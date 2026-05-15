"""
Posts an image to Instagram via the Meta Graph API.

Flow: create media container → publish container

Usage:
    python tools/post_instagram.py --image-url <url> --caption "text" --hashtags "#tag1 #tag2"
    python tools/post_instagram.py --image-url <url> --caption "text" --dry-run
"""

import argparse
import os
import sys
import time

import requests
from dotenv import load_dotenv

load_dotenv()

GRAPH_API_BASE = "https://graph.facebook.com/v21.0"


def post_to_instagram(image_url: str, caption: str, hashtags: list[str], dry_run: bool = False) -> str:
    access_token = os.getenv("INSTAGRAM_ACCESS_TOKEN")
    account_id = os.getenv("INSTAGRAM_ACCOUNT_ID")

    if not access_token or not account_id:
        raise RuntimeError("INSTAGRAM_ACCESS_TOKEN and INSTAGRAM_ACCOUNT_ID must be set in .env")

    full_caption = f"{caption}\n\n{' '.join(hashtags)}"

    if dry_run:
        print("[DRY RUN] Would post to Instagram:", file=sys.stderr)
        print(f"  Account ID: {account_id}", file=sys.stderr)
        print(f"  Image URL: {image_url}", file=sys.stderr)
        print(f"  Caption preview: {full_caption[:100]}...", file=sys.stderr)
        return "dry-run-no-id"

    # Step 1: Create media container
    container_url = f"{GRAPH_API_BASE}/{account_id}/media"
    container_resp = requests.post(
        container_url,
        data={
            "image_url": image_url,
            "caption": full_caption,
            "access_token": access_token,
        },
        timeout=30,
    )
    if not container_resp.ok:
        raise RuntimeError(f"Instagram media container error {container_resp.status_code}: {container_resp.text}")
    creation_id = container_resp.json().get("id")
    if not creation_id:
        raise RuntimeError(f"Failed to create media container: {container_resp.json()}")

    print(f"Container created: {creation_id}", file=sys.stderr)

    # Brief pause — Meta recommends waiting before publishing
    time.sleep(5)

    # Step 2: Publish the container
    publish_url = f"{GRAPH_API_BASE}/{account_id}/media_publish"
    publish_resp = requests.post(
        publish_url,
        data={
            "creation_id": creation_id,
            "access_token": access_token,
        },
        timeout=30,
    )
    publish_resp.raise_for_status()
    post_id = publish_resp.json().get("id")
    if not post_id:
        raise RuntimeError(f"Failed to publish media: {publish_resp.json()}")

    print(f"Published post ID: {post_id}", file=sys.stderr)
    return post_id


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image-url", required=True, help="Publicly accessible image URL")
    parser.add_argument("--caption", required=True, help="Post caption (no hashtags)")
    parser.add_argument("--hashtags", default="", help="Space-separated hashtag string")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be posted without posting")
    args = parser.parse_args()

    hashtags = args.hashtags.split() if args.hashtags else []
    post_id = post_to_instagram(args.image_url, args.caption, hashtags, dry_run=args.dry_run)
    print(post_id)


if __name__ == "__main__":
    main()
