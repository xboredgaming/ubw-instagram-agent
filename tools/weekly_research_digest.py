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

# BGG Board Game Design forum (public XML API, no auth required)
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


# ---------------------------------------------------------------------------
# Data sources
# ---------------------------------------------------------------------------

def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def fetch_bgg_forum(forum_id: int, forum_name: str) -> list[dict]:
    """Fetch recent threads from a BGG forum via the XML API."""
    try:
        resp = requests.get(
            "https://boardgamegeek.com/xmlapi2/forum",
            params={"id": forum_id, "page": 1},
            timeout=20,
        )
        resp.raise_for_status()
    except Exception as e:
        print(f"[digest] BGG forum {forum_id} failed: {e}", file=sys.stderr)
        return []

    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError as e:
        print(f"[digest] BGG XML parse error: {e}", file=sys.stderr)
        return []

    since  = datetime.now(timezone.utc) - timedelta(days=14)
    posts  = []

    for thread in root.findall(".//thread"):
        title = thread.get("subject", "").strip()
        tid   = thread.get("id", "")
        if not title or not tid:
            continue

        # Parse last-post date
        lastpost_str = thread.get("lastpostdate", "")
        try:
            # BGG format: "Mon, 26 May 2026 10:00:00 +0000" or similar
            from email.utils import parsedate_to_datetime
            pub_date = parsedate_to_datetime(lastpost_str)
            if pub_date.tzinfo is None:
                pub_date = pub_date.replace(tzinfo=timezone.utc)
            if pub_date < since:
                continue
        except Exception:
            pass  # Include if we can't parse

        posts.append({
            "title":  title,
            "url":    f"https://boardgamegeek.com/thread/{tid}",
            "text":   "",
            "source": f"BGG / {forum_name}",
        })

        if len(posts) >= 20:
            break

    return posts


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


def fetch_reddit_oauth() -> list[dict]:
    client_id     = os.environ.get("REDDIT_CLIENT_ID", "")
    client_secret = os.environ.get("REDDIT_CLIENT_SECRET", "")
    username      = os.environ.get("REDDIT_USERNAME", "")
    password      = os.environ.get("REDDIT_PASSWORD", "")
    if not all([client_id, client_secret, username, password]):
        return []

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
        return []

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

    print(f"[digest] Reddit OAuth: {len(posts)} posts")
    return posts


def gather_posts() -> list[dict]:
    all_posts: list[dict] = []
    seen_urls: set = set()

    def add(posts: list[dict]):
        for p in posts:
            if p["url"] not in seen_urls:
                seen_urls.add(p["url"])
                all_posts.append(p)

    print("[digest] Fetching BGG forums...")
    for name, fid in BGG_FORUM_IDS:
        posts = fetch_bgg_forum(fid, name)
        add(posts)
        print(f"  -> {len(posts)} threads from BGG / {name}")

    print("[digest] Fetching Hacker News (30d)...")
    hn_count = 0
    for query in HN_QUERIES:
        posts = fetch_hn(query)
        before = len(all_posts)
        add(posts)
        hn_count += len(all_posts) - before
    print(f"  -> {hn_count} new HN posts")

    add(fetch_reddit_oauth())

    print(f"[digest] Total: {len(all_posts)} posts")
    return all_posts


# ---------------------------------------------------------------------------
# Digest composition
# ---------------------------------------------------------------------------

def compose_digest_from_posts(posts: list[dict], week_date: str) -> str:
    games_ctx  = "\n".join(f"- {n}: {d}" for n, d in GAMES)
    posts_text = []
    for p in posts[:50]:
        line = f"[{p['source']}] {p['title']}\nURL: {p['url']}"
        if p.get("text"):
            line += f"\n{p['text']}"
        posts_text.append(line)
    posts_block = "\n\n---\n\n".join(posts_text)

    prompt = f"""You are a research assistant for Unlimited Board Works, a small bootstrapped board game studio in Lima, Peru.

Games in development:
{games_ctx}

Recent posts from board game design communities:
{posts_block}

Produce the weekly research digest in EXACTLY this format:

---
# UBW Weekly Research Digest
*Week of: {week_date}*

## Mechanic Ideas

| Idea | How it works | Source URL | Best fit |
|---|---|---|---|
[3–8 rows. Only include genuine mechanics from the posts. Never fabricate.]

### Notable finds
[2–3 sentences on the most interesting mechanics this week]

---

## Lore Inspiration

| Hook | Description | Source URL | Best fit |
|---|---|---|---|
[3–8 rows. Only include genuine worldbuilding/lore hooks. Never fabricate.]

### Notable finds
[2–3 sentences on the most interesting lore finds this week]

---

## Top 3 Recommendations
1. [Most actionable finding — one sentence]
2. [Second — one sentence]
3. [Third — one sentence]

---
*Generated by UBW Research Agent*
---

Rules: Only use posts above. If a category has fewer than 3 real results, say so. Best fit: To Be The One | Dead Man's Tide | Ashen Kingdom | High Noon Saloon | All."""

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    ).content[0].text.strip()


def compose_digest_knowledge_mode(week_date: str) -> str:
    """Fallback: generate digest from Claude's design knowledge when external sources are thin."""
    games_ctx = "\n".join(f"- {n}: {d}" for n, d in GAMES)

    prompt = f"""You are a research assistant for Unlimited Board Works, a small bootstrapped board game studio in Lima, Peru.

Games in development:
{games_ctx}

External sources were unavailable this week (cloud IP restrictions). Generate a weekly research digest from your knowledge of current board game design trends, interesting mechanics, and worldbuilding approaches relevant to these four games.

Be creative and specific — pick mechanics and lore hooks that are genuinely useful for these game themes. Do NOT fabricate source URLs; use "Knowledge Base" as the source for all rows.

Produce the digest in EXACTLY this format:

---
# UBW Weekly Research Digest
*Week of: {week_date}*
*Note: Generated from design knowledge base — external sources unavailable this week.*

## Mechanic Ideas

| Idea | How it works | Source | Best fit |
|---|---|---|---|
[6–8 rows of genuinely interesting, specific mechanics]

### Notable finds
[2–3 sentences on the most interesting mechanics this week]

---

## Lore Inspiration

| Hook | Description | Source | Best fit |
|---|---|---|---|
[6–8 rows of specific, evocative worldbuilding hooks]

### Notable finds
[2–3 sentences on the most interesting lore finds this week]

---

## Top 3 Recommendations
1. [Most actionable for the current games — one sentence]
2. [Second — one sentence]
3. [Third — one sentence]

---
*Generated by UBW Research Agent*
---

Be specific and useful — avoid generic advice. Best fit: To Be The One | Dead Man's Tide | Ashen Kingdom | High Noon Saloon | All."""

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    ).content[0].text.strip()


def compose_digest(posts: list[dict], week_date: str) -> str:
    if len(posts) >= MIN_POSTS:
        print(f"[digest] Composing from {len(posts)} external posts...")
        return compose_digest_from_posts(posts, week_date)
    print(f"[digest] Only {len(posts)} posts found — using knowledge mode...")
    return compose_digest_knowledge_mode(week_date)


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
    week_date = date.today().strftime("%Y-%m-%d")
    posts     = gather_posts()
    body      = compose_digest(posts, week_date)
    success   = send_digest(f"UBW Weekly Research Digest — {week_date}", body)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
