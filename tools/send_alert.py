"""
Email alert utilities for the UBW Instagram agent.
Handles billing alerts and end-of-day cost summaries.

Usage (standalone test):
    python tools/send_alert.py --test
"""

import argparse
import json
import os
import smtplib
import sys
from datetime import date, datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ALERT_RECIPIENT = "xboredgaming@gmail.com"
TMP_DIR = Path(__file__).parent.parent / ".tmp"


def alert_once_today(key: str) -> bool:
    """
    True the first time it's called for `key` today, False after.

    The 4 daily slots would otherwise send the same alert 4x/day for as long as
    the problem lasts. .tmp/ is cached per Lima date, so the marker survives
    across the day's runs.
    """
    TMP_DIR.mkdir(exist_ok=True)
    marker = TMP_DIR / f"alerted_{key}_{date.today()}"
    if marker.exists():
        return False
    marker.touch()
    return True


def _send_email(subject: str, body_text: str, body_html: str = None) -> bool:
    sender   = os.getenv("GMAIL_SENDER")
    password = (os.getenv("GMAIL_APP_PASSWORD") or "").replace(" ", "")

    if not sender or not password or "your_" in password:
        print("[alert] Gmail credentials not configured — skipping email.", file=sys.stderr)
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = sender
    msg["To"]      = ALERT_RECIPIENT

    msg.attach(MIMEText(body_text, "plain"))
    if body_html:
        msg.attach(MIMEText(body_html, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as smtp:
            smtp.login(sender, password)
            smtp.send_message(msg)
        print(f"[alert] Email sent to {ALERT_RECIPIENT}: {subject}", file=sys.stderr)
        return True
    except Exception as e:
        print(f"[alert] Failed to send email: {e}", file=sys.stderr)
        return False


def send_billing_alert(service: str, error_message: str):
    """Send an immediate alert when an API billing limit is hit."""
    subject = f"🚨 UBW Instagram Agent — {service} credits exhausted"
    body = (
        f"The UBW Instagram posting agent has run out of {service} credits.\n\n"
        f"Error: {error_message}\n\n"
        f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        "Action required:\n"
        f"  1. Log in to your {service} account\n"
        "  2. Add credits or raise the billing limit\n"
        "  3. Posts will resume automatically on the next scheduled run\n\n"
        "— UBW Instagram Agent"
    )
    _send_email(subject, body)


def send_token_alert(error_message: str, expiring_in_days: int = None):
    """
    Alert when the Instagram token is dead or about to die.

    Meta's long-lived tokens last 60 days. The May 2026 token lapsed silently on
    2026-07-16 and cost ~4 weeks of posts, so this is deliberately loud.
    """
    alert_once_today("any_alert")  # suppress the generic failure email for the rest of today

    if expiring_in_days is not None:
        subject = f"⚠️ UBW Instagram — access token expires in {expiring_in_days} days"
        opening = (
            f"The Instagram access token still works, but expires in {expiring_in_days} days.\n"
            "Refresh it now and posting continues uninterrupted.\n"
        )
    else:
        subject = "🚨 UBW Instagram — access token expired, posting is DOWN"
        opening = (
            "The Instagram access token is no longer valid. Posting is stopped.\n\n"
            f"Error: {error_message}\n"
        )

    body = (
        f"{opening}\n"
        f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        "To fix (needs your Meta login):\n"
        "  1. Meta Business Suite → Business Settings → Users → System Users\n"
        "  2. Generate a token for the Instagram account with scopes:\n"
        "       instagram_basic, instagram_content_publish, pages_read_engagement\n"
        "     A System User token does not expire — unlike the 60-day user token.\n"
        "  3. Update the INSTAGRAM_ACCESS_TOKEN secret in the\n"
        "     xboredgaming/ubw-instagram-agent repo\n"
        "  4. Posts resume automatically on the next scheduled slot\n\n"
        "Until then the agent skips each run before spending kie.ai credits.\n\n"
        "— UBW Instagram Agent"
    )
    _send_email(subject, body)


def send_failure_alert(context: str, run_url: str = None):
    """
    Alert when a scheduled run fails for a reason not caught upstream.

    Sends at most once per day, and stays quiet entirely if a more specific
    alert (e.g. the token alert, which already explains the fix) went out today.
    A known-broken agent should not mail four times a day.
    """
    if not alert_once_today("any_alert"):
        print("[alert] An alert already went out today — skipping failure email.", file=sys.stderr)
        return

    subject = "🚨 UBW Instagram Agent — scheduled run failed"
    body = (
        "A scheduled run of the UBW Instagram agent failed.\n\n"
        f"Context: {context}\n"
        f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    )
    if run_url:
        body += f"\nLogs: {run_url}\n"
    body += "\n— UBW Instagram Agent"
    _send_email(subject, body)


def send_daily_summary(cost_log_path: Path):
    """Read today's cost log and send a formatted summary email."""
    if not cost_log_path.exists():
        print("[alert] No cost log found — skipping daily summary.", file=sys.stderr)
        return

    with open(cost_log_path) as f:
        log = json.load(f)

    posts     = log.get("posts", [])
    totals    = log.get("totals", {})
    log_date  = log.get("date", str(date.today()))

    # ── Plain-text body ──────────────────────────────────────────────────────
    lines = [
        f"UBW Instagram — Daily Summary ({log_date})",
        f"Posts published: {len(posts)}",
        "",
        f"{'Game':<22} {'Slot':<6} {'Claude in/out':<18} {'Claude $':<10} {'Image $':<10} {'Total $'}",
        "-" * 80,
    ]
    for p in posts:
        if "error" in p:
            lines.append(f"{p['game']:<22} {'Slot '+str(p.get('slot','?')):<6} ERROR: {p['error'][:40]}")
            continue
        lines.append(
            f"{p['game']:<22} "
            f"{'Slot '+str(p.get('slot','?')):<6} "
            f"{str(p.get('claude_input_tokens',0))+'/'+str(p.get('claude_output_tokens',0)):<18} "
            f"${p.get('claude_cost_usd',0):.5f}   "
            f"${p.get('kie_image_cost_usd',0):.4f}     "
            f"${p.get('total_cost_usd',0):.5f}"
        )

    lines += [
        "-" * 80,
        f"TOTALS",
        f"  Claude API : {totals.get('claude_input_tokens',0):,} input + "
            f"{totals.get('claude_output_tokens',0):,} output tokens "
            f"→ ${totals.get('claude_cost_usd',0):.5f}",
        f"  Kie.ai     : {totals.get('kie_images',0)} image(s) "
            f"→ ${totals.get('kie_image_cost_usd',0):.4f}",
        f"  Total today: ${totals.get('total_cost_usd',0):.5f}",
        "",
        "— UBW Instagram Agent",
    ]
    body_text = "\n".join(lines)

    subject = f"UBW Instagram — Daily Summary {log_date} | ${totals.get('total_cost_usd',0):.4f} spent"
    _send_email(subject, body_text)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="Send a test alert email")
    parser.add_argument("--summary", action="store_true", help="Send today's cost summary now")
    parser.add_argument("--failure", metavar="CONTEXT",
                        help="Send a run-failure alert with the given context string")
    parser.add_argument("--run-url", help="Link to the failing workflow run")
    args = parser.parse_args()

    if args.failure:
        send_failure_alert(args.failure, args.run_url)
    elif args.test:
        _send_email(
            "UBW Agent — email test",
            "If you received this, Gmail is configured correctly.\n\n— UBW Instagram Agent"
        )
    elif args.summary:
        log_path = TMP_DIR / f"costs_{date.today()}.json"
        send_daily_summary(log_path)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
