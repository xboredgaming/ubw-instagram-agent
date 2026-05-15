"""
Uploads an MP4 video to Cloudinary and returns a public HTTPS URL.

Requires env vars: CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET
Sign up for a free account at cloudinary.com — free tier covers ~25 GB/month.

Usage:
    python tools/upload_video.py --video .tmp/dead-mans-tide_123.mp4
"""

import argparse
import hashlib
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()


def upload_video(video_path: str | Path) -> str:
    cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME")
    api_key    = os.getenv("CLOUDINARY_API_KEY")
    api_secret = os.getenv("CLOUDINARY_API_SECRET")

    if not cloud_name or not api_key or not api_secret:
        raise RuntimeError(
            "CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, and CLOUDINARY_API_SECRET must be set"
        )

    ts = int(time.time())
    signature = hashlib.sha1(f"timestamp={ts}{api_secret}".encode()).hexdigest()

    url = f"https://api.cloudinary.com/v1_1/{cloud_name}/video/upload"

    print(f"Uploading video to Cloudinary: {Path(video_path).name}", file=sys.stderr)
    with open(video_path, "rb") as f:
        resp = requests.post(
            url,
            data={"api_key": api_key, "timestamp": ts, "signature": signature},
            files={"file": f},
            timeout=120,
        )

    if not resp.ok:
        raise RuntimeError(f"Cloudinary upload error {resp.status_code}: {resp.text}")

    secure_url = resp.json().get("secure_url")
    if not secure_url:
        raise RuntimeError(f"Cloudinary upload returned no URL: {resp.json()}")

    print(f"Video uploaded: {secure_url}", file=sys.stderr)
    return secure_url


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True, help="Path to MP4 file")
    args = parser.parse_args()

    url = upload_video(args.video)
    print(url)


if __name__ == "__main__":
    main()
