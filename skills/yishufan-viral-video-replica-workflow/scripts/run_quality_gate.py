#!/usr/bin/env python3
"""Run the authoritative pre-generation, pre-stitch, or pre-publish quality gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import analyze_script  # noqa: E402
import validate_creative  # noqa: E402
import validate_delivery  # noqa: E402
import validate_director_qc  # noqa: E402
import validate_director_core  # noqa: E402
import validate_final_render  # noqa: E402
import validate_package  # noqa: E402
import validate_transcript  # noqa: E402


def return_stage(errors: list[str]) -> str:
    text = "\n".join(errors).lower()
    if any(term in text for term in ("director_core", "state discontinuity", "duplicate payoff owners")):
        return "director_plan"
    if "creative_review" in text:
        return "style_calibration" if any(word in text for word in ("style", "proof", "source_axes")) else "creative_room"
    if any(term in text for term in ("brief_alignment", "user confirmation", "requested_mode", "target duration changed")):
        return "brief"
    if any(term in text for term in ("visual_lock", "product_identity", "visual_style", "product reference asset")):
        return "visual_lock"
    if any(term in text for term in ("motion_beats", "camera-only motion", "handoff_in", "handoff_out", "motion_profile")):
        return "motion_design"
    if any(term in text for term in ("music_strategy", "user-confirmed music", "locked music")):
        return "music"
    if any(term in text for term in ("creative_room", "creative concept", "table read", "rejection_reason")):
        return "creative_room"
    if any(term in text for term in ("story_chain", "dramatic_question", "product a causal role", "resolution story")):
        return "story"
    if any(term in text for term in ("human_audio_qc", "final asr models disagree", "final asr: all models failed")):
        return "final_audio_qc"
    if any(term in text for term in ("script units", "speech", "spoken turns", "hero fact", "unexplained magic", "timed markdown")):
        return "screenplay"
    if any(term in text for term in ("storyboard", "prompt", "attachment", "visual_text")):
        return "storyboard_prompt"
    if any(term in text for term in ("output order", "duration differs", "audio stream", "9:16", "video dimensions", "final video", "fact card")):
        return "generation"
    if any(term in text for term in ("asr", "dialogue requirement", "dialogue order")):
        return "dialogue_prompt"
    if any(term in text for term in ("director", "story step evidence", "performance arc", "prop ", "continuity check", "final memory")):
        return "director_prompt"
    return "package"


def failed_result(error: Exception | str) -> dict:
    return {"status": "failed", "errors": [str(error)], "warnings": []}


def read_json(path: Path) -> dict:
    value = json.loads(path.expanduser().read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def run_gate(
    project: Path,
    stage: str,
    *,
    delivery_manifest: Path | None = None,
    asr_manifest: Path | None = None,
    director_manifest: Path | None = None,
    final_manifest: Path | None = None,
    render_validation: Path | None = None,
    audit_legacy: bool = False,
) -> dict:
    project = project.expanduser().resolve()
    try:
        contract = read_json(project / validate_package.CONTRACT_FILE)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        decision = {
            "pre-visual": "block_visual_tests",
            "pre-generation": "block_generation",
            "pre-stitch": "block_stitch",
            "pre-publish": "block_publish",
        }[stage]
        return {
            "status": "failed",
            "stage": stage,
            "decision": decision,
            "return_to_stage": "brief",
            "project": str(project),
            "results": {"contract": failed_result(exc)},
            "errors": [f"contract: {exc}"],
        }
    results: dict[str, dict] = {}
    for name, function in (("package", lambda p: validate_package.validate(p, stage=stage)), ("screenplay", analyze_script.analyze)):
        try:
            results[name] = function(project)
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
            results[name] = failed_result(exc)
    if contract.get("schema_version") != 5:
        if not audit_legacy:
            results["production_schema"] = failed_result("new production requires schema_version=5; --audit-legacy grants no production permission")
    else:
        try:
            results["creative"] = validate_creative.validate(project, contract, stage)
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            results["creative"] = failed_result(exc)
        if contract.get("director_core_version") == "7.3":
            try:
                results["director_core"] = validate_director_core.validate(project, contract)
            except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
                results["director_core"] = failed_result(exc)
    errors = [
        f"{name}: {error}"
        for name, result in results.items()
        for error in result.get("errors", [])
    ]

    director_data: dict = {}
    outputs: list = []
    if stage in {"pre-stitch", "pre-publish"}:
        required_paths = {
            "delivery_manifest": delivery_manifest,
            "asr_manifest": asr_manifest,
            "director_manifest": director_manifest,
        }
        for name, path in required_paths.items():
            if path is None:
                errors.append(f"quality_gate: {name} is required for {stage}")
        if delivery_manifest:
            try:
                manifest = read_json(delivery_manifest)
                outputs = validate_delivery.resolve_outputs(project, manifest)
                results["delivery"] = validate_delivery.evaluate_delivery(contract, outputs)
            except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
                results["delivery"] = failed_result(exc)
        if asr_manifest:
            try:
                manifest = read_json(asr_manifest)
                results["transcript"] = validate_transcript.validate_transcript(contract, manifest)
            except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
                results["transcript"] = failed_result(exc)
        if director_manifest:
            try:
                director_data = read_json(director_manifest)
                results["director"] = validate_director_qc.validate_director_qc(project, contract, director_data)
                if contract.get("schema_version") == 5:
                    delivery_files = {item.get("clip_id"): Path(item.get("file", "")).resolve() for item in outputs}
                    for review in director_data.get("timeline_reviews", []):
                        reviewed = (project / str(review.get("video_file", ""))).resolve()
                        if reviewed != delivery_files.get(review.get("clip_id")):
                            results["director"].setdefault("errors", []).append("director timeline video must match the actual delivery file for its clip_id")
            except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
                results["director"] = failed_result(exc)
        for name in ("delivery", "transcript", "director"):
            result = results.get(name, {})
            errors.extend(f"{name}: {error}" for error in result.get("errors", []))

    if stage == "pre-publish":
        if final_manifest is None:
            errors.append("quality_gate: final_manifest is required for pre-publish")
        else:
            try:
                final_data = read_json(final_manifest)
                results["final"] = validate_final_render.validate_final_render(
                    project, contract, final_data, director_data
                )
            except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
                results["final"] = failed_result(exc)
            errors.extend(f"final: {error}" for error in results["final"].get("errors", []))

    if stage == "pre-publish" and contract.get("mode") == "高保真视觉复刻":
        if render_validation is None:
            errors.append("quality_gate: render_validation is required to publish a high-fidelity replica")
        else:
            try:
                results["render"] = read_json(render_validation)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                results["render"] = failed_result(exc)
            if results["render"].get("status") != "ok":
                errors.extend(
                    f"render: {error}" for error in results["render"].get("errors", ["render validation failed"])
                )

    allowed = not errors
    decisions = {
        "pre-visual": ("allow_visual_tests", "block_visual_tests"),
        "pre-generation": ("allow_generation", "block_generation"),
        "pre-stitch": ("allow_stitch", "block_stitch"),
        "pre-publish": ("allow_publish", "block_publish"),
    }
    bound_inputs = {validate_package.CONTRACT_FILE: validate_creative.digest(project / validate_package.CONTRACT_FILE)}
    def bind_paths(value):
        if isinstance(value, dict):
            for item in value.values():
                bind_paths(item)
        elif isinstance(value, list):
            for item in value:
                bind_paths(item)
        elif isinstance(value, str) and len(value) < 1000 and "\n" not in value:
            candidate = (project / value).resolve()
            try:
                if candidate.is_relative_to(project) and candidate.is_file():
                    bound_inputs[str(candidate.relative_to(project))] = validate_creative.digest(candidate)
            except OSError:
                pass
    bind_paths(contract)
    bound_inputs.update(results.get("creative", {}).get("bound_inputs", {}))
    return {
        "status": "ok" if allowed else "failed",
        "stage": stage,
        "decision": "audit_only" if audit_legacy and allowed else decisions[stage][0] if allowed else decisions[stage][1],
        "production_authorized": allowed and not audit_legacy and stage != "pre-visual",
        "input_fingerprint": hashlib.sha256(json.dumps(bound_inputs, sort_keys=True).encode()).hexdigest(),
        "bound_inputs": bound_inputs,
        "return_to_stage": None if allowed else return_stage(errors),
        "project": str(project),
        "results": results,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the full viral-replica quality gate.")
    parser.add_argument("project")
    parser.add_argument("--stage", choices=("pre-visual", "pre-generation", "pre-stitch", "pre-publish"), required=True)
    parser.add_argument("--audit-legacy", action="store_true", help="Read-only historical audit; never grants production permission")
    parser.add_argument("--delivery-manifest")
    parser.add_argument("--asr-manifest")
    parser.add_argument("--director-manifest")
    parser.add_argument("--final-manifest")
    parser.add_argument("--render-validation")
    parser.add_argument("--out")
    args = parser.parse_args()
    result = run_gate(
        Path(args.project),
        args.stage,
        delivery_manifest=Path(args.delivery_manifest) if args.delivery_manifest else None,
        asr_manifest=Path(args.asr_manifest) if args.asr_manifest else None,
        director_manifest=Path(args.director_manifest) if args.director_manifest else None,
        final_manifest=Path(args.final_manifest) if args.final_manifest else None,
        render_validation=Path(args.render_validation) if args.render_validation else None,
        audit_legacy=args.audit_legacy,
    )
    output = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).expanduser().write_text(output, encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
