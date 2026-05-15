"""
Assembles a static image + DMCA-free audio into a 15-second 1080x1080 MP4.

Track rotation: cycles through 4 tracks per game based on the day ordinal,
so each game uses a different track every 4 days.

Usage:
    python tools/create_reel.py --image .tmp/dead-mans-tide_123.png --slug dead-mans-tide
"""

import argparse
import subprocess
import sys
from datetime import date
from pathlib import Path

TMP_DIR = Path(__file__).parent.parent / ".tmp"
AUDIO_DIR = Path(__file__).parent.parent / "audio"


def create_reel(image_path: str | Path, slug: str) -> Path:
    image_path = Path(image_path)
    track_index = (date.today().toordinal() % 4) + 1
    audio_path = AUDIO_DIR / slug / f"{slug}_{track_index}.mp3"

    if not audio_path.exists():
        raise FileNotFoundError(
            f"Audio track not found: {audio_path}\n"
            f"Download 4 MP3 files from Pixabay and place them at:\n"
            f"  audio/{slug}/{slug}_1.mp3 through {slug}_4.mp3"
        )

    TMP_DIR.mkdir(exist_ok=True)
    output_path = TMP_DIR / f"{slug}_{date.today().toordinal()}.mp4"

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", str(image_path),
        "-i", str(audio_path),
        "-c:v", "libx264",
        "-c:a", "aac",
        "-b:a", "128k",
        "-t", "15",
        "-shortest",
        "-pix_fmt", "yuv420p",
        "-vf", "scale=1080:1080",
        str(output_path),
    ]

    print(f"[{slug}] Assembling reel with track {track_index}...", file=sys.stderr)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed:\n{result.stderr}")

    print(f"[{slug}] Reel ready: {output_path}", file=sys.stderr)
    return output_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True, help="Path to PNG image")
    parser.add_argument("--slug",  required=True, help="Game slug")
    args = parser.parse_args()

    output = create_reel(args.image, args.slug)
    print(output)


if __name__ == "__main__":
    main()
