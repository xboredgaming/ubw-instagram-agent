"""
Orchestrator: generates content, image, uploads, and posts to Instagram.

Slot-based (used by scheduler — one game per call):
    python tools/run_daily_posts.py --slot 1
    python tools/run_daily_posts.py --slot 3 --dry-run

Session-based (manual runs — two games per call):
    python tools/run_daily_posts.py --session morning
    python tools/run_daily_posts.py --session morning --dry-run
    python tools/run_daily_posts.py --session morning --game dead-mans-tide
"""

import argparse
import json
import os
import sys
import time
from datetime import date, datetime
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).parent))

from generate_content import load_game, generate_content, pick_theme
from generate_image   import generate_image
from create_reel      import create_reel
from upload_video     import upload_video
from post_instagram   import post_reel_to_instagram
from send_alert       import send_billing_alert

TMP_DIR = Path(__file__).parent.parent / ".tmp"
TMP_DIR.mkdir(exist_ok=True)

KIE_IMAGE_COST_USD = float(os.getenv("KIE_IMAGE_COST_USD", "0.04"))

MAX_POST_RETRIES  = 3
POST_RETRY_DELAY  = 10  # seconds between Instagram post retries


def _post_with_retry(video_url: str, caption: str, hashtags: list, dry_run: bool, slug: str) -> str:
    last_err = None
    for attempt in range(1, MAX_POST_RETRIES + 1):
        try:
            return post_reel_to_instagram(
                video_url=video_url,
                caption=caption,
                hashtags=hashtags,
                dry_run=dry_run,
            )
        except RuntimeError as e:
            last_err = e
            print(f"[{slug}] Instagram post attempt {attempt}/{MAX_POST_RETRIES} failed: {e}",
                  file=sys.stderr)
            if attempt < MAX_POST_RETRIES:
                print(f"[{slug}] Retrying in {POST_RETRY_DELAY}s...", file=sys.stderr)
                time.sleep(POST_RETRY_DELAY)
    raise last_err


# ── Cost log helpers ─────────────────────────────────────────────────────────

def _log_path() -> Path:
    return TMP_DIR / f"costs_{date.today()}.json"

def _load_log() -> dict:
    p = _log_path()
    if p.exists():
        with open(p) as f:
            return json.load(f)
    return {"date": str(date.today()), "posts": [], "totals": {
        "claude_input_tokens": 0, "claude_output_tokens": 0, "claude_cost_usd": 0.0,
        "kie_images": 0, "kie_image_cost_usd": 0.0, "total_cost_usd": 0.0,
    }}

def _save_log(log: dict):
    with open(_log_path(), "w") as f:
        json.dump(log, f, indent=2)

def _record_post(log: dict, entry: dict):
    log["posts"].append(entry)
    t = log["totals"]
    t["claude_input_tokens"]   += entry.get("claude_input_tokens", 0)
    t["claude_output_tokens"]  += entry.get("claude_output_tokens", 0)
    t["claude_cost_usd"]       += entry.get("claude_cost_usd", 0)
    t["kie_images"]         += entry.get("kie_images", 0)
    t["kie_image_cost_usd"] += entry.get("kie_image_cost_usd", 0)
    t["total_cost_usd"]        += entry.get("total_cost_usd", 0)
    _save_log(log)


# ── Single post pipeline ──────────────────────────────────────────────────────

def run_post(game: dict, slot: int, session: str, dry_run: bool) -> dict:
    slug = game["slug"]
    log  = _load_log()
    print(f"\n{'='*50}", file=sys.stderr)
    print(f"[{slug}] Slot {slot} | Starting...", file=sys.stderr)

    entry = {
        "game": slug, "slot": slot,
        "time": datetime.now().isoformat(timespec="seconds"),
        "claude_input_tokens": 0, "claude_output_tokens": 0, "claude_cost_usd": 0.0,
        "kie_images": 0, "kie_image_cost_usd": 0.0, "total_cost_usd": 0.0,
    }

    # Step 1: Generate content via Claude
    print(f"[{slug}] Generating content via Claude...", file=sys.stderr)
    theme = pick_theme()
    try:
        content = generate_content(game, theme, session, slot=slot)
    except anthropic.APIStatusError as e:
        if "billing" in str(e).lower() or "credit" in str(e).lower():
            send_billing_alert("Anthropic (Claude)", str(e))
        entry["error"] = str(e)
        _record_post(log, entry)
        raise

    usage = content.pop("_usage", {})
    entry["claude_input_tokens"]  = usage.get("input_tokens", 0)
    entry["claude_output_tokens"] = usage.get("output_tokens", 0)
    entry["claude_cost_usd"]      = usage.get("cost_usd", 0.0)

    print(f"[{slug}] Theme: {theme} | "
          f"tokens: {entry['claude_input_tokens']}in/{entry['claude_output_tokens']}out | "
          f"cost: ${entry['claude_cost_usd']:.5f}", file=sys.stderr)
    print(f"[{slug}] Caption preview: {content['caption'][:80]}...", file=sys.stderr)

    # Step 2: Generate image
    print(f"[{slug}] Generating image via kie.ai...", file=sys.stderr)
    if dry_run:
        image_path = TMP_DIR / f"{slug}_dry-run.png"
        print(f"[{slug}] [DRY RUN] Skipping image generation", file=sys.stderr)
    else:
        try:
            image_path = generate_image(content["image_prompt"], slug)
            entry["kie_images"]         = 1
            entry["kie_image_cost_usd"] = KIE_IMAGE_COST_USD
        except Exception as e:
            err_str = str(e).lower()
            if "402" in err_str or "payment required" in err_str or "insufficient" in err_str:
                send_billing_alert("Kie.ai", str(e))
            entry["error"] = str(e)
            _record_post(log, entry)
            raise

    # Step 3: Assemble video (image + audio → MP4)
    print(f"[{slug}] Assembling video...", file=sys.stderr)
    if dry_run:
        reel_path = None
        print(f"[{slug}] [DRY RUN] Skipping video assembly", file=sys.stderr)
    else:
        reel_path = create_reel(image_path, slug)

    # Step 4: Upload video to Cloudinary
    print(f"[{slug}] Uploading video to Cloudinary...", file=sys.stderr)
    if dry_run:
        video_url = "https://example.com/dry-run-video.mp4"
        print(f"[{slug}] [DRY RUN] Skipping upload", file=sys.stderr)
    else:
        video_url = upload_video(reel_path)

    # Step 5: Post to Instagram feed (retries up to MAX_POST_RETRIES on transient failures)
    print(f"[{slug}] Posting to Instagram...", file=sys.stderr)
    post_id = _post_with_retry(
        video_url=video_url,
        caption=content["caption"],
        hashtags=content["hashtags"],
        dry_run=dry_run,
        slug=slug,
    )

    entry["post_id"]        = post_id
    entry["video_url"]      = video_url
    entry["total_cost_usd"] = entry["claude_cost_usd"] + entry["kie_image_cost_usd"]
    _record_post(log, entry)

    print(f"[{slug}] Done. Post ID: {post_id} | Total cost: ${entry['total_cost_usd']:.5f}", file=sys.stderr)
    return entry


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--slot",    type=int, choices=range(1, 5),
                      help="Post slot 1–4 (used by Task Scheduler)")
    mode.add_argument("--session", choices=["morning", "midday", "evening"],
                      help="Session name (manual runs: posts 2 games)")
    parser.add_argument("--game",    help="Restrict to one game slug (session mode only)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    config_path = Path(__file__).parent / "games_config.json"
    with open(config_path) as f:
        config = json.load(f)

    cta_phase = config.get("cta_phase", "follow")

    # ── Slot mode (scheduler) ─────────────────────────────────────────────
    if args.slot is not None:
        day_of_week  = date.today().weekday()          # 0=Mon … 5=Sat
        pattern_idx  = day_of_week % 2                 # 0 = even days, 1 = odd days
        rotation     = config["daily_rotation"]
        slug         = rotation[pattern_idx][args.slot - 1]
        game         = load_game(slug)
        game["cta_phase"] = cta_phase
        session      = "morning" if args.slot == 1 else ("midday" if args.slot <= 3 else "evening")

        print(f"Slot {args.slot} | Day pattern {pattern_idx} | Game: {slug} | Dry run: {args.dry_run}",
              file=sys.stderr)
        try:
            result = run_post(game, args.slot, session, args.dry_run)
            print(json.dumps(result, indent=2))
        except Exception as e:
            print(f"ERROR: {e}", file=sys.stderr)
            sys.exit(1)

    # ── Session mode (manual) ─────────────────────────────────────────────
    else:
        if args.game:
            games = [g for g in config["games"] if g["slug"] == args.game]
            if not games:
                print(f"Game '{args.game}' not found.", file=sys.stderr)
                sys.exit(1)
        else:
            games = [g for g in config["games"] if g["session"] == args.session]

        for g in games:
            g["cta_phase"] = cta_phase

        print(f"Session: {args.session} | Games: {[g['slug'] for g in games]} | "
              f"Dry run: {args.dry_run}", file=sys.stderr)

        results = []
        for i, game in enumerate(games):
            try:
                slot_hint = i + 1
                result = run_post(game, slot_hint, args.session, args.dry_run)
                results.append(result)
            except Exception as e:
                print(f"[{game['slug']}] ERROR: {e}", file=sys.stderr)
                results.append({"game": game["slug"], "error": str(e)})

        print("\nSummary:", file=sys.stderr)
        print(json.dumps(results, indent=2), file=sys.stderr)

        if any("error" in r for r in results):
            sys.exit(1)


if __name__ == "__main__":
    main()

