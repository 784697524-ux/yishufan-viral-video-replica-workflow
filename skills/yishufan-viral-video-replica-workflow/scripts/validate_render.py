#!/usr/bin/env python3
"""Reject structurally under-aligned high-fidelity replica renders."""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import subprocess
from array import array
from pathlib import Path


def run(command: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=check, text=True, capture_output=True)


def probe(path: Path) -> dict:
    result = run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type,width,height,r_frame_rate,channels",
            "-of",
            "json",
            str(path),
        ]
    )
    data = json.loads(result.stdout)
    video = next((stream for stream in data.get("streams", []) if stream.get("codec_type") == "video"), {})
    audio = next((stream for stream in data.get("streams", []) if stream.get("codec_type") == "audio"), {})
    return {
        "duration_seconds": float(data.get("format", {}).get("duration") or 0),
        "width": video.get("width"),
        "height": video.get("height"),
        "frame_rate": video.get("r_frame_rate"),
        "has_audio": bool(audio),
        "channels": audio.get("channels"),
    }


def scene_change_count(path: Path, threshold: float = 0.18) -> int:
    result = run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "info",
            "-i",
            str(path),
            "-vf",
            f"select=gt(scene\\,{threshold}),showinfo",
            "-an",
            "-f",
            "null",
            "-",
        ],
        check=False,
    )
    return len(re.findall(r"Parsed_showinfo[^\n]*pts_time", result.stderr))


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def halfsecond_audio_stats(path: Path, sample_rate: int = 8000) -> dict | None:
    result = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            "-f",
            "s16le",
            "-",
        ],
        check=False,
        capture_output=True,
    )
    if result.returncode != 0 or not result.stdout:
        return None
    samples = array("h")
    samples.frombytes(result.stdout)
    window = sample_rate // 2
    values: list[float] = []
    for start in range(0, len(samples) - window + 1, window):
        chunk = samples[start : start + window]
        rms = math.sqrt(sum(value * value for value in chunk) / len(chunk)) / 32768
        values.append(20 * math.log10(max(rms, 1e-12)))
    if not values:
        return None
    return {
        "median_rms_db": statistics.median(values),
        "p10_rms_db": percentile(values, 0.10),
        "window_count": len(values),
        "quiet_window_count_below_minus_38_db": sum(value < -38 for value in values),
    }


def extract_halfsecond_frames(path: Path, out_dir: Path) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("frame_*.jpg"):
        stale.unlink()
    run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(path),
            "-vf",
            "fps=fps=2:start_time=0,scale=360:-2",
            "-q:v",
            "3",
            str(out_dir / "frame_%04d.jpg"),
        ]
    )
    return len(list(out_dir.glob("frame_*.jpg")))


def evaluate_metrics(
    reference: dict,
    candidate: dict,
    *,
    max_duration_delta: float = 0.5,
    min_scene_ratio: float = 0.7,
    max_rms_drop_db: float = 4.0,
    max_p10_drop_db: float = 8.0,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    duration_delta = abs(candidate["duration_seconds"] - reference["duration_seconds"])
    if duration_delta > max_duration_delta:
        errors.append(
            f"duration differs by {duration_delta:.3f}s; allowed maximum is {max_duration_delta:.3f}s"
        )
    ref_width, ref_height = reference.get("width"), reference.get("height")
    cand_width, cand_height = candidate.get("width"), candidate.get("height")
    if all(isinstance(value, int) and value > 0 for value in (ref_width, ref_height, cand_width, cand_height)):
        ref_ratio = ref_width / ref_height
        cand_ratio = cand_width / cand_height
        if abs(ref_ratio - cand_ratio) > 0.01:
            errors.append("candidate aspect ratio does not match reference")
        if cand_width < ref_width or cand_height < ref_height:
            warnings.append("candidate resolution is lower than reference")
    ref_scenes = reference.get("scene_change_count", 0)
    cand_scenes = candidate.get("scene_change_count", 0)
    if ref_scenes:
        ratio = cand_scenes / ref_scenes
        if ratio < min_scene_ratio:
            errors.append(
                f"scene-change density ratio is {ratio:.3f}; required minimum is {min_scene_ratio:.3f}"
            )
    ref_rms = reference.get("median_halfsecond_rms_db")
    cand_rms = candidate.get("median_halfsecond_rms_db")
    if isinstance(ref_rms, (int, float)) and isinstance(cand_rms, (int, float)):
        drop = ref_rms - cand_rms
        if drop > max_rms_drop_db:
            errors.append(f"candidate median audio energy is {drop:.2f}dB below reference")
    elif reference.get("has_audio"):
        errors.append("candidate audio could not be measured")
    ref_p10 = reference.get("p10_halfsecond_rms_db")
    cand_p10 = candidate.get("p10_halfsecond_rms_db")
    if isinstance(ref_p10, (int, float)) and isinstance(cand_p10, (int, float)):
        drop = ref_p10 - cand_p10
        if drop > max_p10_drop_db:
            errors.append(
                f"candidate low-tail audio energy is {drop:.2f}dB below reference; "
                "music/effect continuity is likely missing"
            )
    return errors, warnings


def write_markdown(path: Path, result: dict) -> None:
    lines = [
        "# 成片结构验收",
        "",
        f"- 状态：**{result['status']}**",
        f"- 原片：`{result['reference_path']}`",
        f"- 成片：`{result['candidate_path']}`",
        f"- 时长差：{result['duration_delta_seconds']:.3f}s",
        f"- 显著变化密度比：{result['scene_change_ratio']:.3f}",
        f"- 半秒音频中位能量差：{result['audio_rms_drop_db']}",
        f"- 半秒音频低分位能量差：{result['audio_p10_drop_db']}",
        "",
        "## Errors",
        "",
        *([f"- {item}" for item in result["errors"]] or ["- 无"]),
        "",
        "## Warnings",
        "",
        *([f"- {item}" for item in result["warnings"]] or ["- 无"]),
        "",
        "此脚本只验收时长、画幅、镜头变化密度和音频能量/动态连续性。表情递进、对白逐字、道具连续和反转因果仍需查看0.5秒帧并完成导演复盘。",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a rendered high-fidelity video against its reference.")
    parser.add_argument("reference")
    parser.add_argument("candidate")
    parser.add_argument("--out", required=True)
    parser.add_argument("--max-duration-delta", type=float, default=0.5)
    parser.add_argument("--min-scene-ratio", type=float, default=0.7)
    parser.add_argument("--max-rms-drop-db", type=float, default=4.0)
    parser.add_argument("--max-p10-drop-db", type=float, default=8.0)
    args = parser.parse_args()

    reference_path = Path(args.reference).expanduser().resolve()
    candidate_path = Path(args.candidate).expanduser().resolve()
    out_dir = Path(args.out).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    reference = probe(reference_path)
    candidate = probe(candidate_path)
    reference["scene_change_count"] = scene_change_count(reference_path)
    candidate["scene_change_count"] = scene_change_count(candidate_path)
    reference_audio = halfsecond_audio_stats(reference_path)
    candidate_audio = halfsecond_audio_stats(candidate_path)
    reference["audio_stats"] = reference_audio
    candidate["audio_stats"] = candidate_audio
    reference["median_halfsecond_rms_db"] = reference_audio["median_rms_db"] if reference_audio else None
    candidate["median_halfsecond_rms_db"] = candidate_audio["median_rms_db"] if candidate_audio else None
    reference["p10_halfsecond_rms_db"] = reference_audio["p10_rms_db"] if reference_audio else None
    candidate["p10_halfsecond_rms_db"] = candidate_audio["p10_rms_db"] if candidate_audio else None
    reference["halfsecond_frame_count"] = extract_halfsecond_frames(reference_path, out_dir / "reference_frames")
    candidate["halfsecond_frame_count"] = extract_halfsecond_frames(candidate_path, out_dir / "candidate_frames")
    errors, warnings = evaluate_metrics(
        reference,
        candidate,
        max_duration_delta=args.max_duration_delta,
        min_scene_ratio=args.min_scene_ratio,
        max_rms_drop_db=args.max_rms_drop_db,
        max_p10_drop_db=args.max_p10_drop_db,
    )
    result = {
        "status": "ok" if not errors else "failed",
        "reference_path": str(reference_path),
        "candidate_path": str(candidate_path),
        "reference": reference,
        "candidate": candidate,
        "duration_delta_seconds": abs(candidate["duration_seconds"] - reference["duration_seconds"]),
        "scene_change_ratio": (
            candidate["scene_change_count"] / reference["scene_change_count"]
            if reference["scene_change_count"]
            else 1.0
        ),
        "audio_rms_drop_db": (
            round(reference["median_halfsecond_rms_db"] - candidate["median_halfsecond_rms_db"], 3)
            if reference["median_halfsecond_rms_db"] is not None
            and candidate["median_halfsecond_rms_db"] is not None
            else None
        ),
        "audio_p10_drop_db": (
            round(reference["p10_halfsecond_rms_db"] - candidate["p10_halfsecond_rms_db"], 3)
            if reference["p10_halfsecond_rms_db"] is not None
            and candidate["p10_halfsecond_rms_db"] is not None
            else None
        ),
        "errors": errors,
        "warnings": warnings,
    }
    (out_dir / "render-validation.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_markdown(out_dir / "render-validation.md", result)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
