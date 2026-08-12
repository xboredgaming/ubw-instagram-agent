"""
Preflight check for the Instagram Graph API access token.

Meta's long-lived tokens expire after 60 days. When one lapses, a posting run
still pays for a caption and an image before dying at the final publish step —
so this runs FIRST, before anything costs money.

It also reports days-to-expiry when Meta will tell us, so the next expiry is a
warning email rather than a silent outage.

Usage:
    python tools/check_token.py                 # exit 1 if the token is dead
    python tools/check_token.py --warn-days 14  # also warn if expiry is near
"""

import argparse
import os
import sys
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

load_dotenv()

GRAPH_API_BASE = "https://graph.facebook.com/v21.0"

# Meta's OAuth error class. Subcode 463 is specifically "token expired".
OAUTH_ERROR_CODE = 190

DEFAULT_WARN_DAYS = 14


class TokenInvalid(RuntimeError):
    """The Instagram access token is expired, revoked, or malformed."""


def _expires_in_days() -> int | None:
    """
    Days until the token expires, or None if Meta won't say.

    Best-effort only: debug_token normally wants an app token as the inspecting
    credential, so this can legitimately fail even when the token is fine. A
    return of -1 means the token never expires (a System User token).
    """
    token = os.getenv("INSTAGRAM_ACCESS_TOKEN")
    try:
        resp = requests.get(
            f"{GRAPH_API_BASE}/debug_token",
            params={"input_token": token, "access_token": token},
            timeout=15,
        )
        if not resp.ok:
            return None
        expires_at = resp.json().get("data", {}).get("expires_at")
        if expires_at is None:
            return None
        if expires_at == 0:  # 0 means "never expires"
            return -1
        delta = datetime.fromtimestamp(expires_at, tz=timezone.utc) - datetime.now(timezone.utc)
        return delta.days
    except requests.RequestException:
        return None


def check_token(warn_days: int = DEFAULT_WARN_DAYS) -> dict:
    """
    Verify the token can still reach the Instagram account.

    Returns a status dict on success. Raises TokenInvalid if the token is dead —
    call this before spending any money on content generation.
    """
    token      = os.getenv("INSTAGRAM_ACCESS_TOKEN")
    account_id = os.getenv("INSTAGRAM_ACCOUNT_ID")

    if not token or not account_id:
        raise TokenInvalid("INSTAGRAM_ACCESS_TOKEN and INSTAGRAM_ACCOUNT_ID must be set")

    # Cheapest possible authenticated call against the account we post to.
    resp = requests.get(
        f"{GRAPH_API_BASE}/{account_id}",
        params={"fields": "id,username", "access_token": token},
        timeout=15,
    )

    if not resp.ok:
        err  = resp.json().get("error", {}) if resp.headers.get("content-type", "").startswith("application/json") else {}
        code = err.get("code")
        msg  = err.get("message", resp.text)
        if code == OAUTH_ERROR_CODE:
            raise TokenInvalid(f"Instagram token rejected by Meta: {msg}")
        raise TokenInvalid(f"Instagram token check failed ({resp.status_code}): {msg}")

    username = resp.json().get("username", "unknown")
    days     = _expires_in_days()

    status = {"username": username, "expires_in_days": days, "expiring_soon": False}

    if days is None:
        print(f"[token] OK — @{username} (expiry unknown)", file=sys.stderr)
    elif days < 0:
        print(f"[token] OK — @{username} (never expires)", file=sys.stderr)
    else:
        print(f"[token] OK — @{username} (expires in {days} days)", file=sys.stderr)
        status["expiring_soon"] = days <= warn_days

    return status


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--warn-days", type=int, default=DEFAULT_WARN_DAYS,
                        help=f"Warn if the token expires within N days (default {DEFAULT_WARN_DAYS})")
    args = parser.parse_args()

    try:
        status = check_token(args.warn_days)
    except TokenInvalid as e:
        print(f"[token] DEAD — {e}", file=sys.stderr)
        sys.exit(1)

    if status["expiring_soon"]:
        print(f"[token] WARNING — expires in {status['expires_in_days']} days. Refresh it.",
              file=sys.stderr)


if __name__ == "__main__":
    main()
