"""
Daily Gmail inbox summary for Unlimited Board Works.

Searches priority labels for emails received in the last 24 hours,
composes an AI-ranked summary using Claude Haiku, and sends it via SMTP.

Uses IMAP + App Password (no OAuth token expiry issues).

Schedule: 23:00 UTC daily (6:00 PM Lima / PET)
Run manually: python tools/gmail_inbox_summary.py
"""

import imaplib
import email as email_lib
import os
import re
import smtplib
import sys
from datetime import date, timedelta
from email.header import decode_header as _decode_raw
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import anthropic
from dotenv import load_dotenv

load_dotenv()

RECIPIENT   = "xboredgaming@gmail.com"
IMAP_SERVER = "imap.gmail.com"
IMAP_PORT   = 993

# Priority labels in order — these are also the IMAP folder names in Gmail
PRIORITY_LABELS = ["Legal", "Finance", "Team", "Kickstarter", "Manufacturers", "Artists"]

# Labels that disqualify an inbox message from being "uncategorized"
SKIP_LABELS = set(PRIORITY_LABELS) | {
    "Social Media", "Tools & Services", "Marketing", "Personal",
    "@Action", "@Waiting",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _decode_header(value: str) -> str:
    if not value:
        return ""
    parts = _decode_raw(value)
    decoded = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(str(part))
    return " ".join(decoded)


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def imap_connect() -> imaplib.IMAP4_SSL:
    sender   = os.environ["GMAIL_SENDER"]
    password = os.environ["GMAIL_APP_PASSWORD"].replace(" ", "")
    mail = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
    mail.login(sender, password)
    return mail


def fetch_details(mail: imaplib.IMAP4_SSL, num: bytes) -> dict | None:
    """Fetch From, Subject, and a short snippet for one message."""
    status, data = mail.fetch(
        num,
        "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT)] BODY.PEEK[TEXT]<0.600>)",
    )
    if status != "OK" or not data:
        return None

    from_val = subject = snippet = ""

    for part in data:
        if not isinstance(part, tuple):
            continue
        raw = part[1]
        if not raw:
            continue
        # Try parsing as headers first (will have From/Subject)
        msg = email_lib.message_from_bytes(raw)
        if msg.get("From"):
            from_val = _decode_header(msg.get("From", ""))
            subject  = _decode_header(msg.get("Subject", "(no subject)"))
        else:
            # Body text
            try:
                text = raw.decode("utf-8", errors="replace")
                text = _strip_html(text)
                snippet = text[:150]
            except Exception:
                pass

    return {"from": from_val, "subject": subject, "snippet": snippet} if from_val else None


# ---------------------------------------------------------------------------
# Search functions
# ---------------------------------------------------------------------------

def search_label(mail: imaplib.IMAP4_SSL, label: str) -> list[dict]:
    since = (date.today() - timedelta(days=1)).strftime("%d-%b-%Y")
    try:
        status, _ = mail.select(f'"{label}"', readonly=True)
        if status != "OK":
            print(f"[inbox-summary] Label not found: {label}", file=sys.stderr)
            return []
    except Exception as e:
        print(f"[inbox-summary] Error selecting '{label}': {e}", file=sys.stderr)
        return []

    status, data = mail.search(None, f"SINCE {since}")
    if status != "OK" or not data[0]:
        return []

    results = []
    for num in data[0].split()[-20:]:
        details = fetch_details(mail, num)
        if details:
            results.append(details)
    return results


def search_uncategorized(mail: imaplib.IMAP4_SSL) -> list[dict]:
    """Return INBOX messages that have none of the skip labels."""
    since = (date.today() - timedelta(days=1)).strftime("%d-%b-%Y")
    mail.select("INBOX", readonly=True)
    status, data = mail.search(None, f"SINCE {since}")
    if status != "OK" or not data[0]:
        return []

    results = []
    for num in data[0].split():
        # Fetch labels and headers in one call
        status, ldata = mail.fetch(num, "(X-GM-LABELS BODY.PEEK[HEADER.FIELDS (FROM SUBJECT)])")
        if status != "OK" or not ldata:
            continue

        labels_raw = ""
        from_val = subject = ""

        for part in ldata:
            if isinstance(part, bytes):
                labels_raw = part.decode("utf-8", errors="replace")
            elif isinstance(part, tuple):
                msg = email_lib.message_from_bytes(part[1])
                from_val = _decode_header(msg.get("From", ""))
                subject  = _decode_header(msg.get("Subject", "(no subject)"))

        # Skip if any priority/low-priority label is present
        if any(lbl.lower() in labels_raw.lower() for lbl in SKIP_LABELS):
            continue

        if from_val:
            results.append({"from": from_val, "subject": subject, "snippet": ""})
        if len(results) >= 20:
            break

    return results


# ---------------------------------------------------------------------------
# Summary composition and delivery
# ---------------------------------------------------------------------------

def compose_summary(email_data: dict[str, list]) -> str:
    has_any = any(emails for emails in email_data.values())
    if not has_any:
        return "No priority emails today. Inbox is clear."

    sections = []
    for label_name, emails in email_data.items():
        if not emails:
            continue
        lines = [f"--- {label_name} ---"]
        for e in emails:
            lines.append(f"From: {e['from']}")
            lines.append(f"Subject: {e['subject']}")
            if e.get("snippet"):
                lines.append(f"Preview: {e['snippet']}")
            lines.append("")
        sections.append("\n".join(lines))

    raw = "\n".join(sections)
    action_labels = {"Legal", "Finance", "Team", "Kickstarter", "Manufacturers", "Artists"}
    action_count  = sum(len(v) for k, v in email_data.items() if k in action_labels)

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
                "- For each email: sender name, subject, and a 5-10 word note on what it's about\n"
                "- Skip empty sections\n"
                "- Keep it scannable — this is a briefing, not a wall of text\n"
                f"- End with: '{action_count} email(s) requiring attention today'\n"
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


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    today = date.today().strftime("%B %d, %Y")
    print("[inbox-summary] Connecting to Gmail via IMAP...")
    mail = imap_connect()

    email_data: dict[str, list] = {}

    for label in PRIORITY_LABELS:
        print(f"[inbox-summary] Searching {label}...")
        emails = search_label(mail, label)
        email_data[label] = emails
        print(f"  -> {len(emails)} email(s)")

    print("[inbox-summary] Searching uncategorized inbox...")
    uncategorized = search_uncategorized(mail)
    if uncategorized:
        email_data["Uncategorized"] = uncategorized
        print(f"  -> {len(uncategorized)} email(s)")

    mail.logout()

    print("[inbox-summary] Composing summary with Claude...")
    body = compose_summary(email_data)

    subject = f"Daily Email Summary -- {today}"
    success = send_summary(subject, body)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
