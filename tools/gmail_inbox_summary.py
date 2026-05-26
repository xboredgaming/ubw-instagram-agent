"""
Daily Gmail inbox summary for Unlimited Board Works.

Searches priority labels for emails received in the last 24 hours,
composes an AI-ranked summary using Claude Haiku, and sends it via SMTP.

Schedule: 23:00 UTC daily (6:00 PM Lima / PET)
Run manually: python tools/gmail_inbox_summary.py
"""

import json
import os
import smtplib
import sys
from datetime import date, datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import anthropic
import requests
from dotenv import load_dotenv

load_dotenv()

RECIPIENT = "xboredgaming@gmail.com"

# Priority labels in order (Legal first, Uncategorized last)
PRIORITY_LABELS = [
    {"id": "Label_7", "name": "Legal"},
    {"id": "Label_6", "name": "Finance"},
    {"id": "Label_8", "name": "Team"},
    {"id": "Label_5", "name": "Kickstarter"},
    {"id": "Label_4", "name": "Manufacturers"},
    {"id": "Label_3", "name": "Artists"},
]

# Labels to skip when checking for uncategorized inbox emails
SKIP_LABEL_IDS = {
    "Label_3", "Label_4", "Label_5", "Label_6",
    "Label_7", "Label_8", "Label_9", "Label_10", "Label_11", "Label_12",
    "CATEGORY_PROMOTIONS", "CATEGORY_SOCIAL", "CATEGORY_UPDATES",
}


def get_access_token() -> str:
    resp = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id":     os.environ["GMAIL_CLIENT_ID"],
            "client_secret": os.environ["GMAIL_CLIENT_SECRET"],
            "refresh_token": os.environ["GMAIL_REFRESH_TOKEN"],
            "grant_type":    "refresh_token",
        },
        timeout=15,
    )
    if not resp.ok:
        print(f"[inbox-summary] Token error {resp.status_code}: {resp.text}", file=sys.stderr)
        resp.raise_for_status()
    return resp.json()["access_token"]


def fetch_email_metadata(token: str, msg_id: str) -> dict:
    resp = requests.get(
        f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg_id}",
        params={"format": "metadata", "metadataHeaders": ["From", "Subject"]},
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    hdrs = {h["name"]: h["value"] for h in data.get("payload", {}).get("headers", [])}
    return {
        "id":      msg_id,
        "labels":  data.get("labelIds", []),
        "from":    hdrs.get("From", "Unknown"),
        "subject": hdrs.get("Subject", "(no subject)"),
        "snippet": data.get("snippet", ""),
    }


def search_label(token: str, label_id: str, since_hours: int = 25) -> list[dict]:
    after_ts = int((datetime.now(timezone.utc) - timedelta(hours=since_hours)).timestamp())
    resp = requests.get(
        "https://gmail.googleapis.com/gmail/v1/users/me/messages",
        params={"labelIds": label_id, "q": f"after:{after_ts}", "maxResults": 20},
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    resp.raise_for_status()
    messages = resp.json().get("messages", [])
    return [fetch_email_metadata(token, m["id"]) for m in messages]


def search_uncategorized(token: str, since_hours: int = 25) -> list[dict]:
    after_ts = int((datetime.now(timezone.utc) - timedelta(hours=since_hours)).timestamp())
    resp = requests.get(
        "https://gmail.googleapis.com/gmail/v1/users/me/messages",
        params={"labelIds": "INBOX", "q": f"after:{after_ts}", "maxResults": 30},
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    resp.raise_for_status()
    messages = resp.json().get("messages", [])

    results = []
    for msg in messages:
        email = fetch_email_metadata(token, msg["id"])
        if not set(email["labels"]) & SKIP_LABEL_IDS:
            results.append(email)
    return results


def compose_summary(email_data: dict[str, list]) -> str:
    has_any = any(emails for emails in email_data.values())
    if not has_any:
        return "No priority emails today. Inbox is clear."

    sections = []
    for label_name, emails in email_data.items():
        if emails:
            lines = [f"--- {label_name} ---"]
            for e in emails:
                lines.append(f"From: {e['from']}")
                lines.append(f"Subject: {e['subject']}")
                lines.append(f"Preview: {e['snippet'][:120]}")
                lines.append("")
            sections.append("\n".join(lines))

    raw = "\n".join(sections)
    action_labels = {"Legal", "Finance", "Team", "Kickstarter", "Manufacturers", "Artists"}
    action_count = sum(len(v) for k, v in email_data.items() if k in action_labels)

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": (
                "You are a daily briefing assistant for Rodrigo, CEO of Unlimited Board Works "
                "(pre-launch board game company, Lima, Peru).\n\n"
                "Here are emails from the last 24 hours grouped by label:\n\n"
                f"{raw}\n\n"
                "Write a clean daily email summary. Rules:\n"
                "- Keep the section order as given (Legal first, Uncategorized last)\n"
                "- For each email: one line with sender name, subject, and a 5-10 word note on what it's about\n"
                "- Skip empty sections entirely\n"
                "- Keep it scannable — this is a briefing, not a wall of text\n"
                f"- End with exactly: '{action_count} email(s) requiring attention today'\n"
                "- Plain text only, no markdown symbols or bullet characters"
            ),
        }],
    )
    return message.content[0].text


def send_summary(subject: str, body: str) -> bool:
    sender   = os.environ["GMAIL_SENDER"]
    password = os.environ["GMAIL_APP_PASSWORD"].replace(" ", "")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = sender
    msg["To"]      = RECIPIENT
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as smtp:
            smtp.login(sender, password)
            smtp.send_message(msg)
        print(f"[inbox-summary] Sent: {subject}")
        return True
    except Exception as e:
        print(f"[inbox-summary] Failed to send: {e}", file=sys.stderr)
        return False


def main():
    today = date.today().strftime("%B %d, %Y")
    print("[inbox-summary] Fetching Gmail access token...")
    token = get_access_token()

    email_data = {}
    for label in PRIORITY_LABELS:
        print(f"[inbox-summary] Searching {label['name']}...")
        emails = search_label(token, label["id"])
        email_data[label["name"]] = emails
        print(f"  -> {len(emails)} email(s)")

    print("[inbox-summary] Searching uncategorized inbox...")
    uncategorized = search_uncategorized(token)
    if uncategorized:
        email_data["Uncategorized"] = uncategorized
        print(f"  -> {len(uncategorized)} email(s)")

    print("[inbox-summary] Composing summary with Claude...")
    body = compose_summary(email_data)

    subject = f"Daily Email Summary -- {today}"
    success = send_summary(subject, body)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
