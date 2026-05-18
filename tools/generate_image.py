"""
Generates an image from a prompt using kie.ai's gpt-image-2 model.

Usage:
    python tools/generate_image.py --prompt "your prompt here" --game <slug>
    python tools/generate_image.py --prompt "your prompt" --game game-one --output .tmp/out.png
"""

import argparse
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

TMP_DIR = Path(__file__).parent.parent / ".tmp"
TMP_DIR.mkdir(exist_ok=True)

KIE_API_BASE  = "https://api.kie.ai/api/v1"
POLL_INTERVAL = 5    # seconds between status checks
POLL_TIMEOUT  = 120  # max seconds to wait before giving up


def generate_image(prompt: str, game_slug: str, output_path: Path = None) -> Path:
    api_key = os.getenv("KIE_API_KEY")
    if not api_key:
        raise RuntimeError("KIE_API_KEY environment variable is not set")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    if output_path is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = TMP_DIR / f"{game_slug}_{timestamp}.png"

    # Submit the generation task
    resp = requests.post(
        f"{KIE_API_BASE}/jobs/createTask",
        headers=headers,
        json={
            "model": "gpt-image-2-text-to-image",
            "input": {
                "prompt": prompt,
                "aspect_ratio": "1:1",
            },
        },
        timeout=30,
    )
    resp.raise_for_status()
    resp_json = resp.json()

    task_id = (resp_json.get("data") or {}).get("taskId")
    if not task_id:
        raise RuntimeError(f"Kie.ai did not return a taskId. Response: {resp_json}")

    print(f"Image task submitted: {task_id}", file=sys.stderr)

    # Poll until done or timed out
    deadline = time.time() + POLL_TIMEOUT
    while time.time() < deadline:
        time.sleep(POLL_INTERVAL)

        poll = requests.get(
            f"{KIE_API_BASE}/jobs/recordInfo",
            headers=headers,
            params={"taskId": task_id},
            timeout=30,
        )
        poll.raise_for_status()
        poll_json = poll.json()
        data      = poll_json.get("data") or {}
        status    = str(data.get("state", data.get("status", ""))).lower()

        print(f"Image status: {status}", file=sys.stderr)

        if status in ("success", "completed", "done", "finish"):
            outputs = data.get("output") or []
            if not outputs:
                raise RuntimeError(f"Kie.ai returned success but no output. Response: {poll_json}")
            image_url = outputs[0].get("url") or outputs[0].get("imageUrl")
            if not image_url:
                raise RuntimeError(f"Could not find image URL in output: {outputs[0]}")

            img_resp = requests.get(image_url, timeout=60)
            img_resp.raise_for_status()
            with open(output_path, "wb") as f:
                f.write(img_resp.content)

            print(f"Image saved: {output_path}", file=sys.stderr)
            return output_path

        if status in ("failed", "error", "fail"):
            raise RuntimeError(f"Kie.ai image generation failed. Response: {poll_json}")

    raise RuntimeError(f"Image generation timed out after {POLL_TIMEOUT}s (task: {task_id})")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", required=True, help="Image generation prompt")
    parser.add_argument("--game",   required=True, help="Game slug (used for filename)")
    parser.add_argument("--output", help="Output file path (default: .tmp/<game>_<timestamp>.png)")
    args = parser.parse_args()

    output = Path(args.output) if args.output else None
    result_path = generate_image(args.prompt, args.game, output)
    print(str(result_path))


if __name__ == "__main__":
    main()
