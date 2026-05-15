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
            f"${p.get('openai_image_cost_usd',0):.4f}     "
            f"${p.get('total_cost_usd',0):.5f}"
        )

    lines += [
        "-" * 80,
        f"TOTALS",
        f"  Claude API : {totals.get('claude_input_tokens',0):,} input + "
            f"{totals.get('claude_output_tokens',0):,} output tokens "
            f"→ ${totals.get('claude_cost_usd',0):.5f}",
        f"  OpenAI     : {totals.get('openai_images',0)} image(s) "
            f"→ ${totals.get('openai_image_cost_usd',0):.4f}",
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
    args = parser.parse_args()

    if args.test:
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
