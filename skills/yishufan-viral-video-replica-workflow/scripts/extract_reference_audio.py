#!/usr/bin/env python3
"""Extract a time-locked reference audio segment for a replica prompt."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


def parse_time(value: str) -> float:
    parts = value.strip().split(":")
    try:
        numbers = [float(part) for part in parts]
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid time: {value}") from exc
    if len(numbers) == 1:
        seconds = numbers[0]
    elif len(numbers) == 2:
        seconds = numbers[0] * 60 + numbers[1]
    elif len(numbers) == 3:
        seconds = numbers[0] * 3600 + numbers[1] * 60 + numbers[2]
    else:
        raise argparse.ArgumentTypeError(f"invalid time: {value}")
    if seconds < 0:
        raise argparse.ArgumentTypeError("time cannot be negative")
    return seconds


def media_duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    return float(result.stdout.strip())


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_ffmpeg_command(source: Path, output: Path, start: float, duration: float) -> list[str]:
    return [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source),
        "-ss",
        f"{start:.3f}",
        "-t",
        f"{duration:.3f}",
        "-vn",
        "-map",
        "0:a:0",
        "-ac",
        "2",
        "-ar",
        "48000",
        "-c:a",
        "libmp3lame",
        "-b:a",
        "320k",
        str(output),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract original mixed audio for a replica clip.")
    parser.add_argument("source", help="Local reference video")
    parser.add_argument("--start", required=True, type=parse_time)
    parser.add_argument("--end", required=True, type=parse_time)
    parser.add_argument("--output", required=True, help="Output .mp3 path")
    parser.add_argument("--manifest", help="Optional metadata JSON path")
    args = parser.parse_args()

    source = Path(args.source).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()
    if not source.is_file():
        parser.error(f"source not found: {source}")
    if output.suffix.lower() != ".mp3":
        parser.error("output must use .mp3")
    if args.end <= args.start:
        parser.error("--end must be greater than --start")
    total = media_duration(source)
    if args.end > total + 0.01:
        parser.error(f"--end {args.end:.3f}s exceeds source duration {total:.3f}s")

    output.parent.mkdir(parents=True, exist_ok=True)
    duration = args.end - args.start
    subprocess.run(build_ffmpeg_command(source, output, args.start, duration), check=True)
    actual_duration = media_duration(output)
    metadata = {
        "source": str(source),
        "source_sha256": sha256(source),
        "start_seconds": round(args.start, 3),
        "end_seconds": round(args.end, 3),
        "requested_duration_seconds": round(duration, 3),
        "actual_duration_seconds": round(actual_duration, 3),
        "output": str(output),
        "output_sha256": sha256(output),
        "codec": "mp3",
        "sample_rate": 48000,
        "channels": 2,
        "bitrate": "320k",
        "note": "single mixed source; may include music, dialogue and sound effects",
    }
    if args.manifest:
        manifest = Path(args.manifest).expanduser().resolve()
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(metadata, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
