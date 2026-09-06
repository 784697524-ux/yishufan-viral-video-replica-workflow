#!/usr/bin/env python3
"""Validate the compact v7.3 story, shot, and continuity plan."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


PLAN_FILE = "03_director_plan.json"
STATE_KEYS = {
    "protagonist_id",
    "left_hand",
    "right_hand",
    "prop_holders",
    "position",
    "gaze_target",
    "action_phase",
    "crowd_signature",
}
EVENT_PHASES = {"setup": 0, "progress": 1, "payoff": 2}
SENSITIVE_TERMS = ("不用付钱", "免费", "一元", "1元", "零元", "0元")
CONTROLLED_FACT_SOURCES = {"post_overlay", "controlled_voiceover", "source_fact_card"}


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _state(value: object, label: str, errors: list[str]) -> dict:
    if not isinstance(value, dict):
        errors.append(f"director_core: {label} must be an object")
        return {}
    missing = sorted(STATE_KEYS - set(value))
    if missing:
        errors.append(f"director_core: {label} missing state keys: {', '.join(missing)}")
    for key in STATE_KEYS & set(value):
        if not _text(value[key]):
            errors.append(f"director_core: {label}.{key} must be concrete text")
    return value


def validate(project: Path, contract: dict) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    project = project.expanduser().resolve()
    relative = contract.get("director_plan_file", PLAN_FILE)
    if not _text(relative):
        return {"status": "failed", "errors": ["director_core: director_plan_file is required"], "warnings": []}
    plan_path = (project / relative).resolve()
    try:
        plan_path.relative_to(project)
    except ValueError:
        return {"status": "failed", "errors": ["director_core: director_plan_file must stay inside project"], "warnings": []}
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": "failed", "errors": [f"director_core: cannot read {relative}: {exc}"], "warnings": []}
    if not isinstance(plan, dict):
        return {"status": "failed", "errors": ["director_core: plan root must be an object"], "warnings": []}

    if str(plan.get("version")) != "7.3":
        errors.append("director_core: version must be 7.3")
    for field in ("story_question", "scene_promise"):
        if not _text(plan.get(field)):
            errors.append(f"director_core: {field} is required")

    cues = plan.get("commercial_truth_cues", [])
    if not isinstance(cues, list):
        errors.append("director_core: commercial_truth_cues must be a list")
        cues = []
    valid_cues: list[dict] = []
    for index, cue in enumerate(cues):
        if not isinstance(cue, dict):
            errors.append(f"director_core: commercial_truth_cues[{index}] must be an object")
            continue
        if cue.get("source") not in CONTROLLED_FACT_SOURCES:
            errors.append(f"director_core: commercial truth cue {index} must use controlled output")
        if not _text(cue.get("text")):
            errors.append(f"director_core: commercial truth cue {index} needs exact text")
        if not isinstance(cue.get("start_seconds"), (int, float)) or not isinstance(cue.get("end_seconds"), (int, float)):
            errors.append(f"director_core: commercial truth cue {index} needs numeric timing")
        valid_cues.append(cue)

    clips = plan.get("clips")
    if not isinstance(clips, list) or not clips:
        return {"status": "failed", "errors": errors + ["director_core: clips are required"], "warnings": warnings}
    contract_clips = {item.get("id"): item for item in contract.get("clips", []) if isinstance(item, dict)}
    seen_beats: dict[str, dict] = {}
    ordered_beats: list[dict] = []
    event_history: dict[str, list[tuple[str, str]]] = {}
    previous_state: dict | None = None
    previous_label = ""

    for clip_index, clip in enumerate(clips):
        if not isinstance(clip, dict):
            errors.append(f"director_core: clip {clip_index} must be an object")
            continue
        clip_id = clip.get("clip_id")
        beats = clip.get("beats")
        if clip_id not in contract_clips:
            errors.append(f"director_core: unknown clip_id {clip_id}")
        if not isinstance(beats, list) or not beats:
            errors.append(f"director_core: {clip_id} needs beats")
            continue
        if len(beats) > 3:
            errors.append(f"director_core: {clip_id} has {len(beats)} beats; default maximum is 3")
        voiced_turns = 0
        expected_start = clip.get("start_seconds")
        for beat_index, beat in enumerate(beats):
            label = f"{clip_id}.beats[{beat_index}]"
            if not isinstance(beat, dict):
                errors.append(f"director_core: {label} must be an object")
                continue
            beat_id = beat.get("id")
            if not _text(beat_id) or beat_id in seen_beats:
                errors.append(f"director_core: {label} needs a unique id")
                continue
            start = beat.get("start_seconds")
            end = beat.get("end_seconds")
            if not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or end <= start:
                errors.append(f"director_core: {beat_id} needs increasing numeric timing")
            elif isinstance(expected_start, (int, float)) and abs(start - expected_start) > 0.001:
                errors.append(f"director_core: {beat_id} starts at {start}, expected {expected_start}")
            expected_start = end
            for field in ("new_information", "visible_action", "viewer_question"):
                if not _text(beat.get(field)):
                    errors.append(f"director_core: {beat_id}.{field} is required")
            cause = beat.get("caused_by")
            if ordered_beats and cause not in seen_beats:
                errors.append(f"director_core: {beat_id}.caused_by must name an earlier beat")
            if not ordered_beats and cause not in (None, "START"):
                errors.append("director_core: first beat caused_by must be START or null")

            shot = beat.get("shot")
            if not isinstance(shot, dict):
                errors.append(f"director_core: {beat_id}.shot is required")
            else:
                for field in ("framing", "primary_character_action", "primary_camera_action", "camera_purpose", "transition_trigger"):
                    if not _text(shot.get(field)):
                        errors.append(f"director_core: {beat_id}.shot.{field} is required")

            state_in = _state(beat.get("state_in"), f"{beat_id}.state_in", errors)
            state_out = _state(beat.get("state_out"), f"{beat_id}.state_out", errors)
            if previous_state and state_in:
                mismatches = [key for key in STATE_KEYS if previous_state.get(key) != state_in.get(key)]
                if mismatches:
                    errors.append(
                        f"director_core: state discontinuity {previous_label}->{beat_id}: {', '.join(sorted(mismatches))}"
                    )
            previous_state, previous_label = state_out, beat_id

            event = beat.get("action_event")
            if not isinstance(event, dict) or not _text(event.get("id")) or event.get("phase") not in EVENT_PHASES:
                errors.append(f"director_core: {beat_id}.action_event needs id and setup/progress/payoff phase")
            else:
                event_history.setdefault(event["id"], []).append((beat_id, event["phase"]))

            dialogue = beat.get("dialogue")
            if dialogue is not None:
                if not isinstance(dialogue, dict) or dialogue.get("speaker_mode") not in {"character", "controlled_voiceover"} or not _text(dialogue.get("text")):
                    errors.append(f"director_core: {beat_id}.dialogue is invalid")
                else:
                    voiced_turns += 1
                    if dialogue["speaker_mode"] == "character" and any(term in dialogue["text"] for term in SENSITIVE_TERMS):
                        supported = any(
                            beat_id in cue.get("supports_beat_ids", [])
                            and isinstance(cue.get("start_seconds"), (int, float))
                            and cue["start_seconds"] <= min(4.0, end if isinstance(end, (int, float)) else 4.0)
                            for cue in valid_cues
                        )
                        if not supported:
                            errors.append(
                                f"director_core: {beat_id} character commercial claim needs an early controlled truth cue"
                            )
            seen_beats[beat_id] = beat
            ordered_beats.append(beat)
        if voiced_turns > 2:
            errors.append(f"director_core: {clip_id} has {voiced_turns} spoken turns; default maximum is 2")
        clip_end = clip.get("end_seconds")
        if isinstance(expected_start, (int, float)) and isinstance(clip_end, (int, float)) and abs(expected_start - clip_end) > 0.001:
            errors.append(f"director_core: {clip_id} beats do not end at clip end")

    if ordered_beats:
        first = ordered_beats[0]
        if first.get("purpose") != "hook" or first.get("start_seconds", 1) > 0 or first.get("end_seconds", 0) < 3:
            errors.append("director_core: first beat must be a visible hook covering 0-3 seconds")
    for event_id, history in event_history.items():
        phases = [phase for _, phase in history]
        if phases.count("payoff") > 1:
            owners = ", ".join(beat_id for beat_id, phase in history if phase == "payoff")
            errors.append(f"director_core: action event {event_id} has duplicate payoff owners: {owners}")
        ranks = [EVENT_PHASES[phase] for phase in phases]
        if ranks != sorted(ranks):
            errors.append(f"director_core: action event {event_id} phases move backward")
        if phases[0] == "setup" and "payoff" not in phases:
            errors.append(f"director_core: action event {event_id} is set up but never paid off")

    coverage = plan.get("required_scene_actions")
    if not isinstance(coverage, list) or not coverage:
        errors.append("director_core: required_scene_actions coverage is required")
    else:
        for index, item in enumerate(coverage):
            if not isinstance(item, dict) or not _text(item.get("requirement")):
                errors.append(f"director_core: required_scene_actions[{index}] is invalid")
                continue
            covered = item.get("covered_by_beat_ids")
            if not isinstance(covered, list) or not covered or any(beat_id not in seen_beats for beat_id in covered):
                errors.append(f"director_core: scene action {index} must map to real beat ids")

    ending = plan.get("ending")
    if not isinstance(ending, dict) or not ordered_beats or ending.get("beat_id") != ordered_beats[-1].get("id") or not _text(ending.get("visible_resolution")):
        errors.append("director_core: ending must bind the last beat to a visible resolution")

    return {
        "status": "ok" if not errors else "failed",
        "plan": str(plan_path),
        "clip_count": len(clips),
        "beat_count": len(ordered_beats),
        "errors": errors,
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a v7.3 compact director plan.")
    parser.add_argument("project")
    parser.add_argument("--out")
    args = parser.parse_args()
    project = Path(args.project)
    contract = json.loads((project / "08_replica_contract.json").read_text(encoding="utf-8"))
    result = validate(project, contract)
    output = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(output + "\n", encoding="utf-8")
    print(output)
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
