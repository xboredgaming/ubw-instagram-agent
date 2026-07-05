"""
Generates Instagram caption and image prompt for a given game using Claude.
Only loads the relevant brand sections to minimise token usage.

Usage:
    python tools/generate_content.py --game dead-mans-tide
    python tools/generate_content.py --game ashen-kingdom --theme lore_snippet
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import date
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv()

THEMES = ["art_reveal", "mechanic_spotlight", "lore_snippet", "kickstarter_countdown"]

CTA_PHASES = {
    "follow": "Follow @unlimitedboardworks for daily updates.",
    "newsletter": "Sign up for early access — link in bio.",
    "kickstarter": "We're LIVE on Kickstarter — link in bio. Back us today!",
}

# claude-sonnet-4-6 pricing (USD per token)
CLAUDE_INPUT_COST_PER_TOKEN  = 3.00  / 1_000_000
CLAUDE_OUTPUT_COST_PER_TOKEN = 15.00 / 1_000_000

MAX_RETRIES = 3


def load_brand_context_for_game(game_name: str) -> str:
    """Load only Section 1 (brand) + the game-specific section + agent instructions.
    Reduces token usage by ~70% vs. sending the full document every call."""
    context_path = Path(__file__).parent.parent / "ubw_social_media_agent_context.md"
    full_text = context_path.read_text(encoding="utf-8")

    # Split into blocks at each top-level ## header
    blocks = re.split(r'\n(?=## )', full_text)

    brand_block  = next((b for b in blocks if "SECTION 1" in b or "MASTER BRAND" in b), "")
    game_block   = next((b for b in blocks if game_name.upper() in b.upper()), "")
    agent_block  = next((b for b in blocks if "AGENT INSTRUCTIONS" in b), "")

    return "\n\n".join(filter(None, [brand_block, game_block, agent_block]))


def load_game(slug: str) -> dict:
    config_path = Path(__file__).parent / "games_config.json"
    with open(config_path) as f:
        config = json.load(f)
    for game in config["games"]:
        if game["slug"] == slug:
            game["cta_phase"] = config.get("cta_phase", "follow")
            return game
    raise ValueError(f"Game '{slug}' not found in games_config.json")


def pick_theme() -> str:
    return THEMES[date.today().toordinal() % len(THEMES)]


def _resolve_visual_world(game: dict, day_seed: int) -> str:
    """Static games use `visual_world` as-is. Games with `art_rotation` get a
    deterministic register + entity pick (computed here, not left to the model,
    since asking an LLM to do modulo on a date ordinal is asking for drift)."""
    rotation = game.get("art_rotation")
    if not rotation:
        return game.get("visual_world", "")

    registers = rotation["registers"]
    entities  = rotation["entities"]
    register  = registers[day_seed % len(registers)]
    entity    = entities[day_seed % len(entities)]

    return (
        f"{rotation['style']}\n"
        f"Today's register — {register['name']}: {register['prompt']}\n"
        f"Today's entity — {entity['name']}: render the glow/light accents in {entity['color']}. "
        "Reference the entity only through color and mood — never spell out its name or any text."
    )


def generate_content(game: dict, theme: str, session: str, slot: int = 1) -> dict:
    """Returns the content dict with an extra '_usage' key for cost tracking."""
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    brand_context = load_brand_context_for_game(game["name"])
    cta_text = CTA_PHASES.get(game["cta_phase"], CTA_PHASES["follow"])

    system_prompt = (
        "You are the social media agent for Unlimited Board Works (@unlimitedboardworks).\n\n"
        "The following is your brand and game context. Every post must be grounded in this document "
        "— tone, mechanics terminology, and post angles are requirements, not suggestions.\n\n"
        + brand_context
    )

    day_seed = date.today().toordinal()
    visual_world = _resolve_visual_world(game, day_seed)

    user_prompt = (
        f"Generate an Instagram Reel caption for: {game['name']}\n\n"
        f"Post theme: {theme.replace('_', ' ').title()}\n"
        f"CTA: {cta_text}\n"
        f"Day seed: {day_seed}, Slot: {slot} — use both to make this caption and image DISTINCT from every other slot today.\n"
        f"Hashtags (use these exactly, do not add or remove): {json.dumps(game['hashtags'])}\n"
        + (f"Visual world: {visual_world}\n" if visual_world else "")
        + "\nCaption rules:\n"
        "- Apply this game's exact social media tone and post angles from the context above\n"
        "- Hook (first line): scroll-stopping question, bold statement, or intriguing fragment — under 100 characters\n"
        "- Body: 2–3 short punchy sentences, no walls of text\n"
        "- End with the CTA text provided above — use it exactly as written, nothing else\n"
        "- Total caption length: 150–280 characters (not counting hashtags or CTA)\n"
        "- Use 1–3 relevant emojis naturally in the caption — not as bullet points\n"
        "- No hashtags inside the caption text — return them in the JSON hashtags field only\n"
        "- NEVER add a Kickstarter link or URL — the campaign is not live yet. Use the CTA text only.\n"
        "- NEVER write placeholder text like '[KICKSTARTER LINK]', '[LINK]', '[URL]', or any bracketed placeholder.\n"
        "- NEVER add music attribution or licensing text (e.g. 'Music: Kevin MacLeod') — that is handled separately.\n"
        "- NEVER reference, describe, or mention game cards, game components, tokens, or prototype art.\n\n"
        "Image prompt rules:\n"
        "- Depict the game's Visual world — environments, atmosphere, scenes. NO cards, NO components, NO prototype art.\n"
        "- Square 1:1 format. No text, no faces.\n"
        f"- Slot {slot} of 4: choose a COMPLETELY DIFFERENT scene from other slots. "
        "Vary: subject (foreground focus vs wide landscape), lighting (dawn/dusk/night/midday), "
        "weather/atmosphere, camera distance (extreme close-up vs aerial), color palette emphasis.\n"
        "- Each slot must feel like a different film frame from the same world — never the same composition twice.\n\n"
        "Return ONLY valid JSON:\n"
        '{"caption": "...", "hashtags": ["#tag1"], "image_prompt": "..."}'
    )

    _PLACEHOLDER_RE = re.compile(r'\[[A-Z][A-Z _]{2,}\]')

    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            message = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            raw = message.content[0].text.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            result = json.loads(raw.strip())

            caption = result.get("caption", "")
            if _PLACEHOLDER_RE.search(caption):
                raise ValueError(f"Caption contains placeholder text: {caption[:120]!r}")

            result["_usage"] = {
                "input_tokens":  message.usage.input_tokens,
                "output_tokens": message.usage.output_tokens,
                "cost_usd": (
                    message.usage.input_tokens  * CLAUDE_INPUT_COST_PER_TOKEN +
                    message.usage.output_tokens * CLAUDE_OUTPUT_COST_PER_TOKEN
                ),
            }
            return result
        except (json.JSONDecodeError, ValueError) as e:
            last_err = e
            print(f"[generate_content] Attempt {attempt}/{MAX_RETRIES}: {e} — retrying...",
                  file=sys.stderr)
            if attempt < MAX_RETRIES:
                time.sleep(2)

    raise RuntimeError(f"Claude returned invalid content after {MAX_RETRIES} attempts") from last_err


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--game",    required=True, help="Game slug from games_config.json")
    parser.add_argument("--theme",   choices=THEMES, help="Post theme (default: auto-rotates daily)")
    parser.add_argument("--session", choices=["morning", "midday", "evening"], default="morning")
    args = parser.parse_args()

    theme  = args.theme or pick_theme()
    game   = load_game(args.game)
    result = generate_content(game, theme, args.session)

    usage = result.pop("_usage", {})
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"\n[tokens] in={usage.get('input_tokens')} out={usage.get('output_tokens')} "
          f"cost=${usage.get('cost_usd', 0):.5f}", file=sys.stderr)


if __name__ == "__main__":
    main()

