#!/usr/bin/env python3
"""Validate generated-video ASR against critical dialogue requirements in the contract."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


CONTRACT_FILE = "08_replica_contract.json"


def normalize(text: str) -> str:
    normalized = text.lower().translate(str.maketrans("零一二三四五六七八九两", "01234567892"))
    return re.sub(r"[^0-9a-z\u3400-\u9fff]+", "", normalized)


def estimated_match_time(segments: list[dict], start_position: int, length: int) -> tuple[float, float] | None:
    """Estimate a matched substring's time inside provider-merged ASR segments."""
    ranges = []
    offset = 0
    for segment in segments:
        text = normalize(str(segment.get("text") or ""))
        if not text:
            continue
        start = float(segment.get("start_seconds") or 0)
        end = float(segment.get("end_seconds") or start)
        ranges.append((offset, offset + len(text), start, end))
        offset += len(text)
    if start_position < 0 or length < 1 or start_position + length > offset:
        return None

    def at(position: int, prefer_previous: bool = False) -> float | None:
        for left, right, start, end in ranges:
            if left <= position < right or prefer_previous and position == right:
                ratio = (position - left) / max(1, right - left)
                return start + (end - start) * ratio
        return None

    start = at(start_position)
    end = at(start_position + length, prefer_previous=True)
    return (start, end) if start is not None and end is not None else None


def match_requirement(requirement: dict, segments: list[dict]) -> tuple[str, bool, int, int, str]:
    transcript = normalize("".join(str(item.get("text") or "") for item in segments))
    match_mode = requirement.get("match_mode")
    position = -1
    match_length = 0
    expected_display = ""
    if match_mode in {"exact", "contains"}:
        expected = normalize(str(requirement.get("expected_text") or ""))
        expected_display = str(requirement.get("expected_text") or "")
        position = transcript.find(expected)
        match_length = len(expected)
        return transcript, bool(expected) and position >= 0, position, match_length, expected_display
    if match_mode == "terms":
        terms = [normalize(str(term)) for term in requirement.get("required_terms", [])]
        expected_display = ", ".join(str(term) for term in requirement.get("required_terms", []))
        positions = [transcript.find(term) for term in terms]
        passed = bool(terms) and all(position >= 0 for position in positions)
        position = min(positions) if passed else -1
        match_length = max(pos + len(term) for pos, term in zip(positions, terms)) - position if passed else 0
        return transcript, passed, position, match_length, expected_display
    return transcript, False, position, match_length, expected_display


def validate_transcript(contract: dict, manifest: dict) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    clip_starts = {
        item.get("id"): float(item.get("start_seconds") or 0)
        for item in contract.get("clips", [])
        if isinstance(item, dict) and item.get("id")
    }
    clips = {
        item.get("clip_id"): item.get("segments", [])
        for item in manifest.get("clips", [])
        if isinstance(item, dict)
    }
    observed: list[dict] = []
    last_order_by_clip: dict[str, tuple[str, float]] = {}

    for requirement in contract.get("dialogue_requirements", []):
        requirement_id = requirement.get("id")
        clip_id = requirement.get("clip_id")
        segments = clips.get(clip_id)
        if not isinstance(segments, list):
            errors.append(f"{requirement_id}: ASR manifest is missing {clip_id}")
            continue
        clip_start = clip_starts.get(clip_id, 0.0)
        window_start = requirement.get("speech_start_seconds", requirement.get("start_seconds"))
        window_end = requirement.get("speech_end_seconds", requirement.get("end_seconds"))
        if window_start is not None:
            window_start = float(window_start) - clip_start
        if window_end is not None:
            window_end = float(window_end) - clip_start
        selected = []
        for segment in segments:
            if not isinstance(segment, dict):
                continue
            start = float(segment.get("start_seconds") or 0)
            end = float(segment.get("end_seconds") or start)
            if window_start is not None and end < window_start - 0.01:
                continue
            if window_end is not None and start > window_end + 0.01:
                continue
            selected.append(segment)
        match_mode = requirement.get("match_mode")
        transcript, passed, position, match_length, expected_display = match_requirement(requirement, selected)
        valid_segments = [item for item in segments if isinstance(item, dict)]
        if not passed and selected != valid_segments and window_start is not None and window_end is not None:
            fallback = match_requirement(requirement, valid_segments)
            if fallback[1]:
                selected = valid_segments
                transcript, passed, position, match_length, expected_display = fallback
        if not passed:
            errors.append(
                f"{requirement_id}: {match_mode} dialogue requirement failed in {clip_id}; "
                f"expected [{expected_display}], ASR normalized text [{transcript}]"
            )
        timing = estimated_match_time(selected, position, match_length) if passed else None
        timing_passed = True
        if timing and window_start is not None and window_end is not None:
            observed_center = sum(timing) / 2
            expected_center = (window_start + window_end) / 2
            tolerance = max(0.75, (window_end - window_start) / 2)
            timing_passed = abs(observed_center - expected_center) <= tolerance
            if not timing_passed:
                errors.append(
                    f"{requirement_id}: dialogue timing failed in {clip_id}; expected center "
                    f"{expected_center:.2f}s ±{tolerance:.2f}s, estimated matched speech "
                    f"{timing[0]:.2f}-{timing[1]:.2f}s"
                )
                passed = False
        if passed and position >= 0:
            order_mode = "time" if timing else "text"
            order_value = timing[0] if timing else float(position)
            previous = last_order_by_clip.get(str(clip_id))
            if previous and previous[0] == order_mode and order_value < previous[1] - 0.01:
                errors.append(f"{requirement_id}: dialogue order regresses inside {clip_id}")
            last_order_by_clip[str(clip_id)] = (order_mode, order_value)
        observed.append(
            {
                "id": requirement_id,
                "clip_id": clip_id,
                "match_mode": match_mode,
                "passed": passed,
                "timing_passed": timing_passed,
                "estimated_start_seconds": round(timing[0], 3) if timing else None,
                "estimated_end_seconds": round(timing[1], 3) if timing else None,
                "normalized_transcript": transcript,
            }
        )

    return {
        "status": "ok" if not errors else "failed",
        "requirements": observed,
        "errors": errors,
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate generated clip ASR against the replica contract.")
    parser.add_argument("project")
    parser.add_argument("manifest")
    parser.add_argument("--out")
    args = parser.parse_args()
    project = Path(args.project).expanduser().resolve()
    contract = json.loads((project / CONTRACT_FILE).read_text(encoding="utf-8"))
    manifest = json.loads(Path(args.manifest).expanduser().read_text(encoding="utf-8"))
    result = validate_transcript(contract, manifest)
    output = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).expanduser().write_text(output, encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
