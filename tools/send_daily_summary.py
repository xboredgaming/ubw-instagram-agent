"""
Sends the end-of-day cost summary email for today's posts.
Scheduled to run at 20:00 (8pm) Mon–Sat via Task Scheduler.

Usage:
    python tools/send_daily_summary.py
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
from send_alert import send_daily_summary

load_dotenv()

if __name__ == "__main__":
    log_path = Path(__file__).parent.parent / ".tmp" / f"costs_{date.today()}.json"
    send_daily_summary(log_path)
