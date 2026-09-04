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
    last_position_by_clip: dict[str, int] = {}

    for requirement in contract.get("dialogue_requirements", []):
        requirement_id = requirement.get("id")
        clip_id = requirement.get("clip_id")
        segments = clips.get(clip_id)
        if not isinstance(segments, list):
            errors.append(f"{requirement_id}: ASR manifest is missing {clip_id}")
            continue
        clip_start = clip_starts.get(clip_id, 0.0)
        window_start = requirement.get("start_seconds")
        window_end = requirement.get("end_seconds")
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
        transcript = normalize("".join(str(item.get("text") or "") for item in selected))
        match_mode = requirement.get("match_mode")
        passed = False
        position = -1
        expected_display = ""
        if match_mode in {"exact", "contains"}:
            expected = normalize(str(requirement.get("expected_text") or ""))
            expected_display = str(requirement.get("expected_text") or "")
            position = transcript.find(expected)
            # ASR providers may merge two adjacent spoken lines into one segment.
            # "exact" means the expected characters must occur without substitution;
            # it does not require the provider's segment boundary to match our window.
            passed = bool(expected) and position >= 0
        elif match_mode == "terms":
            terms = [normalize(str(term)) for term in requirement.get("required_terms", [])]
            expected_display = ", ".join(str(term) for term in requirement.get("required_terms", []))
            positions = [transcript.find(term) for term in terms]
            passed = bool(terms) and all(position >= 0 for position in positions)
            position = min(positions) if positions and all(item >= 0 for item in positions) else -1
        if not passed:
            errors.append(
                f"{requirement_id}: {match_mode} dialogue requirement failed in {clip_id}; "
                f"expected [{expected_display}], ASR normalized text [{transcript}]"
            )
        elif position >= 0:
            previous = last_position_by_clip.get(str(clip_id), -1)
            if position < previous:
                errors.append(f"{requirement_id}: dialogue order regresses inside {clip_id}")
            last_position_by_clip[str(clip_id)] = position
        observed.append(
            {
                "id": requirement_id,
                "clip_id": clip_id,
                "match_mode": match_mode,
                "passed": passed,
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
