"""
Generates an image from a prompt using OpenAI's gpt-image-1 model.

Usage:
    python tools/generate_image.py --prompt "your prompt here" --game <slug>
    python tools/generate_image.py --prompt "your prompt" --game game-one --output .tmp/out.png
"""

import argparse
import base64
import os
import sys
from datetime import datetime
from pathlib import Path

import openai
from dotenv import load_dotenv

load_dotenv()

TMP_DIR = Path(__file__).parent.parent / ".tmp"
TMP_DIR.mkdir(exist_ok=True)

def generate_image(prompt: str, game_slug: str, output_path: Path = None) -> Path:
    client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    if output_path is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = TMP_DIR / f"{game_slug}_{timestamp}.png"

    response = client.images.generate(
        model="gpt-image-2-2026-04-21",
        prompt=prompt,
        size="1024x1024",
        quality="high",
        n=1,
    )

    image_data = base64.b64decode(response.data[0].b64_json)
    with open(output_path, "wb") as f:
        f.write(image_data)

    print(f"Image saved: {output_path}", file=sys.stderr)
    return output_path

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", required=True, help="Image generation prompt")
    parser.add_argument("--game", required=True, help="Game slug (used for filename)")
    parser.add_argument("--output", help="Output file path (default: .tmp/<game>_<timestamp>.png)")
    args = parser.parse_args()

    output = Path(args.output) if args.output else None
    result_path = generate_image(args.prompt, args.game, output)
    print(str(result_path))

if __name__ == "__main__":
    main()
