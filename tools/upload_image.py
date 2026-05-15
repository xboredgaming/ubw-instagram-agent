"""
Uploads a local image to imgbb and returns the public URL.

Usage:
    python tools/upload_image.py --file .tmp/game-one_20240101_110000.png
"""

import argparse
import base64
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

IMGBB_API_URL = "https://api.imgbb.com/1/upload"
IMGBB_EXPIRATION_SECONDS = 86400  # 24 hours — images are temporary; Instagram caches them at post time

def upload_image(file_path: Path) -> str:
    api_key = os.getenv("IMGBB_API_KEY")
    if not api_key:
        raise RuntimeError("IMGBB_API_KEY not set in .env")

    with open(file_path, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode("utf-8")

    response = requests.post(
        IMGBB_API_URL,
        data={
            "key": api_key,
            "image": image_b64,
            "expiration": IMGBB_EXPIRATION_SECONDS,
        },
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()

    if not data.get("success"):
        raise RuntimeError(f"imgbb upload failed: {data}")

    url = data["data"]["url"]
    print(f"Uploaded: {url}", file=sys.stderr)
    return url

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True, help="Path to the image file to upload")
    args = parser.parse_args()

    url = upload_image(Path(args.file))
    print(url)

if __name__ == "__main__":
    main()
