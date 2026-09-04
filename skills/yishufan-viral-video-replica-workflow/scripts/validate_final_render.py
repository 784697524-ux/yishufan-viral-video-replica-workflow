#!/usr/bin/env python3
"""Validate the actual stitched video before any replica may be published."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import subprocess
from pathlib import Path

import validate_delivery
import validate_transcript


CONTRACT_FILE = "08_replica_contract.json"
MIN_FACT_CARD_SIMILARITY = 0.90
MAX_FACT_CARD_SECONDS = 2.5


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def project_file(project: Path, value: object, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} is required")
    path = (project / value).resolve() if not Path(value).is_absolute() else Path(value).resolve()
    try:
        path.relative_to(project)
    except ValueError as exc:
        raise ValueError(f"{label} must be inside the project") from exc
    if not path.is_file():
        raise ValueError(f"{label} does not exist: {value}")
    return path


def target_duration(contract: dict) -> float:
    aligned = contract.get("brief_alignment", {}).get("resolved_duration_seconds")
    if isinstance(aligned, (int, float)) and float(aligned) > 0:
        return float(aligned)
    ends = [
        float(item.get("end_seconds") or 0)
        for item in contract.get("clips", [])
        if isinstance(item, dict)
    ]
    return max(ends, default=0.0)


def evaluate_final_metrics(contract: dict, metrics: dict, max_duration_delta: float = 0.5) -> tuple[list[str], list[str]]:
    expected = target_duration(contract)
    errors: list[str] = []
    warnings: list[str] = []
    actual = float(metrics.get("duration_seconds") or 0)
    if expected <= 0 or abs(actual - expected) > max_duration_delta:
        errors.append(f"final video duration differs; expected {expected:.3f}s, got {actual:.3f}s")
    width = metrics.get("width")
    height = metrics.get("height")
    if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
        errors.append("final video has no readable video dimensions")
    else:
        if abs(width / height - 9 / 16) > 0.015:
            errors.append(f"final video is {width}x{height}, not 9:16")
        if width < 720 or height < 1280:
            warnings.append(f"final video resolution {width}x{height} is below 720x1280")
    if metrics.get("has_audio") is not True:
        errors.append("final video has no audio stream")
    return errors, warnings


def clips_from_absolute_segments(contract: dict, segments: list[dict]) -> dict:
    clips = []
    for clip in contract.get("clips", []):
        if not isinstance(clip, dict):
            continue
        clip_start = float(clip.get("start_seconds") or 0)
        clip_end = float(clip.get("end_seconds") or clip_start)
        selected = []
        for segment in segments:
            if not isinstance(segment, dict):
                continue
            start = float(segment.get("start_seconds", segment.get("start", 0)) or 0)
            end = float(segment.get("end_seconds", segment.get("end", start)) or start)
            if end < clip_start - 0.01 or start > clip_end + 0.01:
                continue
            selected.append(
                {
                    "start_seconds": max(0.0, start - clip_start),
                    "end_seconds": min(clip_end - clip_start, end - clip_start),
                    "text": segment.get("text", ""),
                }
            )
        clips.append({"clip_id": clip.get("id"), "segments": selected})
    return {"clips": clips}


def validate_asr_consensus(project: Path, contract: dict, manifest: dict, video_sha256: str) -> dict:
    project = project.expanduser().resolve()
    errors: list[str] = []
    runs = manifest.get("asr_runs")
    if not isinstance(runs, list) or len(runs) < 2:
        return {"status": "failed", "runs": [], "errors": ["final ASR requires at least two model runs"]}

    try:
        evidence_path = project_file(project, manifest.get("asr_evidence_file"), "asr_evidence_file")
        if manifest.get("asr_evidence_sha256") != sha256_file(evidence_path):
            errors.append("asr_evidence_sha256 does not match the ASR evidence file")
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        if evidence.get("source", {}).get("sha256") != video_sha256:
            errors.append("ASR evidence source SHA-256 does not match the final video")
        transcripts = evidence.get("transcripts")
        if not isinstance(transcripts, dict):
            transcripts = {}
            errors.append("ASR evidence does not contain model transcripts")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        transcripts = {}
        errors.append(f"final ASR evidence failed: {exc}")

    models = [item.get("model") for item in runs if isinstance(item, dict)]
    if len(models) != len(runs) or any(not isinstance(model, str) or not model.strip() for model in models):
        errors.append("every final ASR run must name its model")
    elif len(set(models)) != len(models):
        errors.append("final ASR runs must use different models")

    run_results: list[dict] = []
    for index, run in enumerate(runs):
        if not isinstance(run, dict):
            errors.append(f"final ASR run {index} must be an object")
            continue
        if run.get("video_sha256") != video_sha256:
            errors.append(f"final ASR run {run.get('model') or index} is not bound to the final video SHA-256")
        segments = transcripts.get(run.get("model"))
        if not isinstance(segments, list):
            errors.append(f"ASR evidence is missing transcript for model {run.get('model') or index}")
            segments = []
        result = validate_transcript.validate_transcript(contract, clips_from_absolute_segments(contract, segments))
        run_results.append({"model": run.get("model"), **result})

    human_qc = manifest.get("human_audio_qc")
    if not isinstance(human_qc, dict):
        errors.append("human_audio_qc is required for the final video")
        human_qc = {}
    for field in ("listened", "voice_consistency_passed", "double_voice_absent", "speech_audible_over_music"):
        if human_qc.get(field) is not True:
            errors.append(f"human_audio_qc.{field} must be true")
    for field in ("reviewer", "reviewed_at"):
        if not isinstance(human_qc.get(field), str) or not human_qc.get(field, "").strip():
            errors.append(f"human_audio_qc.{field} is required")

    confirmed = set(human_qc.get("confirmed_requirement_ids") or [])
    override_reason = str(human_qc.get("override_reason") or "").strip()
    for requirement in contract.get("dialogue_requirements", []):
        requirement_id = requirement.get("id")
        states = [
            next((item.get("passed") for item in result.get("requirements", []) if item.get("id") == requirement_id), False)
            for result in run_results
        ]
        passed_count = sum(state is True for state in states)
        if passed_count == 0:
            errors.append(f"final ASR: all models failed dialogue requirement {requirement_id}")
        elif passed_count < len(run_results):
            if requirement_id not in confirmed or not override_reason:
                errors.append(
                    f"final ASR models disagree on {requirement_id}; audited human confirmation and override_reason are required"
                )

    return {"status": "ok" if not errors else "failed", "runs": run_results, "errors": errors}


def final_story_timestamp(contract: dict, director_manifest: dict) -> float | None:
    final_id = contract.get("director_requirements", {}).get("final_memory_step_id")
    for item in director_manifest.get("story_steps", []):
        if isinstance(item, dict) and item.get("id") == final_id and isinstance(item.get("timestamp_seconds"), (int, float)):
            return float(item["timestamp_seconds"])
    return None


def frame_similarity(video: Path, source: Path, sample_seconds: float, crop: dict) -> float:
    try:
        from PIL import Image, ImageChops, ImageStat
    except ImportError as exc:
        raise RuntimeError("Pillow is required for final fact-card verification") from exc

    result = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-ss",
            str(sample_seconds),
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-f",
            "image2pipe",
            "-vcodec",
            "png",
            "pipe:1",
        ],
        check=True,
        capture_output=True,
    )
    with Image.open(io.BytesIO(result.stdout)) as frame_image, Image.open(source) as source_image:
        box = tuple(int(crop[name]) for name in ("x", "y", "width", "height"))
        x, y, width, height = box
        if width <= 0 or height <= 0 or x < 0 or y < 0 or x + width > frame_image.width or y + height > frame_image.height:
            raise ValueError("final fact-card crop is outside the final frame")
        observed = frame_image.convert("RGB").crop((x, y, x + width, y + height))
        expected = source_image.convert("RGB").resize(observed.size)
        mean = ImageStat.Stat(ImageChops.difference(observed, expected)).mean
        return 1.0 - sum(mean[:3]) / (3 * 255)


def validate_finale(
    project: Path,
    contract: dict,
    manifest: dict,
    director_manifest: dict,
    video: Path,
    metrics: dict,
) -> dict:
    errors: list[str] = []
    policy = contract.get("finale_policy")
    if not isinstance(policy, dict) or policy.get("type") not in {"story_action", "source_fact_card"}:
        return {"status": "failed", "errors": ["contract.finale_policy must choose story_action or source_fact_card"]}
    resolution_time = final_story_timestamp(contract, director_manifest)
    if resolution_time is None:
        errors.append("final story resolution timestamp is missing from director evidence")

    if policy.get("type") == "story_action":
        if resolution_time is not None and resolution_time < float(metrics.get("duration_seconds") or 0) - 3.1:
            errors.append("final story action is not evidenced inside the last 3 seconds")
        return {"status": "ok" if not errors else "failed", "type": "story_action", "errors": errors}

    observed = manifest.get("final_fact_card")
    if not isinstance(observed, dict):
        return {"status": "failed", "type": "source_fact_card", "errors": ["final_fact_card evidence is required"]}
    for field in ("source_file", "start_seconds", "end_seconds"):
        if observed.get(field) != policy.get(field):
            errors.append(f"final_fact_card.{field} does not match contract.finale_policy")
    start = float(policy.get("start_seconds") or 0)
    end = float(policy.get("end_seconds") or 0)
    sample = float(observed.get("sample_seconds") or 0)
    if end <= start or end - start > MAX_FACT_CARD_SECONDS:
        errors.append(f"final fact card must last no more than {MAX_FACT_CARD_SECONDS:.1f}s")
    if end > float(metrics.get("duration_seconds") or 0) + 0.1:
        errors.append("final fact card ends after the final video")
    if not start <= sample <= end:
        errors.append("final_fact_card.sample_seconds must fall inside the card interval")
    if resolution_time is not None and resolution_time > start + 0.01:
        errors.append("story resolution must be visible before the final fact card begins")

    try:
        source = project_file(project, policy.get("source_file"), "contract.finale_policy.source_file")
        source_sha = sha256_file(source)
        if observed.get("source_sha256") != source_sha:
            errors.append("final_fact_card.source_sha256 does not match the source image")
        crop = observed.get("crop")
        if not isinstance(crop, dict) or any(name not in crop for name in ("x", "y", "width", "height")):
            errors.append("final_fact_card.crop must provide x, y, width, and height")
            similarity = None
        else:
            similarity = frame_similarity(video, source, sample, crop)
            threshold = max(float(observed.get("min_similarity") or 0), MIN_FACT_CARD_SIMILARITY)
            if similarity < threshold:
                errors.append(f"final fact card similarity {similarity:.3f} is below {threshold:.3f}")
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        similarity = None
        errors.append(f"final fact card verification failed: {exc}")
    return {
        "status": "ok" if not errors else "failed",
        "type": "source_fact_card",
        "similarity": similarity,
        "errors": errors,
    }


def validate_final_render(project: Path, contract: dict, manifest: dict, director_manifest: dict) -> dict:
    project = project.expanduser().resolve()
    errors: list[str] = []
    warnings: list[str] = []
    try:
        video = project_file(project, manifest.get("file"), "final video file")
        actual_sha = sha256_file(video)
        metrics = validate_delivery.probe(video)
    except (OSError, ValueError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        return {"status": "failed", "errors": [str(exc)], "warnings": []}

    expected_ids = [item.get("id") for item in contract.get("clips", []) if isinstance(item, dict)]
    if manifest.get("source_clip_ids") != expected_ids:
        errors.append("final video source_clip_ids do not match contract clip order")
    if manifest.get("sha256") != actual_sha:
        errors.append("final video SHA-256 does not match final manifest")
    metric_errors, metric_warnings = evaluate_final_metrics(contract, metrics)
    errors.extend(metric_errors)
    warnings.extend(metric_warnings)

    asr_result = validate_asr_consensus(project, contract, manifest, actual_sha)
    errors.extend(asr_result["errors"])
    finale_result = validate_finale(project, contract, manifest, director_manifest, video, metrics)
    errors.extend(finale_result["errors"])
    return {
        "status": "ok" if not errors else "failed",
        "file": str(video),
        "sha256": actual_sha,
        "metrics": metrics,
        "asr": asr_result,
        "finale": finale_result,
        "errors": errors,
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the stitched final video before publishing.")
    parser.add_argument("project")
    parser.add_argument("manifest")
    parser.add_argument("--director-manifest", required=True)
    parser.add_argument("--out")
    args = parser.parse_args()
    project = Path(args.project).expanduser().resolve()
    contract = json.loads((project / CONTRACT_FILE).read_text(encoding="utf-8"))
    manifest = json.loads(Path(args.manifest).expanduser().read_text(encoding="utf-8"))
    director = json.loads(Path(args.director_manifest).expanduser().read_text(encoding="utf-8"))
    result = validate_final_render(project, contract, manifest, director)
    output = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).expanduser().write_text(output, encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
