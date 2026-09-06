#!/usr/bin/env python3
"""Validate deterministic invariants of a viral-video replica package."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from PIL import Image


CONTRACT_FILE = "08_replica_contract.json"
ALLOWED_MODES = {"高保真视觉复刻", "爆款机制迁移", "商业混合复刻"}
SUPPORTED_SCHEMA_VERSIONS = {3, 4, 5}
MAX_AITABLE_ATTACHMENTS = 9
CREATIVE_SCORE_LIMITS = {
    "hook": 20,
    "causality": 25,
    "novelty": 20,
    "product_causality": 15,
    "reference_mechanism_fidelity": 10,
    "generatability": 10,
}
DELIVERY_MODE_SPEECH_LIMITS = {
    "dialogue_drama": 0.60,
    "montage_voiceover": 0.75,
    "poetic_narration": 0.92,
    "silent_or_music": 0.0,
}
LEGACY_REQUIRED_FILES = [
    "00_source_manifest.json",
    "01_reference_analysis.md",
    "02_product_facts.md",
    "03_structure_mapping.md",
    "04_script_30s.md",
    "05_seedance_prompts.md",
    "06_pre_generation_qc.md",
    "character/character_sheet.png",
]


def png_size(path: Path) -> tuple[int, int]:
    with Image.open(path) as image:
        if image.format != "PNG":
            raise ValueError("not a PNG file")
        image.verify()
    with Image.open(path) as image:
        image.load()
        return image.size


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path, errors: list[str], label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"{label} is not valid JSON: {exc}")
        return {}
    if not isinstance(value, dict):
        errors.append(f"{label} must contain a JSON object")
        return {}
    return value


def required_path(project: Path, relative: object, errors: list[str], label: str) -> Path | None:
    if not isinstance(relative, str) or not relative.strip():
        errors.append(f"missing {label} path")
        return None
    path = (project / relative).resolve()
    try:
        path.relative_to(project.resolve())
    except ValueError:
        errors.append(f"{label} escapes project directory: {relative}")
        return None
    if not path.is_file():
        errors.append(f"missing {label}: {relative}")
        return None
    return path


def read_text(path: Path | None) -> str:
    return path.read_text(encoding="utf-8", errors="ignore") if path and path.is_file() else ""


def planned_path(project: Path, relative: object, errors: list[str], label: str) -> Path | None:
    """Check an ungenerated asset declaration without pretending the asset exists."""
    if not isinstance(relative, str) or not relative.strip():
        errors.append(f"missing {label} path")
        return None
    if Path(relative).is_absolute():
        errors.append(f"{label} must be a relative project path")
        return None
    path = (project / relative).resolve()
    try:
        path.relative_to(project.resolve())
    except ValueError:
        errors.append(f"{label} escapes project directory: {relative}")
        return None
    if path.is_dir():
        errors.append(f"{label} names a directory: {relative}")
        return None
    return path


def normalize_phrase(text: str) -> str:
    return re.sub(r"[^0-9a-z\u3400-\u9fff]+", "", text.lower())


def prompt_section(text: str, marker: object) -> str:
    if not isinstance(marker, str) or not marker:
        return text
    start = text.find(marker)
    if start < 0:
        return text
    following = re.search(r"^##\s+Clip\b", text[start + len(marker) :], flags=re.MULTILINE | re.IGNORECASE)
    end = start + len(marker) + following.start() if following else len(text)
    return text[start:end]


def as_float(value: object, errors: list[str], label: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        errors.append(f"{label} must be a number")
        return None


def validate_png(path: Path, errors: list[str]) -> None:
    try:
        width, height = png_size(path)
    except (OSError, ValueError, SyntaxError) as exc:
        errors.append(f"{path.name}: {exc}")
        return
    if abs(width / height - 9 / 16) > 0.015:
        errors.append(f"{path.name}: {width}x{height} is not 9:16")


def validate_production_design(
    project: Path,
    contract: dict,
    paths: dict[str, Path | None],
    beats: list[dict],
    clip_by_id: dict[str, dict],
    prompt_texts: dict[str, str],
    storyboard_paths: dict[str, Path],
    errors: list[str],
    stage: str = "pre-generation",
) -> int:
    """Validate schema v4 product/style locks and one executable motion plan per beat."""

    design = contract.get("production_design")
    if not isinstance(design, dict):
        errors.append("production_design is required for schema v4")
        return 0

    visual_lock_text = read_text(paths.get("visual_lock"))
    product = design.get("product_identity")
    product_asset_names: set[str] = set()
    if not isinstance(product, dict):
        errors.append("production_design.product_identity must be an object")
    else:
        locked_features = product.get("locked_features")
        if not isinstance(locked_features, dict):
            errors.append("production_design.product_identity.locked_features must be an object")
        else:
            for field in ("shape", "proportion", "color", "material", "structure", "logo"):
                value = locked_features.get(field)
                if not isinstance(value, str) or not value.strip():
                    errors.append(f"production_design.product_identity.locked_features.{field} is required")
        if product.get("unknown_view_policy") != "do_not_invent":
            errors.append("production_design.product_identity.unknown_view_policy must be do_not_invent")
        assets = product.get("reference_assets")
        if not isinstance(assets, list) or not assets:
            errors.append("production_design.product_identity.reference_assets must be a non-empty array")
            assets = []
        for index, asset in enumerate(assets):
            label = f"production_design.product_identity.reference_assets[{index}]"
            if not isinstance(asset, dict):
                errors.append(f"{label} must be an object")
                continue
            path = required_path(project, asset.get("file"), errors, f"{label}.file")
            expected_hash = asset.get("sha256")
            if not isinstance(expected_hash, str) or not expected_hash:
                errors.append(f"{label}.sha256 is required")
            elif path and file_hash(path) != expected_hash:
                errors.append(f"{label}.sha256 does not match the product reference asset")
            if not isinstance(asset.get("role"), str) or not asset.get("role", "").strip():
                errors.append(f"{label}.role is required")
            if path:
                try:
                    with Image.open(path) as image:
                        image.load()
                except (OSError, ValueError, SyntaxError) as exc:
                    errors.append(f"{label} product reference is not a decodable image: {exc}")
                product_asset_names.add(path.name)

    visual_style = design.get("visual_style")
    style_lock_id = ""
    reusable_prompt = ""
    if not isinstance(visual_style, dict):
        errors.append("production_design.visual_style must be an object")
    else:
        style_lock_id = str(visual_style.get("lock_id", "")).strip()
        reusable_prompt = str(visual_style.get("reusable_prompt", "")).strip()
        for field in (
            "lock_id",
            "lighting",
            "color_palette",
            "composition",
            "lens_and_camera",
            "character_rules",
            "environment_rules",
            "image_texture",
            "reusable_prompt",
        ):
            value = visual_style.get(field)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"production_design.visual_style.{field} is required")
        negative = visual_style.get("negative_style_constraints")
        if not isinstance(negative, list):
            errors.append("production_design.visual_style.negative_style_constraints must be an array")
        if style_lock_id and style_lock_id not in visual_lock_text:
            errors.append("production_design.visual_style.lock_id is missing from the visual lock deliverable")
        if reusable_prompt and normalize_phrase(reusable_prompt) not in normalize_phrase(visual_lock_text):
            errors.append("production_design.visual_style.reusable_prompt is missing from the visual lock deliverable")

    for clip_id, prompt_text in prompt_texts.items():
        if stage == "pre-visual" and not prompt_text:
            continue
        if style_lock_id and style_lock_id not in prompt_text:
            errors.append(f"{clip_id} prompt must reference visual style lock_id: {style_lock_id}")
        if reusable_prompt and normalize_phrase(reusable_prompt) not in normalize_phrase(prompt_text):
            errors.append(f"{clip_id} prompt must include the reusable visual style prompt")

    motion_profile = design.get("motion_profile")
    if motion_profile not in {"reference_led", "narrative_drama", "continuous_motion_ad"}:
        errors.append(
            "production_design.motion_profile must be reference_led, narrative_drama, or continuous_motion_ad"
        )
    music = design.get("music_strategy")
    if not isinstance(music, dict) or music.get("status") not in {
        "source_locked",
        "user_confirmed",
        "pending_selection",
        "not_required",
    }:
        errors.append(
            "production_design.music_strategy.status must be source_locked, user_confirmed, pending_selection, or not_required"
        )
    elif music.get("status") in {"source_locked", "user_confirmed"}:
        required_path(
            project,
            music.get("source_file"),
            errors,
            "production_design.music_strategy.source_file",
        )
    brief_alignment = contract.get("brief_alignment")
    production_scope = brief_alignment.get("production_scope") if isinstance(brief_alignment, dict) else None
    if production_scope == "full_video" and isinstance(music, dict):
        if music.get("status") not in {"source_locked", "user_confirmed"}:
            errors.append("full_video production requires locked or user-confirmed music before generation")

    motion_beats = design.get("motion_beats")
    if not isinstance(motion_beats, list) or len(motion_beats) != len(beats):
        errors.append("production_design.motion_beats must contain exactly one entry per reference beat")
        motion_beats = []
    expected_by_prompt = {
        beat.get("prompt_id"): (beat.get("clip_id"), beat.get("script_id"))
        for beat in beats
        if isinstance(beat, dict)
    }
    seen_prompt_ids: set[str] = set()
    previous_handoff = "START"
    dynamic_levels: list[int] = []
    motion_fields = (
        "start_state",
        "character_action",
        "product_action",
        "environment_reaction",
        "camera_motion",
        "speed_change",
        "end_state",
        "transition_trigger",
        "music_cue",
    )
    for index, motion in enumerate(motion_beats):
        label = f"production_design.motion_beats[{index}]"
        if not isinstance(motion, dict):
            errors.append(f"{label} must be an object")
            continue
        prompt_id = motion.get("prompt_id")
        clip_id = motion.get("clip_id")
        script_id = motion.get("script_id")
        expected = expected_by_prompt.get(prompt_id)
        if expected is None or prompt_id in seen_prompt_ids:
            errors.append(f"{label}.prompt_id must name one unique reference beat prompt_id")
        else:
            seen_prompt_ids.add(str(prompt_id))
            if expected != (clip_id, script_id):
                errors.append(f"{label} clip_id/script_id must match its reference beat")
        if clip_id not in clip_by_id:
            errors.append(f"{label}.clip_id is unknown: {clip_id}")
        product_visibility = motion.get("product_visibility")
        if product_visibility not in {"visible", "withheld_for_reveal"}:
            errors.append(f"{label}.product_visibility must be visible or withheld_for_reveal")
        elif product_visibility == "visible":
            prompt_text = prompt_texts.get(str(clip_id), "")
            if (stage != "pre-visual" or prompt_text) and product_asset_names and not any(name in prompt_text for name in product_asset_names):
                errors.append(f"{label} visible product must reference a locked product asset filename in its prompt")
        for field in motion_fields:
            value = motion.get(field)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{label}.{field} is required")
        handoff_in = motion.get("handoff_in")
        handoff_out = motion.get("handoff_out")
        if handoff_in != previous_handoff:
            errors.append(f"{label}.handoff_in must equal the previous motion beat handoff_out")
        if not isinstance(handoff_out, str) or not handoff_out.strip():
            errors.append(f"{label}.handoff_out is required")
        else:
            previous_handoff = handoff_out
        intent = motion.get("motion_intent")
        if intent not in {"dynamic", "intentional_stillness"}:
            errors.append(f"{label}.motion_intent must be dynamic or intentional_stillness")
        elif intent == "dynamic" and motion.get("camera_removal_still_dynamic") is not True:
            errors.append(f"{label} is camera-only motion; character/environment must remain dynamic without camera movement")
        elif intent == "intentional_stillness":
            reason = motion.get("stillness_reason")
            if not isinstance(reason, str) or not reason.strip():
                errors.append(f"{label}.stillness_reason is required for intentional_stillness")
        level = motion.get("motion_level")
        if not isinstance(level, int) or isinstance(level, bool) or not 0 <= level <= 5:
            errors.append(f"{label}.motion_level must be an integer from 0 to 5")
        elif intent == "dynamic":
            dynamic_levels.append(level)
        complex_action = motion.get("complex_action")
        if not isinstance(complex_action, bool):
            errors.append(f"{label}.complex_action must be true or false")
        keyframes = motion.get("keyframe_files", [])
        if not isinstance(keyframes, list):
            errors.append(f"{label}.keyframe_files must be an array")
            keyframes = []
        if complex_action and len(keyframes) < 3:
            errors.append(f"{label} complex action requires start, middle, and end keyframes")
        for relative in keyframes:
            if relative not in storyboard_paths:
                errors.append(f"{label} keyframe is not declared by a clip: {relative}")
    if motion_beats and previous_handoff != "END":
        errors.append("the final production_design.motion_beats handoff_out must be END")
    if motion_profile == "continuous_motion_ad":
        if len(dynamic_levels) < 3 or len(set(dynamic_levels)) < 3 or max(dynamic_levels, default=0) < 4:
            errors.append("continuous_motion_ad requires at least three dynamic beats with three escalating motion levels reaching 4")
    return len(motion_beats)


def validate_static_source(project: Path, source: dict, contract: dict, errors: list[str]) -> set[str]:
    """Validate static evidence itself, never invent video timing for illustrations."""
    if source.get("source_type") != "static_images":
        errors.append("static source manifest.source_type must be static_images")
    reference_source = contract.get("reference_source")
    if not isinstance(reference_source, dict) or reference_source.get("kind") != "static_images":
        errors.append("reference_source.kind must be static_images for a static source")
    if "duration_seconds" not in source or source.get("duration_seconds") is not None:
        errors.append("static source duration_seconds must be null")
    if source.get("audio_present") is not False:
        errors.append("static source audio_present must be false")
    for key in ("timeline_manifest", "interval_seconds", "frame_count", "last_timestamp_seconds"):
        if source.get(key) is not None:
            errors.append(f"static source must not declare video field {key}")
    if contract.get("deliverables", {}).get("timeline_manifest"):
        errors.append("static source must not declare a video timeline_manifest")
    review = contract.get("evidence_review", {})
    if not isinstance(review, dict):
        errors.append("static evidence_review must be an object")
        review = {}
    for key in ("fixed_timeline_manual_reviewed", "reviewed_frame_count", "reviewed_last_timestamp_seconds"):
        if review.get(key) is not None:
            errors.append(f"static evidence_review must not declare video field {key}")
    assets = source.get("assets")
    if not isinstance(assets, list) or not assets:
        errors.append("static source assets must be a non-empty array")
        assets = []
    assets_by_id: dict[str, dict] = {}
    for index, asset in enumerate(assets):
        label = f"static source assets[{index}]"
        if not isinstance(asset, dict):
            errors.append(f"{label} must be an object")
            continue
        asset_id = asset.get("id")
        if not isinstance(asset_id, str) or not asset_id.strip() or asset_id in assets_by_id:
            errors.append(f"{label}.id must be unique and non-empty")
        else:
            assets_by_id[asset_id] = asset
        if asset.get("role") not in {"scene", "style_detail", "character_detail"}:
            errors.append(f"{label}.role must be scene, style_detail, or character_detail")
        path = required_path(project, asset.get("file"), errors, f"{label}.file")
        digest = asset.get("sha256")
        if not isinstance(digest, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", digest):
            errors.append(f"{label}.sha256 must be a SHA-256 digest")
        elif path and file_hash(path).lower() != digest.lower():
            errors.append(f"{label}.sha256 does not match the static source asset")
        if path:
            try:
                with Image.open(path) as image:
                    image.load()
            except (OSError, ValueError, SyntaxError) as exc:
                errors.append(f"{label} is not a decodable image: {exc}")
    review_path = required_path(project, review.get("static_review_file"), errors, "static review file")
    data = load_json(review_path, errors, "static review file") if review_path else {}
    observations = data.get("assets")
    if not isinstance(observations, list):
        errors.append("static review assets must be an array")
        observations = []
    reviewed_ids: set[str] = set()
    for index, item in enumerate(observations):
        label = f"static review assets[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{label} must be an object")
            continue
        asset_id = item.get("id")
        if not isinstance(asset_id, str) or asset_id not in assets_by_id or asset_id in reviewed_ids:
            errors.append(f"{label}.id must name one unique static source asset")
        else:
            reviewed_ids.add(asset_id)
            if item.get("source_sha256") != assets_by_id[asset_id].get("sha256"):
                errors.append(f"{label}.source_sha256 does not match its source asset")
        if not isinstance(item.get("observation"), str) or not item.get("observation", "").strip():
            errors.append(f"{label}.observation must contain a concrete source observation")
    if reviewed_ids != set(assets_by_id):
        errors.append("static review must cover every source asset exactly once")
    return set(assets_by_id)


def validate_contract(project: Path, contract: dict, stage: str = "pre-generation") -> dict:
    errors: list[str] = []
    warnings: list[str] = []

    schema_version = contract.get("schema_version")
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        errors.append("08_replica_contract.json schema_version must be 3, 4, or 5")
    elif schema_version == 3:
        warnings.append("schema v3 remains readable but does not enforce product/style locks or executable motion chains")
    mode = contract.get("mode")
    if mode not in ALLOWED_MODES:
        errors.append("mode must be exactly one supported replica mode")

    brief_alignment = contract.get("brief_alignment")
    if not isinstance(brief_alignment, dict):
        errors.append("brief_alignment is required; lock the requested mode and duration before analysis")
    else:
        requested_mode = brief_alignment.get("requested_mode")
        resolved_mode = brief_alignment.get("resolved_mode")
        if requested_mode not in ALLOWED_MODES:
            errors.append("brief_alignment.requested_mode must be one supported replica mode")
        if resolved_mode != mode:
            errors.append("brief_alignment.resolved_mode must equal mode")
        if requested_mode in ALLOWED_MODES and resolved_mode in ALLOWED_MODES and requested_mode != resolved_mode:
            if brief_alignment.get("mode_change_user_confirmed") is not True:
                errors.append("replica mode changed from the user brief without explicit user confirmation")
            reason = brief_alignment.get("mode_change_reason")
            if not isinstance(reason, str) or not reason.strip():
                errors.append("brief_alignment.mode_change_reason is required when the replica mode changes")
        if not isinstance(brief_alignment.get("ai_table_requested"), bool):
            errors.append("brief_alignment.ai_table_requested must be true or false")
        if schema_version in {4, 5} and brief_alignment.get("production_scope") not in {
            "package_only",
            "ai_table_handoff",
            "full_video",
        }:
            errors.append(
                "brief_alignment.production_scope must be package_only, ai_table_handoff, or full_video for schema v4"
            )

    deliverables = contract.get("deliverables")
    if not isinstance(deliverables, dict):
        errors.append("deliverables must be an object")
        deliverables = {}
    source_manifest_path = required_path(
        project,
        deliverables.get("source_manifest"),
        errors,
        "deliverable source_manifest",
    )
    source_manifest = (
        load_json(source_manifest_path, errors, "source manifest")
        if source_manifest_path
        else {}
    )
    historical_vector_mode = (
        mode == "爆款机制迁移"
        and source_manifest.get("source_type") == "historical_vector_library"
    )
    reference_source = contract.get("reference_source", {})
    static_mode = schema_version == 5 and (
        source_manifest.get("source_type") == "static_images"
        or isinstance(reference_source, dict) and reference_source.get("kind") == "static_images"
    )
    static_asset_ids = validate_static_source(project, source_manifest, contract, errors) if static_mode else set()
    asset_path = planned_path if stage == "pre-visual" else required_path
    paths: dict[str, Path | None] = {
        name: required_path(project, deliverables.get(name), errors, f"deliverable {name}")
        for name in (
            "analysis",
            "facts",
            "mapping",
            "script",
            "qc",
        )
    }
    paths["character_sheet"] = asset_path(project, deliverables.get("character_sheet"), errors, "deliverable character_sheet")
    if schema_version == 5 and paths["facts"] and not read_text(paths["facts"]).strip():
        errors.append("product facts must contain sourced facts and explicit unknowns, not an empty file")
    if schema_version in {4, 5}:
        paths["visual_lock"] = required_path(
            project,
            deliverables.get("visual_lock"),
            errors,
            "deliverable visual_lock",
        )
    paths["source_manifest"] = source_manifest_path
    paths["timeline_manifest"] = (
        None
        if static_mode or historical_vector_mode and not deliverables.get("timeline_manifest")
        else required_path(
            project,
            deliverables.get("timeline_manifest"),
            errors,
            "deliverable timeline_manifest",
        )
    )
    mapping_text = read_text(paths["mapping"])
    script_text = read_text(paths["script"])
    analysis_text = read_text(paths["analysis"])
    character_sheet = paths["character_sheet"]
    if character_sheet and stage != "pre-visual":
        validate_png(character_sheet, errors)

    expected_sha = contract.get("source_sha256")
    if not isinstance(expected_sha, str) or not expected_sha:
        errors.append("source_sha256 is required")
    elif paths["source_manifest"]:
        if source_manifest.get("sha256") != expected_sha:
            errors.append("source_sha256 does not match source manifest")

    if historical_vector_mode:
        review = contract.get("evidence_review")
        if not isinstance(review, dict) or review.get("historical_evidence_reviewed") is not True:
            errors.append("evidence_review.historical_evidence_reviewed must be true for historical vector mode")
        else:
            required_path(
                project,
                review.get("historical_match_report"),
                errors,
                "historical match report",
            )

    timeline_manifest = (
        load_json(paths["timeline_manifest"], errors, "fixed timeline manifest")
        if paths["timeline_manifest"]
        else {}
    )
    if timeline_manifest:
        interval = as_float(timeline_manifest.get("interval_seconds"), errors, "timeline interval_seconds")
        frame_count = timeline_manifest.get("frame_count")
        if interval is not None and interval > 0.5 + 0.001:
            errors.append("fixed timeline interval must be 0.5s or denser")
        if not isinstance(frame_count, int) or frame_count < 1:
            errors.append("fixed timeline frame_count must be a positive integer")
        review = contract.get("evidence_review")
        if not isinstance(review, dict):
            errors.append("evidence_review must confirm the fixed timeline was inspected")
        else:
            if review.get("fixed_timeline_manual_reviewed") is not True:
                errors.append("evidence_review.fixed_timeline_manual_reviewed must be true")
            if isinstance(frame_count, int) and review.get("reviewed_frame_count") != frame_count:
                errors.append("evidence_review.reviewed_frame_count must equal fixed timeline frame_count")
            reviewed_last = as_float(
                review.get("reviewed_last_timestamp_seconds"),
                errors,
                "evidence_review.reviewed_last_timestamp_seconds",
            )
            timeline_last = as_float(
                timeline_manifest.get("last_timestamp_seconds"),
                errors,
                "timeline last_timestamp_seconds",
            )
            if reviewed_last is not None and timeline_last is not None and reviewed_last + 0.01 < timeline_last:
                errors.append("evidence review stops before the final fixed-timeline frame")

    target_duration = as_float(contract.get("target_duration_seconds"), errors, "target_duration_seconds")
    if isinstance(brief_alignment, dict):
        delegated_duration = schema_version == 5 and brief_alignment.get("duration_policy") == "user_delegated"
        if delegated_duration:
            requested_duration = None
            if brief_alignment.get("requested_duration_seconds") is not None:
                errors.append("user_delegated duration must not erase an explicit requested duration")
            if not isinstance(brief_alignment.get("duration_authority"), str) or not brief_alignment["duration_authority"].strip():
                errors.append("user_delegated duration requires the user's actual duration_authority instruction")
        else:
            requested_duration = as_float(
                brief_alignment.get("requested_duration_seconds"),
                errors,
                "brief_alignment.requested_duration_seconds",
            )
        if (
            requested_duration is not None
            and target_duration is not None
            and abs(requested_duration - target_duration) > 0.25
        ):
            if brief_alignment.get("duration_change_user_confirmed") is not True:
                errors.append("target duration changed from the user brief without explicit user confirmation")
            reason = brief_alignment.get("duration_change_reason")
            if not isinstance(reason, str) or not reason.strip():
                errors.append("brief_alignment.duration_change_reason is required when target duration changes")
    source_duration = None if static_mode else as_float(source_manifest.get("duration_seconds"), errors, "source duration_seconds")
    if (
        mode == "高保真视觉复刻"
        and target_duration is not None
        and source_duration is not None
        and abs(target_duration - source_duration) > 0.25
    ):
        errors.append(
            f"high-fidelity target duration {target_duration:.3f}s must match source duration {source_duration:.3f}s"
        )
    clips = contract.get("clips")
    if not isinstance(clips, list) or not clips:
        errors.append("clips must be a non-empty array")
        clips = []

    clip_ids: set[str] = set()
    clip_by_id: dict[str, dict] = {}
    storyboard_paths: dict[str, Path] = {}
    prompt_texts: dict[str, str] = {}
    previous_end = 0.0
    for index, clip in enumerate(clips, 1):
        label = f"clips[{index - 1}]"
        if not isinstance(clip, dict):
            errors.append(f"{label} must be an object")
            continue
        clip_id = clip.get("id")
        if not isinstance(clip_id, str) or not clip_id:
            errors.append(f"{label}.id is required")
            continue
        if clip_id in clip_ids:
            errors.append(f"duplicate clip id: {clip_id}")
        clip_ids.add(clip_id)
        clip_by_id[clip_id] = clip

        start = as_float(clip.get("start_seconds"), errors, f"{label}.start_seconds")
        end = as_float(clip.get("end_seconds"), errors, f"{label}.end_seconds")
        if start is not None and end is not None:
            duration = end - start
            if duration < 1 - 0.01 or duration > 15 + 0.01:
                errors.append(f"{clip_id} duration is {duration:.3f}s; allowed range is 1-15s")
            if abs(start - previous_end) > 0.05:
                errors.append(f"{clip_id} is not contiguous: starts at {start:.3f}s after {previous_end:.3f}s")
            if end <= start:
                errors.append(f"{clip_id} end_seconds must be greater than start_seconds")
            previous_end = end

        marker = clip.get("prompt_marker")
        prompt_path = asset_path(project, clip.get("prompt_file"), errors, f"{clip_id} prompt_file")
        full_prompt_text = read_text(prompt_path)
        prompt_texts[clip_id] = prompt_section(full_prompt_text, marker)
        if (stage != "pre-visual" or full_prompt_text) and isinstance(marker, str) and marker and marker not in full_prompt_text:
            errors.append(f"{clip_id} prompt marker not found: {marker}")

        files = clip.get("storyboard_files")
        if not isinstance(files, list) or not files:
            errors.append(f"{clip_id} storyboard_files must be a non-empty array")
            files = []
        if len(files) > 9:
            errors.append(f"{clip_id} has {len(files)} storyboard images; maximum is 9")
        for relative in files:
            path = asset_path(project, relative, errors, f"{clip_id} storyboard")
            if not path:
                continue
            if path.suffix.lower() != ".png":
                errors.append(f"{relative}: storyboard must be PNG")
                continue
            if stage != "pre-visual":
                validate_png(path, errors)
            storyboard_paths[str(relative)] = path
            if (stage != "pre-visual" or full_prompt_text) and path.name not in prompt_texts[clip_id]:
                errors.append(f"{clip_id} prompt does not reference storyboard filename: {path.name}")
        if (stage != "pre-visual" or full_prompt_text) and character_sheet and character_sheet.name not in prompt_texts[clip_id]:
            errors.append(f"{clip_id} prompt does not reference character sheet: {character_sheet.name}")

    if target_duration is not None and clips and abs(previous_end - target_duration) > 0.05:
        errors.append(
            f"clip coverage ends at {previous_end:.3f}s but target_duration_seconds is {target_duration:.3f}s"
        )

    continuities = contract.get("continuity", [])
    if not isinstance(continuities, list):
        errors.append("continuity must be an array")
        continuities = []
    for index, item in enumerate(continuities):
        if not isinstance(item, dict):
            errors.append(f"continuity[{index}] must be an object")
            continue
        from_clip_id = item.get("from_clip_id")
        to_clip_id = item.get("to_clip_id")
        if from_clip_id not in clip_by_id or to_clip_id not in clip_by_id:
            errors.append(f"continuity[{index}] must name declared from_clip_id and to_clip_id")
        tail = asset_path(project, item.get("tail_file"), errors, f"continuity[{index}] tail_file")
        head = asset_path(project, item.get("head_file"), errors, f"continuity[{index}] head_file")
        if stage != "pre-visual" and tail and head and file_hash(tail) != file_hash(head):
            errors.append(f"continuity anchor differs: {tail.name} != {head.name}")

    beats = contract.get("reference_beats")
    if not isinstance(beats, list) or not beats:
        errors.append("reference_beats must be a non-empty array")
        beats = []
    beat_reference_ids: set[str] = set()
    beat_script_ids: set[str] = set()
    beat_prompt_ids: set[str] = set()
    previous_source_start = -1.0
    previous_target_start = -1.0
    previous_source_end = 0.0
    previous_target_end = 0.0
    first_source_start: float | None = None
    first_target_start: float | None = None
    last_source_end: float | None = None
    last_target_end: float | None = None
    beat_counts_by_clip: dict[str, int] = {}
    for index, beat in enumerate(beats):
        label = f"reference_beats[{index}]"
        if not isinstance(beat, dict):
            errors.append(f"{label} must be an object")
            continue
        reference_id = beat.get("reference_id")
        script_id = beat.get("script_id")
        prompt_id = beat.get("prompt_id")
        clip_id = beat.get("clip_id")
        storyboard_file = beat.get("storyboard_file")
        for value, seen, field in (
            (reference_id, beat_reference_ids, "reference_id"),
            (script_id, beat_script_ids, "script_id"),
            (prompt_id, beat_prompt_ids, "prompt_id"),
        ):
            if not isinstance(value, str) or not value:
                errors.append(f"{label}.{field} is required")
            elif value in seen:
                errors.append(f"duplicate {field}: {value}")
            else:
                seen.add(value)
        if isinstance(reference_id, str) and reference_id and reference_id not in analysis_text:
            errors.append(f"{label} missing {reference_id} in analysis beat ledger")
        if clip_id not in clip_by_id:
            errors.append(f"{label}.clip_id is unknown: {clip_id}")
            prompt_text = ""
        else:
            prompt_text = prompt_texts.get(str(clip_id), "")
            beat_counts_by_clip[str(clip_id)] = beat_counts_by_clip.get(str(clip_id), 0) + 1
        if storyboard_file not in storyboard_paths:
            errors.append(f"{label}.storyboard_file is not declared by its clip: {storyboard_file}")

        if static_mode:
            for field in ("source_start_seconds", "source_end_seconds"):
                if field not in beat or beat.get(field) is not None:
                    errors.append(f"{label}.{field} must be null for static source evidence")
            source_ids = beat.get("source_asset_ids")
            if not isinstance(source_ids, list) or not source_ids or any(not isinstance(value, str) or value not in static_asset_ids for value in source_ids):
                errors.append(f"{label}.source_asset_ids must reference real static source assets")
            source_start = None
        else:
            source_start = as_float(beat.get("source_start_seconds"), errors, f"{label}.source_start_seconds")
        target_start = as_float(beat.get("target_start_seconds"), errors, f"{label}.target_start_seconds")
        if source_start is not None:
            if source_start < previous_source_start:
                errors.append(f"{label} source order regresses")
            previous_source_start = source_start
        if target_start is not None:
            if target_start < previous_target_start:
                errors.append(f"{label} target order regresses")
            previous_target_start = target_start

        if mode == "高保真视觉复刻" or static_mode:
            source_end = None if static_mode else as_float(beat.get("source_end_seconds"), errors, f"{label}.source_end_seconds")
            target_end = as_float(beat.get("target_end_seconds"), errors, f"{label}.target_end_seconds")
            if source_start is not None:
                if first_source_start is None:
                    first_source_start = source_start
                if abs(source_start - previous_source_end) > 0.25:
                    errors.append(f"{label} leaves a source timeline gap after {previous_source_end:.3f}s")
            if target_start is not None:
                if first_target_start is None:
                    first_target_start = target_start
                if abs(target_start - previous_target_end) > 0.25:
                    errors.append(f"{label} leaves a target timeline gap after {previous_target_end:.3f}s")
            if source_start is not None and source_end is not None:
                if source_end <= source_start:
                    errors.append(f"{label}.source_end_seconds must be greater than source_start_seconds")
                previous_source_end = source_end
                last_source_end = source_end
            if target_start is not None and target_end is not None:
                if target_end <= target_start:
                    errors.append(f"{label}.target_end_seconds must be greater than target_start_seconds")
                previous_target_end = target_end
                last_target_end = target_end
                clip = clip_by_id.get(str(clip_id))
                if clip:
                    clip_start = float(clip.get("start_seconds", 0))
                    clip_end = float(clip.get("end_seconds", 0))
                    if target_start < clip_start - 0.01 or target_end > clip_end + 0.01:
                        errors.append(f"{label} target interval is outside {clip_id}")

        for value, text, where in (
            (reference_id, mapping_text, "mapping"),
            (script_id, mapping_text, "mapping"),
            (prompt_id, mapping_text, "mapping"),
            (script_id, script_text, "script"),
            (prompt_id, prompt_text, "prompt"),
            (Path(str(storyboard_file)).name, mapping_text, "mapping"),
            (Path(str(storyboard_file)).name, prompt_text, "prompt"),
        ):
            if stage == "pre-visual" and where == "prompt" and not text:
                continue
            if isinstance(value, str) and value and value not in text:
                errors.append(f"{label} missing {value} in {where}")
        terms = beat.get("required_terms", [])
        if not isinstance(terms, list):
            errors.append(f"{label}.required_terms must be an array")
            terms = []
        for term in terms:
            if not isinstance(term, str) or not term:
                errors.append(f"{label}.required_terms contains an invalid value")
            elif term not in script_text or (stage != "pre-visual" or prompt_text) and term not in prompt_text:
                errors.append(f"{label} required term missing from script or prompt: {term}")

    analysis_ids = set(re.findall(r"\bR\d{2,}\b", analysis_text))
    missing_beats = sorted(analysis_ids - beat_reference_ids)
    if missing_beats:
        errors.append("reference beat ledger is not fully mapped: " + ", ".join(missing_beats))

    if (mode == "高保真视觉复刻" or static_mode) and beats:
        if first_source_start is not None and first_source_start > 0.05:
            errors.append("high-fidelity beat ledger must start at source 0s")
        if first_target_start is not None and first_target_start > 0.05:
            errors.append("high-fidelity beat ledger must start at target 0s")
        if source_duration is not None and last_source_end is not None and abs(last_source_end - source_duration) > 0.25:
            errors.append(
                f"high-fidelity source beat coverage ends at {last_source_end:.3f}s, not {source_duration:.3f}s"
            )
        if target_duration is not None and last_target_end is not None and abs(last_target_end - target_duration) > 0.25:
            errors.append(
                f"high-fidelity target beat coverage ends at {last_target_end:.3f}s, not {target_duration:.3f}s"
            )
        overloaded = sorted(clip_id for clip_id, count in beat_counts_by_clip.items() if count > 3) if mode == "高保真视觉复刻" else []
        if overloaded:
            errors.append(
                "high-fidelity clips contain more than 3 causal beats and must be split: " + ", ".join(overloaded)
            )

    motion_beat_count = 0
    if schema_version in {4, 5}:
        motion_beat_count = validate_production_design(
            project,
            contract,
            paths,
            beats,
            clip_by_id,
            prompt_texts,
            storyboard_paths,
            errors,
            stage=stage,
        )

    audio_assets = contract.get("audio_assets", [])
    if not isinstance(audio_assets, list):
        errors.append("audio_assets must be an array")
        audio_assets = []
    audio_by_clip: dict[str, list[str]] = {}
    for index, asset in enumerate(audio_assets):
        label = f"audio_assets[{index}]"
        if not isinstance(asset, dict):
            errors.append(f"{label} must be an object")
            continue
        path = required_path(project, asset.get("file"), errors, f"{label}.file")
        clip_id = asset.get("clip_id")
        if clip_id not in clip_by_id:
            errors.append(f"{label}.clip_id is unknown: {clip_id}")
            continue
        prompt_text = prompt_texts.get(str(clip_id), "")
        if path:
            audio_by_clip.setdefault(str(clip_id), []).append(path.name)
            if (stage != "pre-visual" or prompt_text) and path.name not in prompt_text:
                errors.append(f"{clip_id} prompt does not reference audio filename: {path.name}")
            if (stage != "pre-visual" or prompt_text) and mode == "高保真视觉复刻" and "不换其他音乐" not in prompt_text:
                errors.append(f"{clip_id} prompt must say 不换其他音乐 when reference audio is attached")
        use_start = as_float(asset.get("use_start_seconds"), errors, f"{label}.use_start_seconds")
        use_end = as_float(asset.get("use_end_seconds"), errors, f"{label}.use_end_seconds")
        clip = clip_by_id[str(clip_id)]
        clip_start = float(clip.get("start_seconds", 0))
        clip_end = float(clip.get("end_seconds", 0))
        if use_start is not None and use_end is not None:
            if use_start < clip_start - 0.01 or use_end > clip_end + 0.01 or use_end <= use_start:
                errors.append(f"{label} use interval is outside {clip_id}")
        if mode == "高保真视觉复刻":
            source_start = as_float(
                asset.get("source_start_seconds"), errors, f"{label}.source_start_seconds"
            )
            source_end = as_float(asset.get("source_end_seconds"), errors, f"{label}.source_end_seconds")
            if source_start is not None and source_end is not None and source_end <= source_start:
                errors.append(f"{label} source interval is invalid")
            if asset.get("must_use_original_mix") is not True:
                errors.append(f"{label}.must_use_original_mix must be true for high-fidelity input audio")

    if mode == "高保真视觉复刻":
        original_audio_claim = re.compile(r"原片[^\n]{0,12}(?:BGM|音乐|音效)|同段BGM", re.IGNORECASE)
        for clip_id, prompt_text in prompt_texts.items():
            if original_audio_claim.search(prompt_text) and not audio_by_clip.get(clip_id):
                errors.append(f"{clip_id} claims original music/effects but declares no audio asset")

    visual_text = contract.get("visual_text_requirements", [])
    if not isinstance(visual_text, list):
        errors.append("visual_text_requirements must be an array")
        visual_text = []
    for index, requirement in enumerate(visual_text):
        label = f"visual_text_requirements[{index}]"
        if not isinstance(requirement, dict):
            errors.append(f"{label} must be an object")
            continue
        file_name = requirement.get("storyboard_file")
        exact_text = requirement.get("exact_text")
        clip_id = requirement.get("clip_id")
        if file_name not in storyboard_paths:
            errors.append(f"{label}.storyboard_file is not declared: {file_name}")
        if clip_id not in prompt_texts:
            errors.append(f"{label}.clip_id is unknown: {clip_id}")
            continue
        prompt_text = prompt_texts[str(clip_id)]
        if not isinstance(exact_text, str) or not exact_text:
            errors.append(f"{label}.exact_text is required")
        elif (stage != "pre-visual" or prompt_text) and exact_text not in prompt_text:
            errors.append(f"{label} exact text is missing from prompt: {exact_text}")
        if isinstance(exact_text, str) and exact_text:
            generic_no_text = re.search(r"(?:画面)?无(?:任何|可读)?文字|禁止(?:任何|可读)?文字", prompt_text)
            whitelist_exception = re.search(rf"除[^\n]{{0,20}}{re.escape(exact_text)}[^\n]{{0,20}}外", prompt_text)
            if generic_no_text and not whitelist_exception:
                errors.append(f"{label} conflicts with a generic no-text prompt; add an explicit whitelist exception")
        if stage != "pre-visual" and requirement.get("manual_visual_verified") is not True:
            errors.append(f"{label} must set manual_visual_verified=true after inspecting the image")

    handoff = contract.get("aitable_handoff")
    if (
        isinstance(brief_alignment, dict)
        and brief_alignment.get("ai_table_requested") is True
        and handoff is None
        and not (schema_version == 5 and stage == "pre-visual")
    ):
        errors.append("AI table delivery was requested but aitable_handoff is missing")
    if handoff is not None:
        if not isinstance(handoff, dict):
            errors.append("aitable_handoff must be an object")
        else:
            protected = set(handoff.get("protected_field_ids", []))
            if not protected:
                errors.append("aitable_handoff.protected_field_ids must include auto/video result fields")
            records = handoff.get("records", [])
            if not isinstance(records, list) or not records:
                errors.append("aitable_handoff.records must be a non-empty array")
                records = []
            for index, record in enumerate(records):
                label = f"aitable_handoff.records[{index}]"
                if not isinstance(record, dict):
                    errors.append(f"{label} must be an object")
                    continue
                clip_id = record.get("clip_id")
                if clip_id not in clip_by_id:
                    errors.append(f"{label}.clip_id is unknown: {clip_id}")
                    continue
                write_fields = set(record.get("write_field_ids", []))
                overlap = sorted(protected & write_fields)
                if overlap:
                    errors.append(f"{label} writes protected fields: {', '.join(overlap)}")
                attachments = record.get("attachment_filenames", [])
                if not isinstance(attachments, list):
                    errors.append(f"{label}.attachment_filenames must be an array")
                    attachments = []
                if len(attachments) > MAX_AITABLE_ATTACHMENTS:
                    errors.append(
                        f"{label} has {len(attachments)} total attachments; "
                        f"AI table maximum is {MAX_AITABLE_ATTACHMENTS}, including character, storyboard, audio, and product assets"
                    )
                if len(attachments) != len(set(attachments)):
                    errors.append(f"{label}.attachment_filenames contains duplicates")
                required_names = {
                    Path(value).name for value in clip_by_id[str(clip_id)].get("storyboard_files", [])
                }
                if character_sheet:
                    required_names.add(character_sheet.name)
                required_names.update(audio_by_clip.get(str(clip_id), []))
                missing = sorted(required_names - set(attachments))
                if missing:
                    errors.append(f"{label} is missing attachments: {', '.join(missing)}")

    story_step_ids: list[str] = []
    narrative = contract.get("narrative_qc")
    if not isinstance(narrative, dict):
        errors.append("narrative_qc is required; add the dramatic question, causal links, resolution, and clip complexity")
    else:
        question = narrative.get("dramatic_question")
        if not isinstance(question, str) or not question.strip():
            errors.append("narrative_qc.dramatic_question is required")
        world_rule = narrative.get("world_rule")
        if not isinstance(world_rule, dict) or not isinstance(world_rule.get("allows_unexplained_magic"), bool):
            errors.append("narrative_qc.world_rule.allows_unexplained_magic must be true or false")
        story_chain = narrative.get("story_chain")
        if not isinstance(story_chain, list) or len(story_chain) < 4:
            errors.append("narrative_qc.story_chain must contain at least problem, choice, consequence, and resolution")
            story_chain = []
        else:
            allowed_types = {"problem", "choice", "consequence", "escalation", "resolution"}
            product_roles = {"none", "evidence", "bargaining_chip", "incentive", "obstacle", "solution"}
            has_choice = False
            has_consequence = False
            has_product_role = False
            for index, step in enumerate(story_chain):
                label = f"narrative_qc.story_chain[{index}]"
                if not isinstance(step, dict):
                    errors.append(f"{label} must be an object")
                    continue
                step_id = step.get("id")
                step_type = step.get("type")
                if not isinstance(step_id, str) or not step_id:
                    errors.append(f"{label}.id is required")
                elif step_id in story_step_ids:
                    errors.append(f"duplicate story step id: {step_id}")
                else:
                    story_step_ids.append(step_id)
                if step_type not in allowed_types:
                    errors.append(f"{label}.type must be one of: {', '.join(sorted(allowed_types))}")
                if index == 0 and step_type != "problem":
                    errors.append("narrative_qc.story_chain must start with a problem")
                if index > 0:
                    caused_by = step.get("caused_by")
                    if caused_by not in story_step_ids[:-1]:
                        errors.append(f"{label}.caused_by must name an earlier story step")
                script_ids = step.get("script_ids")
                if not isinstance(script_ids, list) or not script_ids:
                    errors.append(f"{label}.script_ids must be a non-empty array")
                else:
                    for script_id in script_ids:
                        if not isinstance(script_id, str) or script_id not in script_text:
                            errors.append(f"{label} references a script id missing from the script: {script_id}")
                for field in ("actor", "action"):
                    value = step.get(field)
                    if not isinstance(value, str) or not value.strip():
                        errors.append(f"{label}.{field} is required")
                product_role = step.get("product_role")
                if product_role not in product_roles:
                    errors.append(f"{label}.product_role must be one of: {', '.join(sorted(product_roles))}")
                elif product_role != "none":
                    has_product_role = True
                if step_type == "choice":
                    has_choice = True
                if step_type in {"consequence", "resolution"}:
                    has_consequence = True
                    visible_result = step.get("visible_result")
                    if not isinstance(visible_result, str) or not visible_result.strip():
                        errors.append(f"{label}.visible_result is required for {step_type}")
            if not has_choice:
                errors.append("narrative_qc.story_chain must include a character choice")
            if not has_consequence:
                errors.append("narrative_qc.story_chain must include a visible consequence")
            if story_chain and story_chain[-1].get("type") != "resolution":
                errors.append("narrative_qc.story_chain must end with a resolution")
            elif story_chain and story_chain[-1].get("answers") != story_chain[0].get("id"):
                errors.append("the resolution story step must answer the opening problem step")
            if not has_product_role:
                errors.append("narrative_qc.story_chain must give the product a causal role, not decoration")
        resolution = narrative.get("resolution")
        if not isinstance(resolution, dict):
            errors.append("narrative_qc.resolution must state how the dramatic question is answered")
        else:
            script_id = resolution.get("script_id")
            answer = resolution.get("answer")
            if not isinstance(script_id, str) or not script_id or script_id not in script_text:
                errors.append("narrative_qc.resolution.script_id must identify a script beat")
            if not isinstance(answer, str) or not answer.strip():
                errors.append("narrative_qc.resolution.answer is required")
        policies = narrative.get("clip_policies")
        if not isinstance(policies, list) or len(policies) != len(clip_by_id):
            errors.append("narrative_qc.clip_policies must contain exactly one entry per clip")
        else:
            seen_policies: set[str] = set()
            for index, item in enumerate(policies):
                label = f"narrative_qc.clip_policies[{index}]"
                if not isinstance(item, dict):
                    errors.append(f"{label} must be an object")
                    continue
                clip_id = item.get("clip_id")
                if clip_id not in clip_by_id or clip_id in seen_policies:
                    errors.append(f"{label}.clip_id must name one unique declared clip")
                    continue
                seen_policies.add(str(clip_id))
                delivery_mode = item.get("delivery_mode")
                if delivery_mode not in DELIVERY_MODE_SPEECH_LIMITS:
                    errors.append(
                        f"{label}.delivery_mode must be one of: {', '.join(DELIVERY_MODE_SPEECH_LIMITS)}"
                    )

    dialogue_requirements = contract.get("dialogue_requirements")
    if not isinstance(dialogue_requirements, list):
        errors.append("dialogue_requirements must be an array")
        dialogue_requirements = []
    non_silent_clips = {
        item.get("clip_id")
        for item in narrative.get("clip_policies", [])
        if isinstance(item, dict) and item.get("delivery_mode") != "silent_or_music"
    } if isinstance(narrative, dict) else set()
    requirement_clips: set[str] = set()
    requirement_ids: set[str] = set()
    for index, requirement in enumerate(dialogue_requirements):
        label = f"dialogue_requirements[{index}]"
        if not isinstance(requirement, dict):
            errors.append(f"{label} must be an object")
            continue
        requirement_id = requirement.get("id")
        clip_id = requirement.get("clip_id")
        if not isinstance(requirement_id, str) or not requirement_id or requirement_id in requirement_ids:
            errors.append(f"{label}.id must be unique and non-empty")
        else:
            requirement_ids.add(requirement_id)
        if clip_id not in clip_by_id:
            errors.append(f"{label}.clip_id is unknown: {clip_id}")
        else:
            requirement_clips.add(str(clip_id))
        match_mode = requirement.get("match_mode")
        if match_mode not in {"exact", "contains", "terms"}:
            errors.append(f"{label}.match_mode must be exact, contains, or terms")
        expected_text = requirement.get("expected_text")
        required_terms = requirement.get("required_terms")
        if match_mode in {"exact", "contains"} and (not isinstance(expected_text, str) or not expected_text.strip()):
            errors.append(f"{label}.expected_text is required for {match_mode}")
        elif match_mode in {"exact", "contains"} and normalize_phrase(str(expected_text)) not in normalize_phrase(script_text):
            errors.append(f"{label}.expected_text is missing from the script")
        if match_mode == "terms" and (not isinstance(required_terms, list) or not required_terms):
            errors.append(f"{label}.required_terms must be a non-empty array for terms")
        elif match_mode == "terms":
            for term in required_terms:
                if normalize_phrase(str(term)) not in normalize_phrase(script_text):
                    errors.append(f"{label} required term is missing from the script: {term}")
    missing_dialogue_clips = sorted(non_silent_clips - requirement_clips)
    if missing_dialogue_clips:
        errors.append(f"dialogue_requirements missing non-silent clips: {', '.join(missing_dialogue_clips)}")

    prop_requirements = contract.get("prop_continuity_requirements")
    if not isinstance(prop_requirements, list):
        errors.append("prop_continuity_requirements must be an array")
        prop_requirements = []
    prop_ids: set[str] = set()
    for index, requirement in enumerate(prop_requirements):
        label = f"prop_continuity_requirements[{index}]"
        if not isinstance(requirement, dict):
            errors.append(f"{label} must be an object")
            continue
        prop_id = requirement.get("id")
        if not isinstance(prop_id, str) or not prop_id or prop_id in prop_ids:
            errors.append(f"{label}.id must be unique and non-empty")
        else:
            prop_ids.add(prop_id)
        events = requirement.get("event_ids")
        if not isinstance(events, list) or not events:
            errors.append(f"{label}.event_ids must be a non-empty array")
        introduction_script_id = requirement.get("introduction_script_id")
        if not isinstance(introduction_script_id, str) or introduction_script_id not in script_text:
            errors.append(f"{label}.introduction_script_id must exist in the script")

    director_requirements = contract.get("director_requirements")
    if not isinstance(director_requirements, dict):
        errors.append("director_requirements must be an object")
    else:
        final_memory_step_id = director_requirements.get("final_memory_step_id")
        if final_memory_step_id not in story_step_ids:
            errors.append("director_requirements.final_memory_step_id must name a story_chain step")
        performance_arcs = director_requirements.get("performance_arcs")
        if not isinstance(performance_arcs, list) or not performance_arcs:
            errors.append("director_requirements.performance_arcs must be a non-empty array")
        else:
            arc_ids: set[str] = set()
            for index, arc in enumerate(performance_arcs):
                label = f"director_requirements.performance_arcs[{index}]"
                if not isinstance(arc, dict):
                    errors.append(f"{label} must be an object")
                    continue
                arc_id = arc.get("id")
                if not isinstance(arc_id, str) or not arc_id or arc_id in arc_ids:
                    errors.append(f"{label}.id must be unique and non-empty")
                else:
                    arc_ids.add(arc_id)
                if not isinstance(arc.get("character"), str) or not arc.get("character", "").strip():
                    errors.append(f"{label}.character is required")
                states = arc.get("states")
                if not isinstance(states, list) or len(states) < 3:
                    errors.append(f"{label}.states must contain at least start, turn, and result")
                    continue
                state_ids: set[str] = set()
                for state in states:
                    if not isinstance(state, dict):
                        errors.append(f"{label}.states entries must be objects")
                        continue
                    state_id = state.get("id")
                    script_id = state.get("script_id")
                    if not isinstance(state_id, str) or not state_id or state_id in state_ids:
                        errors.append(f"{label} state ids must be unique and non-empty")
                    else:
                        state_ids.add(state_id)
                    if not isinstance(script_id, str) or script_id not in script_text:
                        errors.append(f"{label} state script_id is missing from the script: {script_id}")

    creative_room = contract.get("creative_room")
    if not isinstance(creative_room, dict):
        errors.append("creative_room is required before the timed screenplay")
    else:
        dna = creative_room.get("reference_mechanism_dna")
        dna_fields = (
            "opening_hook", "viewer_question", "misbelief", "conflict_engine",
            "reversal_mechanism", "emotional_payoff", "final_memory_point",
        )
        if not isinstance(dna, dict):
            errors.append("creative_room.reference_mechanism_dna must be an object")
        else:
            for field in dna_fields:
                if not isinstance(dna.get(field), str) or not dna.get(field, "").strip():
                    errors.append(f"creative_room.reference_mechanism_dna.{field} is required")

        candidates = creative_room.get("candidates")
        candidate_by_id: dict[str, dict] = {}
        signatures: set[str] = set()
        required_candidate_fields = (
            "logline", "conflict", "character_choice", "visible_consequence",
            "unexpected_turn", "setup_evidence", "product_role", "ending_payoff",
        )
        minimum_candidates = 3 if schema_version == 5 else 5
        if not isinstance(candidates, list) or len(candidates) < minimum_candidates:
            errors.append(f"creative_room.candidates must contain at least {minimum_candidates} genuinely different concepts")
            candidates = []
        for index, candidate in enumerate(candidates):
            label = f"creative_room.candidates[{index}]"
            if not isinstance(candidate, dict):
                errors.append(f"{label} must be an object")
                continue
            candidate_id = candidate.get("id")
            if not isinstance(candidate_id, str) or not candidate_id or candidate_id in candidate_by_id:
                errors.append(f"{label}.id must be unique and non-empty")
            else:
                candidate_by_id[candidate_id] = candidate
            for field in required_candidate_fields:
                if not isinstance(candidate.get(field), str) or not candidate.get(field, "").strip():
                    errors.append(f"{label}.{field} is required")
            axes = candidate.get("difference_axes")
            if not isinstance(axes, list) or len(set(axes)) < 2:
                errors.append(f"{label}.difference_axes must name at least 2 changed story dimensions")
            signature = normalize_phrase(str(candidate.get("mechanism_signature", "")))
            if not signature:
                errors.append(f"{label}.mechanism_signature is required")
            elif signature in signatures:
                errors.append(f"{label}.mechanism_signature duplicates another concept")
            else:
                signatures.add(signature)
            scorecard = candidate.get("scorecard")
            if not isinstance(scorecard, dict):
                errors.append(f"{label}.scorecard must be an object")
                continue
            calculated_total = 0
            for field, maximum in CREATIVE_SCORE_LIMITS.items():
                value = scorecard.get(field)
                if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= maximum:
                    errors.append(f"{label}.scorecard.{field} must be an integer from 0 to {maximum}")
                else:
                    calculated_total += value
            if scorecard.get("total") != calculated_total:
                errors.append(f"{label}.scorecard.total must equal the six category scores")
            if not isinstance(scorecard.get("hard_vetoes"), list):
                errors.append(f"{label}.scorecard.hard_vetoes must be an array")

        selected_id = creative_room.get("selected_candidate_id")
        selected = candidate_by_id.get(selected_id)
        if selected is None:
            errors.append("creative_room.selected_candidate_id must name one candidate")
        else:
            selected_scorecard = selected.get("scorecard", {})
            if selected_scorecard.get("total", 0) < 85:
                if schema_version == 5:
                    warnings.append("creative score below 85; independent editorial evidence, not a self-score, controls schema5 approval")
                else:
                    errors.append("selected creative concept must score at least 85")
            if selected_scorecard.get("hard_vetoes"):
                errors.append("selected creative concept cannot contain hard vetoes")
            for candidate_id, candidate in candidate_by_id.items():
                if candidate_id != selected_id and (
                    not isinstance(candidate.get("rejection_reason"), str)
                    or not candidate.get("rejection_reason", "").strip()
                ):
                    errors.append(f"unselected creative concept {candidate_id} requires a rejection_reason")
        if not isinstance(creative_room.get("selection_reason"), str) or not creative_room.get("selection_reason", "").strip():
            errors.append("creative_room.selection_reason is required")

        table_read = creative_room.get("table_read")
        if not isinstance(table_read, dict):
            errors.append("creative_room.table_read must be an object")
        else:
            if table_read.get("passed") is not True:
                errors.append("creative_room.table_read.passed must be true")
            if schema_version == 5:
                for field in ("product_removal_observation", "commercial_relevance_evidence"):
                    if not isinstance(table_read.get(field), str) or not table_read[field].strip():
                        errors.append(f"table read needs concrete {field}, not a product-deletion checkbox")
            elif table_read.get("product_removal_breaks_story") is not True:
                errors.append("table read must confirm that removing the product breaks the story")
            if table_read.get("dialogue_read_aloud") is not True:
                errors.append("table read must include dialogue read-aloud timing")
            issues = table_read.get("issues")
            if not isinstance(issues, list) or issues:
                errors.append("creative_room.table_read.issues must be an empty array before screenplay approval")
            checks = table_read.get("checks")
            checked_ids: set[str] = set()
            if not isinstance(checks, list):
                errors.append("creative_room.table_read.checks must be an array")
                checks = []
            for index, check in enumerate(checks):
                label = f"creative_room.table_read.checks[{index}]"
                if not isinstance(check, dict):
                    errors.append(f"{label} must be an object")
                    continue
                step_id = check.get("story_step_id")
                if step_id not in story_step_ids or step_id in checked_ids:
                    errors.append(f"{label}.story_step_id must name one unique story_chain step")
                else:
                    checked_ids.add(step_id)
                for field in ("viewer_question", "beat_change", "next_cause"):
                    if not isinstance(check.get(field), str) or not check.get(field, "").strip():
                        errors.append(f"{label}.{field} is required")
                if check.get("performable_in_seconds") is not True:
                    errors.append(f"{label}.performable_in_seconds must be true")
            if set(story_step_ids) != checked_ids:
                errors.append("creative_room.table_read.checks must cover every story_chain step exactly once")

    return {
        "status": "ok" if not errors else "failed",
        "project": str(project),
        "stage": stage,
        "schema_version": contract.get("schema_version"),
        "mode": mode,
        "clip_count": len(clips),
        "storyboard_count": len(storyboard_paths),
        "reference_beat_count": len(beats),
        "audio_asset_count": len(audio_assets),
        "visual_text_requirement_count": len(visual_text),
        "creative_candidate_count": len(creative_room.get("candidates", [])) if isinstance(creative_room, dict) else 0,
        "motion_beat_count": motion_beat_count,
        "errors": errors,
        "warnings": warnings,
    }


def validate_legacy(project: Path) -> dict:
    errors: list[str] = []
    warnings = ["legacy validation does not check narrative beats, prompt assets, audio, exact text, or AI table safety"]
    for relative in LEGACY_REQUIRED_FILES:
        if not (project / relative).is_file():
            errors.append(f"missing required file: {relative}")
    images = sorted((project / "storyboard").glob("*.png")) if (project / "storyboard").is_dir() else []
    if not images:
        errors.append("storyboard contains no PNG files")
    for image in images:
        validate_png(image, errors)
    return {
        "status": "ok" if not errors else "failed",
        "project": str(project),
        "legacy": True,
        "storyboard_count": len(images),
        "errors": errors,
        "warnings": warnings,
    }


def validate(project: Path, legacy: bool = False, stage: str = "pre-generation") -> dict:
    contract_path = project / CONTRACT_FILE
    if not contract_path.is_file():
        if legacy:
            return validate_legacy(project)
        return {
            "status": "failed",
            "project": str(project),
            "errors": [f"missing required file: {CONTRACT_FILE}"],
            "warnings": [],
        }
    errors: list[str] = []
    contract = load_json(contract_path, errors, CONTRACT_FILE)
    if errors:
        return {"status": "failed", "project": str(project), "errors": errors, "warnings": []}
    return validate_contract(project, contract, stage=stage)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a yishufan replica package.")
    parser.add_argument("project_dir")
    parser.add_argument("--legacy", action="store_true", help="Use the old shallow checks when no contract exists")
    parser.add_argument("--stage", choices=("pre-visual", "pre-generation", "pre-stitch", "pre-publish"), default="pre-generation")
    parser.add_argument("--report", help="Optional JSON report path")
    args = parser.parse_args()
    project = Path(args.project_dir).expanduser().resolve()
    result = validate(project, legacy=args.legacy, stage=args.stage)
    report = Path(args.report).expanduser().resolve() if args.report else project / "07_package_validation.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
