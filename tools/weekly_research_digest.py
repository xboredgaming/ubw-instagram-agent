"""
UBW Weekly Research Digest — board game mechanics and lore inspiration.

Data sources (cloud-IP safe):
  1. BoardGameGeek forum XML API (Board Game Design forum)
  2. Hacker News Algolia API (30-day window, broader queries)
  3. Reddit OAuth (optional — set REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET,
     REDDIT_USERNAME, REDDIT_PASSWORD to enable)
  4. Claude knowledge-mode fallback (when fewer than MIN_POSTS found)

Schedule: 14:00 UTC every Monday (9:00 AM Lima / PET)
Recipients: xboredgaming@gmail.com, unlimitedboredworks@gmail.com
Run manually: python tools/weekly_research_digest.py
"""

import os
import re
import smtplib
import sys
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import anthropic
import requests
from dotenv import load_dotenv

load_dotenv()

RECIPIENTS  = ["xboredgaming@gmail.com", "unlimitedboredworks@gmail.com"]
MIN_POSTS   = 5   # fall back to knowledge mode if fewer posts collected

GAMES = [
    ("To Be The One",    "cosmic/philosophical — epic tone"),
    ("Dead Man's Tide",  "pirate adventure — treachery tone"),
    ("Ashen Kingdom",    "dark fantasy — grim political tone"),
    ("High Noon Saloon", "western — tense cunning tone"),
]

BGG_FORUM_IDS = [
    ("Board Game Design",      974756),
    ("Mechanics & Dynamics",   13),
]

HN_QUERIES = [
    "board game design",
    "tabletop game mechanics",
    "board game lore worldbuilding",
    "card game design asymmetry",
    "game design player interaction",
]

REDDIT_SUBREDDITS = ["boardgamedesign", "tabletopgamedesign", "boardgames"]

SEP = "________________________________________________________________"


# ---------------------------------------------------------------------------
# Data sources
# ---------------------------------------------------------------------------

def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def fetch_bgg_forum(forum_id: int, forum_name: str) -> tuple[list[dict], str]:
    """Returns (posts, status_note)."""
    try:
        resp = requests.get(
            "https://boardgamegeek.com/xmlapi2/forum",
            params={"id": forum_id, "page": 1},
            timeout=20,
        )
        resp.raise_for_status()
    except Exception as e:
        note = f"blocked ({e})"
        print(f"[digest] BGG forum {forum_id} failed: {e}", file=sys.stderr)
        return [], note

    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError as e:
        print(f"[digest] BGG XML parse error: {e}", file=sys.stderr)
        return [], "XML parse error"

    since = datetime.now(timezone.utc) - timedelta(days=14)
    posts = []

    for thread in root.findall(".//thread"):
        title = thread.get("subject", "").strip()
        tid   = thread.get("id", "")
        if not title or not tid:
            continue

        lastpost_str = thread.get("lastpostdate", "")
        try:
            from email.utils import parsedate_to_datetime
            pub_date = parsedate_to_datetime(lastpost_str)
            if pub_date.tzinfo is None:
                pub_date = pub_date.replace(tzinfo=timezone.utc)
            if pub_date < since:
                continue
        except Exception:
            pass

        posts.append({
            "title":  title,
            "url":    f"https://boardgamegeek.com/thread/{tid}",
            "text":   "",
            "source": f"BGG / {forum_name}",
        })

        if len(posts) >= 20:
            break

    note = f"{len(posts)} threads" if posts else "0 threads"
    return posts, note


def fetch_hn(query: str, since_days: int = 30) -> list[dict]:
    since_ts = int((datetime.now(timezone.utc) - timedelta(days=since_days)).timestamp())
    try:
        resp = requests.get(
            "https://hn.algolia.com/api/v1/search",
            params={
                "query":          query,
                "numericFilters": f"created_at_i>{since_ts}",
                "hitsPerPage":    10,
            },
            timeout=15,
        )
        resp.raise_for_status()
    except Exception as e:
        print(f"[digest] HN failed for '{query}': {e}", file=sys.stderr)
        return []

    results = []
    for h in resp.json().get("hits", []):
        title = h.get("title", "").strip()
        if not title:
            continue
        url  = h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}"
        text = re.sub(r"\s+", " ", h.get("story_text") or "").strip()[:400]
        results.append({"title": title, "url": url, "text": text, "source": "Hacker News"})
    return results


def fetch_reddit_oauth() -> tuple[list[dict], str]:
    """Returns (posts, status_note)."""
    client_id     = os.environ.get("REDDIT_CLIENT_ID", "")
    client_secret = os.environ.get("REDDIT_CLIENT_SECRET", "")
    username      = os.environ.get("REDDIT_USERNAME", "")
    password      = os.environ.get("REDDIT_PASSWORD", "")
    if not all([client_id, client_secret, username, password]):
        return [], "credentials not configured"

    ua = f"script:ubw-digest:1.0 (by /u/{username})"
    try:
        tok = requests.post(
            "https://www.reddit.com/api/v1/access_token",
            auth=requests.auth.HTTPBasicAuth(client_id, client_secret),
            data={"grant_type": "password", "username": username, "password": password},
            headers={"User-Agent": ua},
            timeout=15,
        ).json()["access_token"]
    except Exception as e:
        print(f"[digest] Reddit OAuth failed: {e}", file=sys.stderr)
        return [], f"OAuth failed ({e})"

    hdrs  = {"Authorization": f"bearer {tok}", "User-Agent": ua}
    since = datetime.now(timezone.utc) - timedelta(days=7)
    posts = []

    for sub in REDDIT_SUBREDDITS:
        try:
            data = requests.get(
                f"https://oauth.reddit.com/r/{sub}/hot",
                params={"limit": 25},
                headers=hdrs,
                timeout=15,
            ).json()
        except Exception as e:
            print(f"[digest] Reddit r/{sub}: {e}", file=sys.stderr)
            continue

        for child in data["data"]["children"]:
            p = child["data"]
            if datetime.fromtimestamp(p["created_utc"], tz=timezone.utc) < since:
                continue
            title = p.get("title", "").strip()
            if title:
                posts.append({
                    "title":  title,
                    "url":    f"https://reddit.com{p.get('permalink', '')}",
                    "text":   re.sub(r"\s+", " ", p.get("selftext") or "")[:500],
                    "source": f"r/{sub}",
                })

    note = f"{len(posts)} posts" if posts else "0 posts"
    print(f"[digest] Reddit OAuth: {len(posts)} posts")
    return posts, note


def gather_posts() -> tuple[list[dict], list[str]]:
    """Returns (posts, source_notes_for_research_section)."""
    all_posts: list[dict] = []
    seen_urls: set = set()
    source_notes: list[str] = []

    def add(posts: list[dict]):
        for p in posts:
            if p["url"] not in seen_urls:
                seen_urls.add(p["url"])
                all_posts.append(p)

    print("[digest] Fetching BGG forums...")
    for name, fid in BGG_FORUM_IDS:
        posts, note = fetch_bgg_forum(fid, name)
        add(posts)
        source_notes.append(f"BGG {name} forum — {note}")
        print(f"  -> {len(posts)} threads from BGG / {name}")

    print("[digest] Fetching Hacker News (30d)...")
    hn_count = 0
    for query in HN_QUERIES:
        posts = fetch_hn(query)
        before = len(all_posts)
        add(posts)
        hn_count += len(all_posts) - before
    hn_note = f"{hn_count} posts" if hn_count else "0 posts (topic too sparse in 30-day window)"
    source_notes.append(f"Hacker News (30-day window, {len(HN_QUERIES)} queries) — {hn_note}")
    print(f"  -> {hn_count} new HN posts")

    reddit_posts, reddit_note = fetch_reddit_oauth()
    add(reddit_posts)
    source_notes.append(
        f"Reddit (r/boardgamedesign, r/tabletopgamedesign, r/boardgames) — {reddit_note}"
    )

    print(f"[digest] Total: {len(all_posts)} posts")
    return all_posts, source_notes


# ---------------------------------------------------------------------------
# Digest composition
# ---------------------------------------------------------------------------

FORMAT_INSTRUCTIONS = """Produce the digest in EXACTLY this plain-text format. No markdown, no asterisks, no pound signs, no pipes, no table syntax.

________________________________________________________________
RESEARCH NOTES
________________________________________________________________

Sources searched this week:
{SOURCE_NOTES}

{If all sources were blocked or returned 0 results, add one line: "All findings this week are sourced from design knowledge base — live community data was unavailable."}

________________________________________________________________
MECHANIC IDEAS
________________________________________________________________

1. TITLE OF MECHANIC IN ALL CAPS
Best fit: Game Name
How it works: One to three sentences describing the mechanic, referencing real game examples where possible.
Source: Full URL or "Knowledge Base"

[Repeat for 5-8 entries]

Notable finds:
2-3 sentence paragraph highlighting the most actionable mechanics and why they matter for the games.

________________________________________________________________
LORE INSPIRATION
________________________________________________________________

1. TITLE OF LORE HOOK IN ALL CAPS
Best fit: Game Name
Description: One to three sentences describing the worldbuilding or lore concept and its source.
Source: Full URL or "Knowledge Base"

[Repeat for 5-8 entries]

Notable finds:
2-3 sentence paragraph on the strongest lore themes this week.

________________________________________________________________
TOP 3 RECOMMENDATIONS
________________________________________________________________

1. TITLE IN ALL CAPS
One sentence — specific, actionable, tied to a concrete game.

2. TITLE IN ALL CAPS
One sentence.

3. TITLE IN ALL CAPS
One sentence.

________________________________________________________________
Generated by UBW Research Agent | {WEEK_DATE}"""


def compose_digest_from_posts(posts: list[dict], week_date: str, source_notes: list[str]) -> str:
    games_ctx  = "\n".join(f"- {n}: {d}" for n, d in GAMES)
    posts_text = []
    for p in posts[:50]:
        line = f"[{p['source']}] {p['title']}\nURL: {p['url']}"
        if p.get("text"):
            line += f"\n{p['text']}"
        posts_text.append(line)
    posts_block = "\n\n---\n\n".join(posts_text)

    source_block = "\n".join(f"• {n}" for n in source_notes)
    fmt = FORMAT_INSTRUCTIONS.replace("{SOURCE_NOTES}", source_block).replace("{WEEK_DATE}", week_date)

    prompt = f"""You are a research assistant for Unlimited Board Works, a small bootstrapped board game studio in Lima, Peru.

Games in development:
{games_ctx}

Recent posts from board game design communities:
{posts_block}

{fmt}

Rules: Only use content from the posts above. If a section has fewer than 3 real results from the posts, supplement with knowledge-base entries and label them "Knowledge Base". Best fit options: To Be The One | Dead Man's Tide | Ashen Kingdom | High Noon Saloon | All."""

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=3000,
        messages=[{"role": "user", "content": prompt}],
    ).content[0].text.strip()


def compose_digest_knowledge_mode(week_date: str, source_notes: list[str]) -> str:
    games_ctx    = "\n".join(f"- {n}: {d}" for n, d in GAMES)
    source_block = "\n".join(f"• {n}" for n in source_notes)
    fmt = FORMAT_INSTRUCTIONS.replace("{SOURCE_NOTES}", source_block).replace("{WEEK_DATE}", week_date)

    prompt = f"""You are a research assistant for Unlimited Board Works, a small bootstrapped board game studio in Lima, Peru.

Games in development:
{games_ctx}

Live community sources were unavailable this week (cloud IP restrictions). Generate a weekly research digest from your knowledge of current board game design trends, interesting mechanics, and worldbuilding approaches relevant to these four games.

Be specific — reference real published games, designers, and studios where possible. Use "Knowledge Base" as the source for all entries.

{fmt}

Rules: Be specific and useful — avoid generic advice. Reference real games and designers. Best fit options: To Be The One | Dead Man's Tide | Ashen Kingdom | High Noon Saloon | All."""

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=3000,
        messages=[{"role": "user", "content": prompt}],
    ).content[0].text.strip()


def compose_digest(posts: list[dict], week_date: str, source_notes: list[str]) -> str:
    if len(posts) >= MIN_POSTS:
        print(f"[digest] Composing from {len(posts)} external posts...")
        return compose_digest_from_posts(posts, week_date, source_notes)
    print(f"[digest] Only {len(posts)} posts found — using knowledge mode...")
    return compose_digest_knowledge_mode(week_date, source_notes)


# ---------------------------------------------------------------------------
# Email delivery
# ---------------------------------------------------------------------------

def send_digest(subject: str, body: str) -> bool:
    sender   = os.environ["GMAIL_SENDER"]
    password = os.environ["GMAIL_APP_PASSWORD"].replace(" ", "")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = sender
    msg["To"]      = ", ".join(RECIPIENTS)
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as smtp:
            smtp.login(sender, password)
            smtp.sendmail(sender, RECIPIENTS, msg.as_string())
        print(f"[digest] Sent to {', '.join(RECIPIENTS)}")
        return True
    except Exception as e:
        print(f"[digest] Send failed: {e}", file=sys.stderr)
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    week_date          = date.today().strftime("%Y-%m-%d")
    posts, source_notes = gather_posts()
    body               = compose_digest(posts, week_date, source_notes)
    success            = send_digest(f"UBW Weekly Research Digest — {week_date}", body)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
