"""Validate review evidence, not artistic merit. Schema 5 production prerequisite."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from PIL import Image

AXES = {"palette", "line_and_fill", "texture", "character_rendering", "space", "activity_density"}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate(project: Path, contract: dict, stage: str) -> dict:
    errors = []
    inputs = {}

    def require(value, label):
        if not isinstance(value, str) or not value.strip():
            errors.append(f"creative_review: {label} needs a concrete observation")

    def asset(item, label, picture=False):
        if not isinstance(item, dict):
            errors.append(f"creative_review: {label} must bind file and sha256")
            return None
        path = (project / str(item.get("file", ""))).resolve()
        if not path.is_relative_to(project.resolve()) or not path.is_file():
            errors.append(f"creative_review: {label} missing file or escapes project")
            return None
        actual = digest(path)
        inputs[str(path.relative_to(project.resolve()))] = actual
        if item.get("sha256") != actual:
            errors.append(f"creative_review: {label} stale sha256")
        if picture:
            try:
                with Image.open(path) as im:
                    im.verify()
            except (OSError, ValueError) as exc:
                errors.append(f"creative_review: {label} image cannot decode: {exc}")
        return path

    direction = contract.get("creative_direction", {})
    for key in ("audience_desire", "commercial_promise", "scene_promise"):
        require(direction.get(key), key)
    review_path = (project / str(direction.get("review_file", ""))).resolve()
    if not review_path.is_relative_to(project.resolve()) or not review_path.is_file():
        return {"status": "failed", "errors": errors + ["creative_review: review_file is required"], "warnings": []}
    review = json.loads(review_path.read_text(encoding="utf-8"))
    if not isinstance(review, dict):
        raise ValueError("creative_review must be an object")
    inputs[str(review_path.relative_to(project.resolve()))] = digest(review_path)
    script = asset(review.get("script"), "script")
    expected_script = (project / contract.get("deliverables", {}).get("script", "")).resolve()
    if script != expected_script:
        errors.append("creative_review: script must be the contract deliverable")
    script_ids = set(re.findall(r"\bS\d+\b", script.read_text(encoding="utf-8"))) if script else set()

    def script_ref(value, label):
        if value not in script_ids:
            errors.append(f"creative_review: {label} unknown script_id {value}")

    editor = review.get("editor", {})
    if editor.get("kind") not in {"independent_agent", "human"}:
        errors.append("creative_review: independent editor or human review required; author self-score is not approval")
    require(editor.get("name"), "editor.name")
    require(editor.get("most_likely_swipe_away"), "editor.most_likely_swipe_away")
    require(editor.get("revision_evidence"), "editor.revision_evidence")
    if review.get("decision") != "approved" or review.get("unresolved_issues") != []:
        errors.append("creative_review: rejected, unknown or unresolved editorial issues")
    hook = review.get("hook", {})
    if not isinstance(hook.get("end_seconds"), (int, float)) or not 0 < hook["end_seconds"] <= 3:
        errors.append("creative_review: hook must deliver within the first 3 seconds")
    for key in ("visible_action", "viewer_question", "benefit_cue"):
        require(hook.get(key), f"hook.{key}")
    script_ref(hook.get("script_id"), "hook")
    beats = review.get("retention_beats", [])
    seen, reversal_count, last_time = set(), 0, -1
    for beat in beats:
        beat_id = beat.get("id")
        if not beat_id or beat_id in seen:
            errors.append("creative_review: retention beat id missing or duplicated")
        script_ref(beat.get("script_id"), str(beat_id))
        timestamp = beat.get("timestamp_seconds")
        if not isinstance(timestamp, (int, float)) or not last_time <= timestamp <= contract.get("target_duration_seconds", 0):
            errors.append(f"creative_review: {beat_id} timestamp outside ordered target timeline")
        else:
            last_time = timestamp
        for key in ("expectation_before", "visible_change", "expectation_after", "consequence", "next_question"):
            require(beat.get(key), f"{beat_id}.{key}")
        if beat.get("type") == "reversal":
            reversal_count += 1
            if beat.get("setup_id") not in seen:
                errors.append(f"creative_review: {beat_id} reversal needs earlier setup_id")
            if beat.get("expectation_before") == beat.get("expectation_after"):
                errors.append(f"creative_review: {beat_id} unchanged expectation is not a reversal")
        seen.add(beat_id)
    minimum = direction.get("minimum_reversals", 0)
    if not isinstance(minimum, int) or minimum < 0 or reversal_count < minimum:
        errors.append("creative_review: requested reversals are not covered")
    if not beats or beats[-1].get("type") != "payoff":
        errors.append("creative_review: retention ledger must end in a visible payoff")
    required_actions = direction.get("required_scene_actions", [])
    if not isinstance(required_actions, list) or not required_actions:
        errors.append("creative_review: required_scene_actions must state the user's visible scene promise")
        required_actions = []
    coverage = review.get("scene_action_coverage", [])
    for action in required_actions:
        matches = [row for row in coverage if row.get("requirement") == action]
        if not matches:
            errors.append(f"creative_review: scene promise has no visible evidence: {action}")
        for row in matches:
            script_ref(row.get("script_id"), "scene_action_coverage")
            require(row.get("visible_action"), "scene_action_coverage.visible_action")

    style = review.get("style_calibration", {})
    refs = style.get("references", [])
    declared_static_assets = []
    if contract.get("reference_source", {}).get("kind") == "static_images":
        source_path = project / contract.get("deliverables", {}).get("source_manifest", "")
        declared_static_assets = json.loads(source_path.read_text(encoding="utf-8")).get("assets", [])
    ref_ids, ref_hashes = set(), set()
    for ref in refs:
        asset(ref, "style reference", picture=True)
        if not ref.get("id") or ref["id"] in ref_ids:
            errors.append("creative_review: style reference id missing or duplicated")
        ref_ids.add(ref.get("id"))
        ref_hashes.add(ref.get("sha256"))
        if ref.get("role") not in {"style_only", "layout_reference", "character_identity", "product_fact"}:
            errors.append("creative_review: explicit reference role required")
        require(ref.get("observation"), "style reference observation")
        if contract.get("reference_source", {}).get("kind") == "static_images" and ref.get("role") == "style_only":
            if not any(all(ref.get(key) == item.get(key) for key in ("id", "file", "sha256")) for item in declared_static_assets):
                errors.append("creative_review: style reference must match the declared static source asset identity")
    if not any(ref.get("role") == "style_only" for ref in refs):
        errors.append("creative_review: actual style_only reference required")
    axes = style.get("source_axes", {})
    for axis in AXES:
        require(axes.get(axis), f"source_axes.{axis}")
    require(style.get("originality_plan"), "originality_plan")
    fallback = style.get("manual_observation_fallback")
    fallback_ids, fallback_brief = set(), None
    if fallback is not None:
        if not isinstance(fallback, dict):
            errors.append("creative_review: manual_observation_fallback must be an object")
            fallback = {}
        require(fallback.get("reason"), "manual_observation_fallback.reason")
        fallback_ids = set(fallback.get("source_reference_ids", []))
        if not fallback_ids or not fallback_ids <= ref_ids:
            errors.append("creative_review: manual fallback needs declared source style reference ids")
        if any(not any(ref.get("id") == ref_id and ref.get("role") == "style_only" for ref in refs)
               for ref_id in fallback_ids):
            errors.append("creative_review: manual fallback may only observe declared style_only references")
        failure_path = asset(fallback.get("failure_evidence"), "manual fallback failure_evidence")
        if failure_path:
            failure_record = json.loads(failure_path.read_text(encoding="utf-8"))
            failed_attempts = [attempt for attempt in failure_record.get("attempts", [])
                               if attempt.get("status") == "failed"
                               and attempt.get("output_received") is False
                               and isinstance(attempt.get("error"), str) and attempt["error"].strip()]
            if len(failed_attempts) < 2:
                errors.append("creative_review: manual fallback needs at least two failed no-output source-input attempts")
        fallback_brief = fallback.get("manual_style_brief")
        asset(fallback_brief, "manual fallback manual_style_brief")
    if stage != "pre-visual":
        reviewer = style.get("reviewer", {})
        if reviewer.get("kind") not in {"independent_agent", "human"}:
            errors.append("creative_review: style requires an independent visual reviewer")
        require(reviewer.get("name"), "style reviewer.name")
        require(reviewer.get("asset_author"), "style reviewer.asset_author")
        if reviewer.get("name") == reviewer.get("asset_author"):
            errors.append("creative_review: style author cannot approve their own assets")
        require(reviewer.get("comparison_method"), "style reviewer.comparison_method")
        proofs = style.get("proofs", [])
        hashes = [proof.get("sha256") for proof in proofs]
        if len(hashes) != len(set(hashes)):
            errors.append("creative_review: independent calibration proof images cannot share the same SHA")
        if not {"master_scene", "character_detail"} <= {p.get("role") for p in proofs}:
            errors.append("creative_review: master_scene and character_detail proof images required")
        for proof in proofs:
            asset(proof, "style proof", picture=True)
            if proof.get("sha256") in ref_hashes:
                errors.append("creative_review: original reference cannot masquerade as new proof")
            used = proof.get("generation_reference_ids", [])
            if fallback is None:
                if not used or not set(used) <= ref_ids:
                    errors.append("creative_review: proof must record actual generation references")
                if not any(ref.get("id") in used and ref.get("role") == "style_only" for ref in refs):
                    errors.append("creative_review: proof generation omitted the style reference")
            elif used:
                errors.append("creative_review: manual fallback cannot claim direct source inputs")
            record_path = asset(proof.get("generation_evidence"), "proof generation_evidence")
            if record_path:
                record = json.loads(record_path.read_text(encoding="utf-8"))
                require(record.get("tool_call_id"), "generation tool_call_id")
                recorded_inputs = record.get("input_assets", [])
                if fallback is None:
                    for source in refs:
                        if source.get("id") in used and not any(
                            item.get("file") == source.get("file") and item.get("sha256") == source.get("sha256")
                            for item in recorded_inputs
                        ):
                            errors.append("creative_review: generation evidence omitted the claimed source input")
                else:
                    if record.get("input_mode") != "manual_observation_fallback":
                        errors.append("creative_review: manual fallback proof must name its input mode")
                    if recorded_inputs:
                        errors.append("creative_review: manual fallback evidence cannot claim source input_assets")
                    if set(record.get("manual_reference_ids", [])) != fallback_ids:
                        errors.append("creative_review: manual fallback evidence must bind the observed source ids")
                    if record.get("manual_style_brief") != fallback_brief:
                        errors.append("creative_review: manual fallback evidence must bind the approved style brief")
                output = record.get("output_asset", {})
                if output.get("file") != proof.get("file") or output.get("sha256") != proof.get("sha256"):
                    errors.append("creative_review: generation evidence does not bind the proof output")
            comparisons = proof.get("comparisons", {})
            for axis in AXES:
                item = comparisons.get(axis, {})
                require(item.get("source_observation"), f"proof.{axis}.source_observation")
                require(item.get("candidate_observation"), f"proof.{axis}.candidate_observation")
                if item.get("verdict") != "pass":
                    errors.append(f"creative_review: style proof {axis} not approved")
        if style.get("decision") != "approved":
            errors.append("creative_review: style calibration not approved")
        production_files = {file for clip in contract.get("clips", []) for file in clip.get("storyboard_files", [])}
        character_file = contract.get("deliverables", {}).get("character_sheet")
        if character_file:
            production_files.add(character_file)
        reviews = style.get("production_asset_reviews", [])
        reviewed_files = [item.get("file") for item in reviews]
        if len(reviewed_files) != len(set(reviewed_files)):
            errors.append("creative_review: duplicate production asset review")
        if set(reviewed_files) != production_files:
            errors.append("creative_review: style production_asset_reviews must cover every actual character and storyboard input")
        for item in reviews:
            asset(item, "production style asset", picture=True)
            require(item.get("identity_and_state_observation"), "production style asset identity_and_state_observation")
            if item.get("identity_and_state_verdict") != "pass":
                errors.append("creative_review: production asset identity or story state not approved")
            for axis in AXES:
                comparison = item.get("comparisons", {}).get(axis, {})
                require(comparison.get("source_observation"), f"production style asset.{axis}.source_observation")
                require(comparison.get("candidate_observation"), f"production style asset.{axis}.candidate_observation")
                if comparison.get("verdict") != "pass":
                    errors.append(f"creative_review: production style asset {item.get('file')} {axis} not approved")
    return {"status": "failed" if errors else "ok", "errors": errors,
            "warnings": ["Evidence checks do not judge beauty, verify editor honesty, or predict retention."],
            "bound_inputs": inputs}
