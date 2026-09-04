#!/usr/bin/env python3
"""Validate AI-table clip outputs against the replica contract before stitching."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


CONTRACT_FILE = "08_replica_contract.json"


def probe(path: Path) -> dict:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type,width,height",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    data = json.loads(result.stdout)
    video = next((item for item in data.get("streams", []) if item.get("codec_type") == "video"), {})
    return {
        "duration_seconds": float(data.get("format", {}).get("duration") or 0),
        "width": video.get("width"),
        "height": video.get("height"),
        "has_audio": any(item.get("codec_type") == "audio" for item in data.get("streams", [])),
    }


def evaluate_delivery(contract: dict, outputs: list[dict], max_duration_delta: float = 0.5) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    clips = contract.get("clips", [])
    expected_ids = [clip.get("id") for clip in clips if isinstance(clip, dict)]
    actual_ids = [item.get("clip_id") for item in outputs if isinstance(item, dict)]
    if actual_ids != expected_ids:
        errors.append(f"output order/identity {actual_ids} does not match contract clip order {expected_ids}")
    if len(actual_ids) != len(set(actual_ids)):
        errors.append("delivery manifest contains duplicate clip_id values")

    expected_by_id = {clip["id"]: clip for clip in clips if isinstance(clip, dict) and clip.get("id")}
    for item in outputs:
        clip_id = item.get("clip_id")
        expected = expected_by_id.get(clip_id)
        if not expected:
            continue
        expected_duration = float(expected["end_seconds"]) - float(expected["start_seconds"])
        actual_duration = float(item.get("duration_seconds") or 0)
        delta = abs(actual_duration - expected_duration)
        if delta > max_duration_delta:
            errors.append(
                f"{clip_id} duration differs by {delta:.3f}s; expected {expected_duration:.3f}s, got {actual_duration:.3f}s"
            )
        width = item.get("width")
        height = item.get("height")
        if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
            errors.append(f"{clip_id} has no readable video dimensions")
        else:
            if abs(width / height - 9 / 16) > 0.015:
                errors.append(f"{clip_id} is {width}x{height}, not 9:16")
            if width < 720 or height < 1280:
                warnings.append(f"{clip_id} resolution {width}x{height} is below 720x1280")
        if item.get("has_audio") is not True:
            errors.append(f"{clip_id} has no audio stream")

    return {
        "status": "ok" if not errors else "failed",
        "expected_clip_ids": expected_ids,
        "actual_clip_ids": actual_ids,
        "outputs": outputs,
        "errors": errors,
        "warnings": warnings,
    }


def resolve_outputs(project: Path, manifest: dict) -> list[dict]:
    outputs: list[dict] = []
    for item in manifest.get("outputs", []):
        resolved = (project / item["file"]).resolve() if not Path(item["file"]).is_absolute() else Path(item["file"])
        if not resolved.is_file():
            outputs.append({**item, "duration_seconds": 0, "width": None, "height": None, "has_audio": False})
            continue
        try:
            outputs.append({**item, "file": str(resolved), **probe(resolved)})
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
            outputs.append(
                {
                    **item,
                    "file": str(resolved),
                    "duration_seconds": 0,
                    "width": None,
                    "height": None,
                    "has_audio": False,
                    "probe_error": str(exc),
                }
            )
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate generated clip files before stitching or publishing.")
    parser.add_argument("project")
    parser.add_argument("manifest", help='JSON file: {"outputs":[{"clip_id":"clip01","file":"...mp4"}]}')
    parser.add_argument("--out")
    parser.add_argument("--max-duration-delta", type=float, default=0.5)
    args = parser.parse_args()

    project = Path(args.project).expanduser().resolve()
    contract = json.loads((project / CONTRACT_FILE).read_text(encoding="utf-8"))
    manifest = json.loads(Path(args.manifest).expanduser().read_text(encoding="utf-8"))
    outputs = resolve_outputs(project, manifest)
    result = evaluate_delivery(contract, outputs, args.max_duration_delta)
    if args.out:
        Path(args.out).expanduser().write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
