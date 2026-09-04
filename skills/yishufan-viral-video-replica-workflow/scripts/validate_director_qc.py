#!/usr/bin/env python3
"""Validate Watch-backed director evidence for story, performance, props, and final memory point."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


CONTRACT_FILE = "08_replica_contract.json"
SCORE_MAX = {
    "causality": 25,
    "performance": 20,
    "reference_mechanism": 15,
    "product_integration": 15,
    "generatability": 10,
    "camera_sound": 10,
    "fact_accuracy": 5,
}


def evidence_path(project: Path, value: object, errors: list[str], label: str) -> Path | None:
    if not isinstance(value, str) or not value:
        errors.append(f"{label}.evidence_file is required")
        return None
    path = (project / value).resolve() if not Path(value).is_absolute() else Path(value).resolve()
    try:
        path.relative_to(project.resolve())
    except ValueError:
        errors.append(f"{label}.evidence_file must be inside the project")
        return None
    if not path.is_file():
        errors.append(f"{label}.evidence_file does not exist: {value}")
        return None
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=codec_type,width,height",
                "-of",
                "json",
                str(path),
            ],
            check=True,
            text=True,
            capture_output=True,
        )
        streams = json.loads(result.stdout).get("streams", [])
        image = next((item for item in streams if item.get("codec_type") == "video"), {})
        if not image.get("width") or not image.get("height"):
            raise ValueError("image dimensions are missing")
    except (OSError, ValueError, subprocess.SubprocessError, json.JSONDecodeError):
        errors.append(f"{label}.evidence_file is not a readable image: {value}")
        return None
    return path


def validate_director_qc(project: Path, contract: dict, manifest: dict) -> dict:
    project = project.expanduser().resolve()
    errors: list[str] = []
    warnings: list[str] = []
    clips = {item.get("id"): item for item in contract.get("clips", []) if isinstance(item, dict)}

    timeline_reviews = manifest.get("timeline_reviews")
    review_by_clip = {
        item.get("clip_id"): item for item in timeline_reviews or [] if isinstance(item, dict)
    }
    if not isinstance(timeline_reviews, list):
        errors.append("timeline_reviews must be an array")
    for clip_id, clip in clips.items():
        review = review_by_clip.get(clip_id)
        if not review:
            errors.append(f"timeline review missing for {clip_id}")
            continue
        if review.get("fixed_timeline_manual_reviewed") is not True:
            errors.append(f"{clip_id} fixed timeline was not manually reviewed")
        frame_count = review.get("reviewed_frame_count")
        if not isinstance(frame_count, int) or frame_count < 1:
            errors.append(f"{clip_id} reviewed_frame_count must be positive")
        last_timestamp = review.get("reviewed_last_timestamp_seconds")
        duration = float(clip.get("end_seconds") or 0) - float(clip.get("start_seconds") or 0)
        if not isinstance(last_timestamp, (int, float)) or float(last_timestamp) < duration - 0.6:
            errors.append(f"{clip_id} fixed timeline review stops before the end of the generated clip")

    expected_steps = contract.get("narrative_qc", {}).get("story_chain", [])
    expected_step_ids = [item.get("id") for item in expected_steps if isinstance(item, dict)]
    observed_steps = manifest.get("story_steps")
    observed_step_ids = [item.get("id") for item in observed_steps or [] if isinstance(item, dict)]
    if observed_step_ids != expected_step_ids:
        errors.append(f"story step evidence {observed_step_ids} does not match contract order {expected_step_ids}")
    previous_timestamp = -1.0
    for index, item in enumerate(observed_steps or []):
        label = f"story_steps[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{label} must be an object")
            continue
        timestamp = item.get("timestamp_seconds")
        if not isinstance(timestamp, (int, float)) or float(timestamp) < previous_timestamp:
            errors.append(f"{label}.timestamp_seconds must be ordered")
        else:
            previous_timestamp = float(timestamp)
        if item.get("observed") is not True:
            errors.append(f"{label} was not observed in the generated video")
        if not isinstance(item.get("observed_action"), str) or not item.get("observed_action", "").strip():
            errors.append(f"{label}.observed_action is required")
        evidence_path(project, item.get("evidence_file"), errors, label)

    expected_arcs = {
        item.get("id"): item
        for item in contract.get("director_requirements", {}).get("performance_arcs", [])
        if isinstance(item, dict)
    }
    observed_arcs = {
        item.get("id"): item for item in manifest.get("performance_arcs", []) if isinstance(item, dict)
    }
    if set(observed_arcs) != set(expected_arcs):
        errors.append("performance arc evidence does not match director_requirements")
    for arc_id, expected_arc in expected_arcs.items():
        observed_arc = observed_arcs.get(arc_id, {})
        expected_states = [item.get("id") for item in expected_arc.get("states", [])]
        states = observed_arc.get("states", [])
        observed_state_ids = [item.get("id") for item in states if isinstance(item, dict)]
        if observed_state_ids != expected_states:
            errors.append(f"performance arc {arc_id} states {observed_state_ids} do not match {expected_states}")
        previous_timestamp = -1.0
        for index, state in enumerate(states):
            label = f"performance_arcs.{arc_id}.states[{index}]"
            if not isinstance(state, dict):
                errors.append(f"{label} must be an object")
                continue
            timestamp = state.get("timestamp_seconds")
            if not isinstance(timestamp, (int, float)) or float(timestamp) <= previous_timestamp:
                errors.append(f"{label}.timestamp_seconds must strictly increase")
            else:
                previous_timestamp = float(timestamp)
            if item_value_false(state.get("observed")):
                errors.append(f"{label} was not observed")
            evidence_path(project, state.get("evidence_file"), errors, label)

    expected_props = {
        item.get("id"): item for item in contract.get("prop_continuity_requirements", []) if isinstance(item, dict)
    }
    observed_prop_events = manifest.get("prop_events", [])
    for prop_id, requirement in expected_props.items():
        expected_event_ids = requirement.get("event_ids", [])
        events = [item for item in observed_prop_events if isinstance(item, dict) and item.get("prop_id") == prop_id]
        event_ids = [item.get("event_id") for item in events]
        if event_ids != expected_event_ids:
            errors.append(f"prop {prop_id} events {event_ids} do not match {expected_event_ids}")
        previous_timestamp = -1.0
        for index, event in enumerate(events):
            label = f"prop_events.{prop_id}[{index}]"
            timestamp = event.get("timestamp_seconds")
            if not isinstance(timestamp, (int, float)) or float(timestamp) <= previous_timestamp:
                errors.append(f"{label}.timestamp_seconds must strictly increase")
            else:
                previous_timestamp = float(timestamp)
            if item_value_false(event.get("observed")):
                errors.append(f"{label} was not observed")
            evidence_path(project, event.get("evidence_file"), errors, label)

    expected_pairs = [
        (item.get("from_clip_id"), item.get("to_clip_id"))
        for item in contract.get("continuity", [])
        if isinstance(item, dict) and item.get("from_clip_id") and item.get("to_clip_id")
    ]
    checks = manifest.get("continuity_checks", [])
    observed_pairs = [
        (item.get("from_clip_id"), item.get("to_clip_id")) for item in checks if isinstance(item, dict)
    ]
    if observed_pairs != expected_pairs:
        errors.append(f"continuity checks {observed_pairs} do not match contract {expected_pairs}")
    for index, check in enumerate(checks):
        label = f"continuity_checks[{index}]"
        if check.get("passed") is not True:
            errors.append(f"{label} failed")
        evidence_path(project, check.get("evidence_file"), errors, label)

    hard_vetoes = manifest.get("hard_vetoes")
    if not isinstance(hard_vetoes, list):
        errors.append("hard_vetoes must be an array")
    elif hard_vetoes:
        errors.append(f"director hard vetoes are present: {', '.join(str(item) for item in hard_vetoes)}")

    scores = manifest.get("scores")
    total_score = 0
    if not isinstance(scores, dict):
        errors.append("scores must be an object")
    else:
        for name, maximum in SCORE_MAX.items():
            value = scores.get(name)
            if not isinstance(value, (int, float)) or value < 0 or value > maximum:
                errors.append(f"scores.{name} must be between 0 and {maximum}")
            else:
                total_score += value
        if total_score < 85:
            errors.append(f"director score is {total_score}/100; minimum is 85")

    final_step_id = contract.get("director_requirements", {}).get("final_memory_step_id")
    if final_step_id not in observed_step_ids:
        errors.append("final memory story step is not evidenced")

    return {
        "status": "ok" if not errors else "failed",
        "director_score": total_score,
        "errors": errors,
        "warnings": warnings,
    }


def item_value_false(value: object) -> bool:
    return value is not True


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Watch-backed director QC evidence.")
    parser.add_argument("project")
    parser.add_argument("manifest")
    parser.add_argument("--out")
    args = parser.parse_args()
    project = Path(args.project).expanduser().resolve()
    contract = json.loads((project / CONTRACT_FILE).read_text(encoding="utf-8"))
    manifest = json.loads(Path(args.manifest).expanduser().read_text(encoding="utf-8"))
    result = validate_director_qc(project, contract, manifest)
    output = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).expanduser().write_text(output, encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
