"""
UBW Weekly Research Digest — board game mechanics and lore inspiration.

Data sources (all work from cloud IPs):
  - Hacker News Algolia API (primary — no auth needed)
  - Reddit OAuth (optional — set REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET,
    REDDIT_USERNAME, REDDIT_PASSWORD secrets to enable richer results)

Schedule: 14:00 UTC every Monday (9:00 AM Lima / PET)
Recipients: xboredgaming@gmail.com, unlimitedboredworks@gmail.com
Run manually: python tools/weekly_research_digest.py
"""

import os
import re
import smtplib
import sys
from datetime import date, datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import anthropic
import requests
from dotenv import load_dotenv

load_dotenv()

RECIPIENTS = ["xboredgaming@gmail.com", "unlimitedboredworks@gmail.com"]

GAMES = [
    ("To Be The One",    "cosmic/philosophical — epic tone"),
    ("Dead Man's Tide",  "pirate adventure — treachery tone"),
    ("Ashen Kingdom",    "dark fantasy — grim political tone"),
    ("High Noon Saloon", "western — tense cunning tone"),
]

HN_QUERIES = [
    "board game design mechanic",
    "tabletop game design",
    "board game worldbuilding lore",
    "card game asymmetry",
    "board game player interaction",
]

REDDIT_SUBREDDITS = [
    "boardgamedesign",
    "tabletopgamedesign",
    "boardgames",
]


# ---------------------------------------------------------------------------
# Data sources
# ---------------------------------------------------------------------------

def fetch_hn(query: str, since_days: int = 7) -> list[dict]:
    since_ts = int((datetime.now(timezone.utc) - timedelta(days=since_days)).timestamp())
    try:
        resp = requests.get(
            "https://hn.algolia.com/api/v1/search",
            params={
                "query":          query,
                "tags":           "story",
                "numericFilters": f"created_at_i>{since_ts}",
                "hitsPerPage":    15,
            },
            timeout=15,
        )
        resp.raise_for_status()
    except Exception as e:
        print(f"[digest] HN fetch failed for '{query}': {e}", file=sys.stderr)
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
    """Fetch Reddit posts using OAuth. Only runs if all 4 secrets are present."""
    client_id     = os.environ.get("REDDIT_CLIENT_ID", "")
    client_secret = os.environ.get("REDDIT_CLIENT_SECRET", "")
    username      = os.environ.get("REDDIT_USERNAME", "")
    password      = os.environ.get("REDDIT_PASSWORD", "")

    if not all([client_id, client_secret, username, password]):
        return []

    ua = f"script:ubw-digest:1.0 (by /u/{username})"
    try:
        token_resp = requests.post(
            "https://www.reddit.com/api/v1/access_token",
            auth=requests.auth.HTTPBasicAuth(client_id, client_secret),
            data={"grant_type": "password", "username": username, "password": password},
            headers={"User-Agent": ua},
            timeout=15,
        )
        token_resp.raise_for_status()
        token = token_resp.json()["access_token"]
    except Exception as e:
        print(f"[digest] Reddit OAuth failed: {e}", file=sys.stderr)
        return []

    headers = {"Authorization": f"bearer {token}", "User-Agent": ua}
    since   = datetime.now(timezone.utc) - timedelta(days=7)
    posts   = []

    for sub in REDDIT_SUBREDDITS:
        try:
            resp = requests.get(
                f"https://oauth.reddit.com/r/{sub}/hot",
                params={"limit": 25},
                headers=headers,
                timeout=15,
            )
            resp.raise_for_status()
        except Exception as e:
            print(f"[digest] Reddit r/{sub} failed: {e}", file=sys.stderr)
            continue

        for child in resp.json()["data"]["children"]:
            p       = child["data"]
            created = datetime.fromtimestamp(p["created_utc"], tz=timezone.utc)
            if created < since:
                continue
            title = p.get("title", "").strip()
            if not title:
                continue
            posts.append({
                "title":  title,
                "url":    f"https://reddit.com{p.get('permalink', '')}",
                "text":   re.sub(r"\s+", " ", p.get("selftext") or "").strip()[:500],
                "source": f"r/{sub}",
            })

    print(f"[digest] Reddit OAuth: {len(posts)} posts")
    return posts


def gather_posts() -> list[dict]:
    all_posts: list[dict] = []
    seen_urls: set = set()

    print("[digest] Fetching Hacker News...")
    for query in HN_QUERIES:
        for post in fetch_hn(query):
            if post["url"] not in seen_urls:
                seen_urls.add(post["url"])
                all_posts.append(post)
    print(f"  -> {len(all_posts)} HN posts")

    reddit_posts = fetch_reddit_oauth()
    for post in reddit_posts:
        if post["url"] not in seen_urls:
            seen_urls.add(post["url"])
            all_posts.append(post)

    print(f"[digest] Total: {len(all_posts)} posts")
    return all_posts


# ---------------------------------------------------------------------------
# Digest composition
# ---------------------------------------------------------------------------

def compose_digest(posts: list[dict], week_date: str) -> str:
    if not posts:
        return (
            f"# UBW Weekly Research Digest\n"
            f"*Week of: {week_date}*\n\n"
            "No relevant posts found this week.\n\n"
            "*Generated by UBW Research Agent*"
        )

    games_ctx = "\n".join(f"- {name}: {desc}" for name, desc in GAMES)
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

Below are recent posts from board game design communities. Analyze them and produce the weekly research digest.

POSTS:
{posts_block}

Produce the digest in EXACTLY this format:

---
# UBW Weekly Research Digest
*Week of: {week_date}*

## Mechanic Ideas

| Idea | How it works | Source URL | Best fit |
|---|---|---|---|
[fill rows — at least 3, max 8. Only include genuinely interesting mechanics. Never fabricate.]

### Notable finds
[2-3 sentences on the most interesting mechanic finds this week]

---

## Lore Inspiration

| Hook | Description | Source URL | Best fit |
|---|---|---|---|
[fill rows — at least 3, max 8. Only include genuinely useful lore/worldbuilding hooks. Never fabricate.]

### Notable finds
[2-3 sentences on the most interesting lore finds this week]

---

## Top 3 Recommendations
1. [Most actionable finding and why — one sentence]
2. [Second most actionable — one sentence]
3. [Third most actionable — one sentence]

---
*Generated by UBW Research Agent*
---

Rules:
- Only include findings from the posts above. Never fabricate sources or URLs.
- If a category has fewer than 3 real results, say so honestly rather than padding.
- Each table row: idea name, how it works in 10-15 words, URL, best-fit game.
- Best fit must be one of: To Be The One, Dead Man's Tide, Ashen Kingdom, High Noon Saloon, or All."""

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text.strip()


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
    subject   = f"UBW Weekly Research Digest — {week_date}"

    posts = gather_posts()
    print("[digest] Composing digest with Claude...")
    body = compose_digest(posts, week_date)

    success = send_digest(subject, body)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
