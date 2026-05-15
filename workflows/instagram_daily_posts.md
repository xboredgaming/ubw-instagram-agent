# Instagram Daily Posts Workflow

## Objective

Generate and publish four Instagram posts per day — one per board game — using AI-generated images and Claude-written captions. Posts run on a schedule targeting peak engagement windows to build a following ahead of the Kickstarter launch.

## Required Inputs

- `tools/games_config.json` — filled in with all four game details
- `.env` — all API keys set (Anthropic, OpenAI, imgbb, Instagram)
- Instagram Business account linked to Meta Graph API (see One-Time Setup below)

## Tools Used

| Tool | Purpose |
|------|---------|
| `generate_content.py` | Claude API → caption + image prompt |
| `generate_image.py` | OpenAI gpt-image-1 → 1024×1024 PNG |
| `upload_image.py` | imgbb API → public image URL |
| `post_instagram.py` | Meta Graph API → publish post |
| `run_daily_posts.py` | Orchestrates all four steps per game |

## Daily Schedule

| Time | Command | Posts |
|------|---------|-------|
| 11:00 AM | `python tools/run_daily_posts.py --session morning` | Games 1 & 2 (30 min apart) |
| 6:00 PM | `python tools/run_daily_posts.py --session evening` | Games 3 & 4 (30 min apart) |

**To configure Windows Task Scheduler:** See "Scheduling Setup" section below.

## Content Rotation

Claude rotates through four post themes, cycling by day of year so all four appear across the week:

| Theme | What it posts |
|-------|--------------|
| Art Reveal | Showcase game art with atmospheric copy |
| Mechanic Spotlight | Explain a core mechanic in an engaging way |
| Lore Snippet | World-building hook — character, setting, story |
| Kickstarter Countdown | Urgency/excitement copy around the campaign |

The current CTA phase is set in `games_config.json` under `"cta_phase"`. Values:
- `"follow"` — "Follow us for daily updates" (use now)
- `"newsletter"` — "Sign up for early access — link in bio"
- `"kickstarter"` — "We're LIVE on Kickstarter — link in bio"

Update `cta_phase` when you launch the Kickstarter.

## Running Manually

```bash
# Full morning session (games 1 & 2)
python tools/run_daily_posts.py --session morning

# Full evening session (games 3 & 4)
python tools/run_daily_posts.py --session evening

# Single game only
python tools/run_daily_posts.py --session morning --game game-one

# Dry run (generates content + image but does NOT post)
python tools/run_daily_posts.py --session morning --dry-run
```

## Testing Individual Steps

```bash
# Test content generation only
python tools/generate_content.py --game game-one

# Test image generation only
python tools/generate_image.py --game game-one --prompt "A dark fantasy tavern scene with glowing runes"

# Test image upload only
python tools/upload_image.py --file .tmp/your_image.png

# Test Instagram posting (dry run — no actual post)
python tools/post_instagram.py --image-url https://example.com/img.png --caption "Test caption" --dry-run
```

---

## One-Time Setup

### 1. imgbb (Free Image Hosting)

1. Go to imgbb.com and create a free account
2. Go to API → Get API key
3. Add to `.env`: `IMGBB_API_KEY=your_key_here`

### 2. Meta / Instagram API Setup

**Step 1 — Convert Instagram to a Business or Creator account**
- Instagram app → Settings → Account → Switch to Professional Account
- Choose "Business" and connect to a Facebook Page (create one if needed)

**Step 2 — Create a Meta Developer App**
1. Go to developers.facebook.com
2. Create a new app → type: "Business"
3. In the app dashboard, add the product: **Instagram Graph API**

**Step 3 — Get your Instagram Business Account ID**
1. In your Meta app, go to Instagram Graph API → Getting Started
2. Use the Graph API Explorer tool to call `GET /me?fields=id,username` with your token
3. Or look it up in Instagram Settings → Account → Professional Dashboard

**Step 4 — Generate a Long-Lived Access Token**
1. In Graph API Explorer, select your app and get a short-lived token
2. Exchange it for a 60-day long-lived token:
   ```
   GET https://graph.instagram.com/access_token?
       grant_type=ig_exchange_token&
       client_id={app-id}&
       client_secret={app-secret}&
       access_token={short-lived-token}
   ```
3. Store in `.env`:
   ```
   INSTAGRAM_ACCESS_TOKEN=your_long_lived_token_here
   INSTAGRAM_ACCOUNT_ID=your_numeric_account_id_here
   ```

**Step 5 — Verify the token works**
```bash
python tools/post_instagram.py --image-url https://picsum.photos/1024 --caption "Test post" --dry-run
```

**Token refresh reminder:** Long-lived tokens expire after 60 days. Refresh before expiry by calling:
```
GET https://graph.instagram.com/refresh_access_token?
    grant_type=ig_refresh_token&
    access_token={current_token}
```
Set a calendar reminder every 50 days.

### 3. Fill in Game Configs

Edit `tools/games_config.json`. For each game replace all `FILL IN` placeholders:
- `name` — the game's name
- `description` — one detailed paragraph covering theme, setting, and core mechanics
- `visual_style` — describe the art direction (style, palette, mood, influences)
- `hashtags` — 5–10 tags including game-specific ones
- `session` — `"morning"` or `"evening"` (two games per session)

### 4. Windows Task Scheduler

Create two scheduled tasks:

**Morning task (11:00 AM daily)**
- Action: `python "C:\path\to\agentic workflows\tools\run_daily_posts.py" --session morning`
- Start in: `C:\path\to\agentic workflows`
- Trigger: Daily at 11:00 AM

**Evening task (6:00 PM daily)**
- Action: `python "C:\path\to\agentic workflows\tools\run_daily_posts.py" --session evening`
- Start in: `C:\path\to\agentic workflows`
- Trigger: Daily at 6:00 PM

Make sure to set the correct timezone in Task Scheduler properties.

---

## Troubleshooting

| Error | Likely cause | Fix |
|-------|-------------|-----|
| `ANTHROPIC_API_KEY not set` | Missing .env key | Add key to `.env` |
| `OPENAI_API_KEY not set` | Missing .env key | Add key to `.env` |
| `imgbb upload failed` | Bad API key or network | Verify `IMGBB_API_KEY` in .env |
| `Failed to create media container` | Bad Instagram token or account ID | Re-check `.env` values; token may have expired |
| `OAuthException: (#10)` | Instagram account not Business type | Switch account to Business in Instagram app |
| `JSONDecodeError` from generate_content.py | Claude returned non-JSON | Retry; if recurring, check API key credits |
| Task Scheduler doesn't run | Python not in PATH | Use full path to python.exe in the task action |

---

## Known Constraints

- Instagram API limit: 25 published posts per 24-hour period (we use 4)
- `gpt-image-1` images are generated as base64 and saved locally before upload
- imgbb images are set to expire after 24 hours — this is fine because Instagram stores the image permanently at post time
- Long-lived access tokens expire after 60 days; must be manually refreshed

---

## Improvement Ideas

- Add a post log (CSV or Google Sheet) to track what was posted each day
- Rotate which games post in morning vs. evening to vary exposure
- Add carousel posts for mechanic explainers (multiple images per post)
- Auto-refresh Instagram token before expiry using a scheduled script
