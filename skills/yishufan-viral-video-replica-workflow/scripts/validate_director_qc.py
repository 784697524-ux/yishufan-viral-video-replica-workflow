#!/usr/bin/env python3
"""Validate Watch-backed director evidence for story, performance, props, and final memory point."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
from pathlib import Path

from PIL import Image, ImageChops, ImageStat


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
COMPARISON_SIZE = (128, 128)
VISUAL_AXES = ("palette", "line_and_fill", "texture", "character_rendering", "space", "activity_density")
CONTINUITY_STATE_AXES = (
    "character",
    "prop",
    "action_phase",
    "screen_direction",
    "background_cast",
    "scene_inventory",
)


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def finite_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def local_file(project: Path, value: object, errors: list[str], label: str) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{label} must name a local evidence file")
        return None
    path = (project / value).resolve()
    if not path.is_relative_to(project) or not path.is_file():
        errors.append(f"{label} must be an existing file inside the project")
        return None
    return path


def decode_video_evidence(path: Path) -> dict:
    """Decode the same fixed-fps samples as prepare_reference, plus actual end frames."""
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height,duration:format=duration:frame=best_effort_timestamp_time",
         "-of", "json", str(path)], capture_output=True, text=True, check=True, timeout=60,
    )
    data = json.loads(probe.stdout)
    stream = data["streams"][0]
    timestamps = [float(frame["best_effort_timestamp_time"]) for frame in data.get("frames", [])]
    if not timestamps or not all(math.isfinite(value) for value in timestamps):
        raise ValueError("video has no finite decoded frame timestamps")
    duration = float(stream.get("duration") or data.get("format", {}).get("duration"))
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("video duration is invalid")

    def decode(filter_text: str) -> list[Image.Image]:
        result = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(path), "-vf", filter_text + ",scale=128:128:flags=area",
             "-vsync", "0", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
            capture_output=True, check=True, timeout=60,
        )
        size = 128 * 128 * 3
        if not result.stdout or len(result.stdout) % size:
            raise ValueError("video frame decode is incomplete")
        return [Image.frombytes("RGB", COMPARISON_SIZE, result.stdout[index:index + size])
                for index in range(0, len(result.stdout), size)]

    frames = decode("fps=fps=2:start_time=0")
    boundaries = decode(f"select='eq(n,0)+eq(n,{len(timestamps) - 1})'")
    last_timestamp = timestamps[-1] - timestamps[0]
    if (len(frames) - 1) * 0.5 < last_timestamp - 0.501:
        raise ValueError("fixed timeline decode stops before the end of the actual video")
    return {"duration": duration, "width": stream["width"], "height": stream["height"],
            "frames": frames, "first_frame": boundaries[0], "last_frame": boundaries[-1],
            "first_timestamp": 0.0, "last_timestamp": last_timestamp}


def compare_bound_frame(project: Path, item: dict, reference: Image.Image, video: dict,
                        errors: list[str], label: str) -> Path | None:
    """Tolerate resizing/JPEG, but reject unrelated imagery. This is not semantic QC."""
    path = local_file(project, item.get("evidence_file"), errors, f"{label}.evidence_file")
    if not isinstance(item.get("observation"), str) or not item.get("observation", "").strip():
        errors.append(f"{label}.observation must describe the visible frame state")
    if not path:
        return None
    if item.get("sha256") != file_hash(path):
        errors.append(f"{label}.sha256 does not match the evidence frame")
    try:
        with Image.open(path) as image:
            image.load()
            if abs(image.width / image.height - video["width"] / video["height"]) > 0.02:
                errors.append(f"{label} aspect ratio differs from its source video")
            candidate = image.convert("RGB").resize(COMPARISON_SIZE, Image.Resampling.BOX)
        difference = ImageChops.difference(candidate, reference)
        mean_error = sum(ImageStat.Stat(difference).mean) / 3
        changed = sum(max(pixel) > 32 for pixel in difference.getdata()) / (128 * 128)
        if mean_error > 12 or changed > 0.10:
            errors.append(f"{label} does not match the decoded video frame at its timestamp (RGB error {mean_error:.2f}, changed {changed:.3f})")
    except (OSError, ValueError, SyntaxError) as exc:
        errors.append(f"{label} is not a decodable image: {exc}")
        return None
    return path


def validate_bound_timelines(project: Path, clips: dict, reviews: list, errors: list[str]) -> tuple[dict, dict]:
    videos: dict[str, dict] = {}
    bound_frames: dict[Path, list[tuple[str, float]]] = {}
    review_ids = [item.get("clip_id") for item in reviews if isinstance(item, dict)]
    if review_ids != list(clips):
        errors.append("schema v5 timeline_reviews must cover every clip exactly once in contract order")
    for review in reviews:
        if not isinstance(review, dict) or review.get("clip_id") not in clips:
            continue
        clip_id = review["clip_id"]
        label = f"timeline_reviews.{clip_id}"
        path = local_file(project, review.get("video_file"), errors, f"{label}.video_file")
        if not path:
            continue
        if review.get("video_sha256") != file_hash(path):
            errors.append(f"{label}.video_sha256 does not match the actual video")
        try:
            video = decode_video_evidence(path)
        except (OSError, ValueError, KeyError, IndexError, subprocess.SubprocessError) as exc:
            errors.append(f"{label} cannot decode actual video evidence: {exc}")
            continue
        videos[clip_id] = video
        clip = clips[clip_id]
        if abs(video["duration"] - (float(clip["end_seconds"]) - float(clip["start_seconds"]))) > 0.5:
            errors.append(f"{label} actual video duration differs from the contract")
        frames = review.get("frames")
        if not isinstance(frames, list) or len(frames) != len(video["frames"]):
            errors.append(f"{label}.frames must contain all {len(video['frames'])} decoded fixed 0.5s samples")
            frames = frames if isinstance(frames, list) else []
        if review.get("reviewed_frame_count") != len(video["frames"]):
            errors.append(f"{label}.reviewed_frame_count must equal the actual decoded sample count")
        if review.get("reviewed_last_timestamp_seconds") != (len(video["frames"]) - 1) * 0.5:
            errors.append(f"{label}.reviewed_last_timestamp_seconds must equal the actual final sample time")
        for index, item in enumerate(frames):
            frame_label = f"{label}.frames[{index}]"
            if not isinstance(item, dict):
                errors.append(f"{frame_label} must be an object")
                continue
            timestamp = item.get("timestamp_seconds")
            if not finite_number(timestamp) or abs(timestamp - index * 0.5) > 0.001:
                errors.append(f"{frame_label}.timestamp_seconds must be {index * 0.5:.1f} (complete ordered 0.5s grid)")
            if index < len(video["frames"]):
                frame_path = compare_bound_frame(project, item, video["frames"][index], video, errors, frame_label)
                if frame_path:
                    bound_frames.setdefault(frame_path, []).append((clip_id, index * 0.5))
    return videos, bound_frames


def validate_observation_binding(project: Path, item: dict, clips: dict, bound_frames: dict,
                                 errors: list[str], label: str, observation_field: str) -> None:
    clip_id = item.get("clip_id")
    if clip_id not in clips:
        errors.append(f"{label}.clip_id must bind the observation to a generated clip")
        return
    timestamp = item.get("timestamp_seconds")
    path = (project / str(item.get("evidence_file", ""))).resolve()
    relative = timestamp - float(clips[clip_id]["start_seconds"]) if finite_number(timestamp) else None
    matches = bound_frames.get(path, [])
    if relative is None or not any(key == clip_id and abs(time - relative) <= 0.251 for key, time in matches):
        errors.append(f"{label} must reference a verified frame within 0.25s of its global story timestamp")
    if not isinstance(item.get(observation_field), str) or not item.get(observation_field, "").strip():
        errors.append(f"{label}.{observation_field} must describe the actual visible state")


def verified_clip_frame(project: Path, value: object, clip_id: str, bound_frames: dict,
                        errors: list[str], label: str) -> Path | None:
    path = (project / value).resolve() if isinstance(value, str) and value.strip() else None
    if path is None or not any(key == clip_id for key, _ in bound_frames.get(path, [])):
        errors.append(f"{label}.evidence_file must reference a verified timeline frame from {clip_id}")
        return None
    return path


def validate_actual_visuals(project: Path, contract: dict, manifest: dict, clips: dict,
                           bound_frames: dict, errors: list[str]) -> None:
    """Require source-to-render visual observations, not proof-image-only approval."""
    reviews = manifest.get("timeline_reviews")
    for review in reviews if isinstance(reviews, list) else []:
        if not isinstance(review, dict):
            continue
        clip_id = review.get("clip_id")
        comparisons = review.get("visual_comparisons")
        if not isinstance(comparisons, dict):
            errors.append(f"timeline_reviews.{clip_id}.visual_comparisons must cover all six source-to-video axes")
            continue
        for axis in VISUAL_AXES:
            label = f"timeline_reviews.{clip_id}.visual_comparisons.{axis}"
            item = comparisons.get(axis)
            if not isinstance(item, dict):
                errors.append(f"{label} is required for the actual generated video")
                continue
            reference = local_file(project, item.get("reference_file"), errors, f"{label}.reference_file")
            evidence = verified_clip_frame(project, item.get("evidence_file"), clip_id, bound_frames, errors, label)
            if reference:
                digest = file_hash(reference)
                if item.get("reference_sha256") != digest:
                    errors.append(f"{label}.reference_sha256 does not match the source image")
                if evidence and file_hash(evidence) == digest:
                    errors.append(f"{label} must compare the actual output against a separate source reference, not itself")
                try:
                    with Image.open(reference) as image:
                        image.load()
                except (OSError, ValueError, SyntaxError) as exc:
                    errors.append(f"{label}.reference_file is not a decodable source image: {exc}")
            for field in ("source_observation", "output_observation"):
                if not isinstance(item.get(field), str) or not item.get(field, "").strip():
                    errors.append(f"{label}.{field} must contain a concrete visual observation")
            if item.get("verdict") != "pass":
                errors.append(f"{label} has an unresolved actual-video visual failure")

    direction = contract.get("creative_direction", {})
    required = direction.get("required_scene_actions", []) if isinstance(direction, dict) else []
    if not isinstance(required, list) or any(not isinstance(value, str) or not value.strip() for value in required):
        errors.append("creative_direction.required_scene_actions must be an array of concrete requirements")
        return
    if not required:
        return
    checks = manifest.get("scene_action_checks")
    if not isinstance(checks, list):
        errors.append("scene_action_checks must evidence every required scene action in the actual video")
        return
    covered: set[str] = set()
    for index, item in enumerate(checks):
        label = f"scene_action_checks[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{label} must be an object")
            continue
        requirement = item.get("requirement")
        if not isinstance(requirement, str) or requirement not in required:
            errors.append(f"{label}.requirement must name a required scene action")
        else:
            covered.add(requirement)
        clip_id = item.get("clip_id")
        if not isinstance(clip_id, str) or clip_id not in clips:
            errors.append(f"{label}.clip_id must identify a generated clip")
        verified_clip_frame(project, item.get("evidence_file"), clip_id, bound_frames, errors, label)
        if not isinstance(item.get("observed_action"), str) or not item.get("observed_action", "").strip():
            errors.append(f"{label}.observed_action must describe a visible scene action")
        if item.get("verdict") != "pass":
            errors.append(f"{label} has an unresolved scene-action failure")
    if covered != set(required):
        errors.append("scene_action_checks must cover every required scene action")


def validate_bound_continuity(project: Path, check: dict, videos: dict, errors: list[str], label: str) -> None:
    for field, clip_key, endpoint in (("from_frame", "from_clip_id", "last"), ("to_frame", "to_clip_id", "first")):
        frame = check.get(field)
        video = videos.get(check.get(clip_key))
        if not isinstance(frame, dict) or video is None:
            errors.append(f"{label}.{field} requires a bound actual {endpoint} video frame")
            continue
        timestamp = frame.get("timestamp_seconds")
        if not finite_number(timestamp) or abs(timestamp - video[f"{endpoint}_timestamp"]) > 0.001:
            errors.append(f"{label}.{field}.timestamp_seconds must be the actual {endpoint} decoded frame time")
        compare_bound_frame(project, frame, video[f"{endpoint}_frame"], video, errors, f"{label}.{field}")
    states = check.get("state_checks")
    if not isinstance(states, dict):
        errors.append(f"{label}.state_checks must describe both sides of the actual clip boundary")
        return
    for name in CONTINUITY_STATE_AXES:
        item = states.get(name)
        if not isinstance(item, dict):
            errors.append(f"{label}.state_checks.{name} is required")
            continue
        for field in ("from_state", "to_state", "reason"):
            if not isinstance(item.get(field), str) or not item.get(field, "").strip():
                errors.append(f"{label}.state_checks.{name}.{field} must contain a concrete observation")
        if item.get("verdict") != "consistent":
            errors.append(f"{label}.state_checks.{name} has an unresolved continuity mismatch")


def validate_retention_checks(project: Path, manifest: dict, clips: dict, bound_frames: dict,
                              errors: list[str]) -> None:
    """Require explicit review of the hook and dead viewing time after generation."""
    clip_ids = list(clips)
    expected = ([('hook_salience', clip_ids[0])] if clip_ids else []) + [
        ("dead_time", clip_id) for clip_id in clip_ids
    ]
    checks = manifest.get("retention_checks")
    if not isinstance(checks, list):
        errors.append("retention_checks must cover the opening hook and dead time in every generated clip")
        return
    observed = [
        (item.get("criterion"), item.get("clip_id"))
        for item in checks if isinstance(item, dict)
    ]
    if observed != expected:
        errors.append(f"retention checks {observed} do not match required order {expected}")
    for index, item in enumerate(checks):
        label = f"retention_checks[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{label} must be an object")
            continue
        criterion = item.get("criterion")
        clip_id = item.get("clip_id")
        if (criterion, clip_id) not in expected:
            errors.append(f"{label} must identify a required retention criterion and clip")
            continue
        duration = float(clips[clip_id]["end_seconds"]) - float(clips[clip_id]["start_seconds"])
        required_end = min(3.0, duration) if criterion == "hook_salience" else duration
        start = item.get("reviewed_start_seconds")
        end = item.get("reviewed_end_seconds")
        if not finite_number(start) or abs(float(start)) > 0.001:
            errors.append(f"{label}.reviewed_start_seconds must be 0.0")
        if not finite_number(end) or abs(float(end) - required_end) > 0.001:
            errors.append(f"{label}.reviewed_end_seconds must be {required_end:.1f}")
        evidence_files = item.get("evidence_files")
        if not isinstance(evidence_files, list) or len(evidence_files) < 2:
            errors.append(f"{label}.evidence_files must contain at least two verified timeline frames")
        else:
            matched_times: list[float] = []
            for evidence in evidence_files:
                path = verified_clip_frame(project, evidence, clip_id, bound_frames, errors, label)
                if path:
                    matched_times.extend(time for key, time in bound_frames.get(path, []) if key == clip_id)
            if criterion == "hook_salience" and not any(0 <= time <= required_end + 0.001 for time in matched_times):
                errors.append(f"{label} must include verified evidence from the first {required_end:.1f} seconds")
        if not isinstance(item.get("observation"), str) or not item.get("observation", "").strip():
            errors.append(f"{label}.observation must state the visible retention evidence")
        if item.get("verdict") != "pass":
            errors.append(f"{label} has an unresolved retention failure")


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
    schema_five = contract.get("schema_version") == 5
    videos, bound_frames = validate_bound_timelines(project, clips, timeline_reviews if isinstance(timeline_reviews, list) else [], errors) if schema_five else ({}, {})
    if schema_five:
        warnings.append("Frame matching verifies media provenance, not semantic truth, acting quality, or audience retention; observations require real visual review.")
        validate_actual_visuals(project, contract, manifest, clips, bound_frames, errors)
        validate_retention_checks(project, manifest, clips, bound_frames, errors)
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
        if schema_five:
            validate_observation_binding(project, item, clips, bound_frames, errors, label, "observed_action")

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
            if schema_five:
                validate_observation_binding(project, state, clips, bound_frames, errors, label, "observed_state")

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
            if schema_five:
                validate_observation_binding(project, event, clips, bound_frames, errors, label, "observed_action")

    expected_pairs = [
        (item.get("from_clip_id"), item.get("to_clip_id"))
        for item in contract.get("continuity", [])
        if isinstance(item, dict) and item.get("from_clip_id") and item.get("to_clip_id")
    ]
    if schema_five:
        clip_ids = list(clips)
        expected_pairs = list(zip(clip_ids, clip_ids[1:]))
    checks = manifest.get("continuity_checks", [])
    observed_pairs = [
        (item.get("from_clip_id"), item.get("to_clip_id")) for item in checks if isinstance(item, dict)
    ]
    if observed_pairs != expected_pairs:
        errors.append(f"continuity checks {observed_pairs} do not match contract {expected_pairs}")
    for index, check in enumerate(checks):
        label = f"continuity_checks[{index}]"
        if not isinstance(check, dict):
            errors.append(f"{label} must be an object")
            continue
        if check.get("passed") is not True:
            errors.append(f"{label} failed")
        if schema_five:
            validate_bound_continuity(project, check, videos, errors, label)
        else:
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
            if not finite_number(value) or value < 0 or value > maximum:
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
