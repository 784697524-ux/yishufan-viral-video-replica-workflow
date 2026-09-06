#!/usr/bin/env python3
"""Parse the timed screenplay and reject content that a short-video model cannot perform clearly."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


CONTRACT_FILE = "08_replica_contract.json"
TIME_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*[–—-]\s*(\d+(?:\.\d+)?)\s*(?:秒|s)?\s*$", re.I)
SCRIPT_ID_RE = re.compile(r"\bS\d+[A-Za-z0-9_-]*\b", re.I)
QUOTE_RE = re.compile(r'“([^”]+)”|"([^"]+)"|「([^」]+)」|『([^』]+)』')
HAN_RE = re.compile(r"[\u3400-\u9fff]")
NON_HAN_SPEECH_RE = re.compile(r"[A-Za-z\d]")
SPEECH_WINDOW_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[–—-]\s*(\d+(?:\.\d+)?)\s*秒")
SILENCE_RE = re.compile(r"^(?:无(?:对白|台词|口播|旁白)|无|静音|不说话|—|-)"
                        r"(?:[；;，,。]\s*(?:不张嘴|人物不张嘴|全员不张嘴|无嘴型|仅环境声|仅音效))*[。.]?$")
MAGIC_RE = re.compile(
    r"光带|魔法|瞬移|传送|(?<!不)(?<!禁止)穿越|"
    r"(?<!禁止)(?<!不得)(?<!不许)(?<!避免)凭空|自动变装|化成发光|炸出金色|突然出现|忽然出现"
)
PRODUCT_RE = re.compile(
    r"\d+(?:\.\d+)?\s*元|\d+\s*抵\s*\d+|\d+\s*选\s*[一二三四五六七八九十\d]+|"
    r"[零一二三四五六七八九十百千万两]+\s*元|"
    r"[零一二三四五六七八九十百千万两]+\s*抵\s*[零一二三四五六七八九十百千万两]+|"
    r"奶茶|双人餐|抵用|美容|搏击|体验券|权益|买一送一|免费试吃"
)
SPEECH_LIMITS = {
    "dialogue_drama": 0.60,
    "montage_voiceover": 0.75,
    "poetic_narration": 0.92,
    "silent_or_music": 0.0,
}
DEFAULT_MODEL_CAPACITY = {
    "max_script_units": 3,
    "max_spoken_turns": 2,
    "max_product_fact_rows": 1,
}


def file_digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def parse_rows(text: str) -> list[dict]:
    rows: list[dict] = []
    dialogue_index: int | None = None
    window_index: int | None = None
    dialogue_header = ""
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.lstrip().startswith("|"):
            # A new table must declare its own columns; never inherit a previous header.
            dialogue_index, window_index, dialogue_header = None, None, ""
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if not cells:
            continue
        time_index = next((index for index, cell in enumerate(cells[:3]) if TIME_RE.match(cell)), None)
        malformed_time_row = time_index is None and any(SCRIPT_ID_RE.search(cell) for cell in cells)
        if time_index is None and not malformed_time_row:
            if all(re.fullmatch(r":?-+:?", cell.replace(" ", "")) for cell in cells):
                continue
            window_index = next((index for index, cell in enumerate(cells) if "窗口" in cell), None)
            dialogue_index = next((index for index, cell in enumerate(cells)
                                   if index != window_index and any(term in cell for term in ("对白", "台词", "口播", "旁白"))), None)
            dialogue_header = cells[dialogue_index] if dialogue_index is not None else ""
            continue
        match = TIME_RE.match(cells[time_index]) if time_index is not None else None
        start, end = (float(match.group(1)), float(match.group(2))) if match else (0.0, 0.0)
        parse_errors = ["unparseable timed row; use a start-end range in the first three columns"] if malformed_time_row else []
        if end <= start:
            parse_errors.append("time range must have positive duration")
        row_text = " | ".join(cell for index, cell in enumerate(cells) if index != time_index)
        speech_source = cells[dialogue_index] if dialogue_index is not None and dialogue_index < len(cells) else ""
        if dialogue_index is None or dialogue_index >= len(cells):
            parse_errors.append("timed row needs a dialogue column in its own table header")
        quotes = [next(item for item in match if item).strip() for match in QUOTE_RE.findall(speech_source)]
        prefix = QUOTE_RE.split(speech_source, maxsplit=1)[0] if quotes else speech_source.split("：", 1)[0]
        if SILENCE_RE.fullmatch(speech_source):
            spoken_text = ""
        elif quotes:
            spoken_text = "".join(quotes)
            remainder = QUOTE_RE.sub("", speech_source)
            # A second, unquoted speaker must not disappear from a partly quoted cell.
            for part in re.split(r"[；;\n]", remainder):
                if re.search(r"[：:]\s*[\u3400-\u9fffA-Za-z\d]", part):
                    parse_errors.append("mixed quoted and unquoted dialogue is ambiguous; quote every utterance")
        elif speech_source:
            if any(term in dialogue_header for term in ("画面", "动作")) and not re.search(r"[：:]", speech_source):
                spoken_text = ""
                parse_errors.append("mixed visual/dialogue cell needs explicit quoted dialogue or 无对白")
            else:
                spoken_text = re.split(r"[：:]", speech_source, maxsplit=1)[-1].strip()
                if any(mark in spoken_text for mark in ('“', '”', '"', '「', '」', '『', '』')):
                    parse_errors.append("unbalanced dialogue quotes")
        else:
            spoken_text = ""
            if dialogue_index is not None:
                parse_errors.append("empty dialogue cell; write 无对白 for intentional silence")
        speech_window = None
        window_source = cells[window_index] if window_index is not None and window_index < len(cells) else ""
        window_match = TIME_RE.match(window_source) if window_source else SPEECH_WINDOW_RE.search(prefix)
        if window_match:
            if not window_source and re.search(r"本段|本Clip|段内|片段内", prefix, re.I):
                parse_errors.append("local speech window is ambiguous; use absolute dialogue_requirements speech_start_seconds/speech_end_seconds")
            else:
                speech_window = (float(window_match[1]), float(window_match[2]))
        elif window_source and spoken_text:
            parse_errors.append("speech window must be an absolute start-end range")
        script_ids = SCRIPT_ID_RE.findall(row_text)
        rows.append(
            {
                "line_number": line_number,
                "start_seconds": start,
                "end_seconds": end,
                "script_ids": script_ids,
                "spoken_text": spoken_text,
                "spoken_characters": len(HAN_RE.findall(spoken_text)) + len(NON_HAN_SPEECH_RE.findall(spoken_text)),
                "requires_spoken_expansion": bool(NON_HAN_SPEECH_RE.search(spoken_text)),
                "speech_window": speech_window,
                "parse_errors": parse_errors,
                "has_product_fact": bool(spoken_text and PRODUCT_RE.search(spoken_text)),
                "magic_terms": sorted(set(MAGIC_RE.findall(row_text))),
                "text": row_text,
            }
        )
    return rows


def union_duration(intervals: list[tuple[float, float]]) -> float:
    if not intervals:
        return 0.0
    total = 0.0
    current_start, current_end = sorted(intervals)[0]
    for start, end in sorted(intervals)[1:]:
        if start <= current_end:
            current_end = max(current_end, end)
        else:
            total += current_end - current_start
            current_start, current_end = start, end
    return total + current_end - current_start


def infer_delivery_mode(script_text: str) -> str:
    if "朗读" in script_text and "不张嘴" in script_text:
        return "poetic_narration"
    if "旁白" in script_text and "嘴型同步" not in script_text:
        return "montage_voiceover"
    return "dialogue_drama"


def analyze(project: Path) -> dict:
    project = project.expanduser().resolve()
    contract = json.loads((project / CONTRACT_FILE).read_text(encoding="utf-8"))
    script_relative = contract.get("deliverables", {}).get("script")
    script_path = project / str(script_relative or "04_script.md")
    script_text = script_path.read_text(encoding="utf-8")
    rows = parse_rows(script_text)
    errors: list[str] = []
    warnings: list[str] = []
    schema5 = contract.get("schema_version", 3) >= 5
    if not rows:
        errors.append("script has no parseable timed Markdown rows; use one row per performable unit")

    narrative = contract.get("narrative_qc", {})
    policies = {
        item.get("clip_id"): item.get("delivery_mode")
        for item in narrative.get("clip_policies", narrative.get("clip_complexity", []))
        if isinstance(item, dict)
    }
    world_rule = narrative.get("world_rule", {})
    allows_magic = world_rule.get("allows_unexplained_magic") is True
    product_hook_allowed = narrative.get("product_hook_user_requested") is True
    target_duration = float(contract.get("target_duration_seconds") or 0)
    opening_cutoff = target_duration * 0.30
    mode = contract.get("mode")
    clip_results: list[dict] = []
    clips = contract.get("clips", [])
    previous_end = 0.0
    for clip in clips:
        start, end = float(clip.get("start_seconds") or 0), float(clip.get("end_seconds") or 0)
        if abs(start - previous_end) > 0.01 or not 1 <= end - start <= 15:
            errors.append(f"{clip.get('id')} clips must continuously cover the target with durations from 1 to 15 seconds")
        previous_end = end
    if not clips or target_duration <= 0 or abs(previous_end - target_duration) > 0.01:
        errors.append("clips must cover the full positive target_duration_seconds")

    requirements = contract.get("dialogue_requirements", [])
    previous_end = 0.0
    for row in rows:
        label = f"script line {row['line_number']}"
        errors.extend(f"{label}: {error}" for error in row["parse_errors"])
        if abs(row["start_seconds"] - previous_end) > 0.01:
            errors.append(f"{label}: timed rows must be ordered and continuous without gaps or overlaps")
        previous_end = row["end_seconds"]
        owners = [clip for clip in clips if row["start_seconds"] >= float(clip["start_seconds"]) - 0.01
                  and row["end_seconds"] <= float(clip["end_seconds"]) + 0.01]
        if len(owners) != 1:
            errors.append(f"{label}: timed row crosses a clip boundary or lies outside clips; split the row explicitly")
        matching = [item for item in requirements if item.get("script_id") in row["script_ids"]]
        if len(matching) > 1:
            errors.append(f"{label}: multiple dialogue_requirements match one script unit; split utterances into rows")
        requirement = matching[0] if len(matching) == 1 else {}
        if requirement and owners and requirement.get("clip_id") != owners[0].get("id"):
            errors.append(f"{label}: dialogue requirement clip_id does not match its script row")
        expanded = requirement.get("spoken_text")
        if expanded is not None:
            normalize = lambda value: "".join(re.findall(r"[\u3400-\u9fffA-Za-z\d]", str(value)))
            if normalize(requirement.get("expected_text", "")) != normalize(row["spoken_text"]):
                errors.append(f"{label}: spoken_text requires expected_text matching the actual screenplay dialogue")
            if not isinstance(expanded, str) or not HAN_RE.search(expanded) or NON_HAN_SPEECH_RE.search(expanded):
                errors.append(f"{label}: spoken_text must expand all numbers and Latin text into spoken Chinese")
            else:
                position = 0
                for literal in re.findall(r"[\u3400-\u9fff]+", row["spoken_text"]):
                    found = expanded.find(literal, position)
                    if found < 0:
                        errors.append(f"{label}: spoken_text must preserve existing Chinese dialogue in order")
                        break
                    position = found + len(literal)
                row["spoken_characters"] = len(HAN_RE.findall(expanded))
                row["requires_spoken_expansion"] = False
        if row["requires_spoken_expansion"]:
            errors.append(f"{label}: numbers/Latin text need dialogue_requirements script_id, expected_text and spoken_text; pronunciation must not be undercounted")
        start_key = "speech_start_seconds" if "speech_start_seconds" in requirement else "start_seconds"
        end_key = "speech_end_seconds" if "speech_end_seconds" in requirement else "end_seconds"
        if start_key in requirement or end_key in requirement:
            try:
                declared_window = (float(requirement[start_key]), float(requirement[end_key]))
                if row["speech_window"] is not None and row["speech_window"] != declared_window:
                    errors.append(f"{label}: screenplay and dialogue requirement speech windows disagree")
                row["speech_window"] = declared_window
            except (KeyError, TypeError, ValueError):
                errors.append(f"{label}: dialogue requirement needs both numeric absolute speech window endpoints")
        if row["spoken_characters"]:
            if schema5 and row["speech_window"] is None:
                errors.append(f"{label}: schema5 dialogue needs an explicit absolute speech window")
            speech_start, speech_end = row["speech_window"] or (row["start_seconds"], row["end_seconds"])
            row["speech_window"] = (speech_start, speech_end)
            if not row["start_seconds"] <= speech_start < speech_end <= row["end_seconds"]:
                errors.append(f"{label}: speech window must lie completely inside its timed row")
            if row["spoken_characters"] / 4.2 > speech_end - speech_start + 0.01:
                errors.append(f"{label}: dialogue exceeds its actual speech window at maximum 4.20 Chinese characters/s")
    if rows and abs(previous_end - target_duration) > 0.01:
        errors.append("timed rows must cover target_duration_seconds exactly")

    for clip in clips:
        clip_id = clip.get("id")
        clip_start = float(clip.get("start_seconds") or 0)
        clip_end = float(clip.get("end_seconds") or 0)
        clip_duration = clip_end - clip_start
        clip_rows = [
            row
            for row in rows
            if row["start_seconds"] < clip_end and row["end_seconds"] > clip_start
        ]
        delivery_mode = policies.get(clip_id) or infer_delivery_mode(script_text)
        spoken_rows = [row for row in clip_rows if row["spoken_characters"] > 0]
        scheduled_spoken_window = union_duration(
            [row["speech_window"] for row in spoken_rows]
        )
        spoken_characters = sum(row["spoken_characters"] for row in spoken_rows)
        minimum_spoken_seconds = spoken_characters / 4.2
        speech_ratio = minimum_spoken_seconds / clip_duration if clip_duration > 0 else 0
        scheduled_speech_rate = (
            spoken_characters / scheduled_spoken_window if scheduled_spoken_window > 0 else 0
        )
        script_units = []
        for row in clip_rows:
            candidates = row["script_ids"] or [f"line-{row['line_number']}"]
            for item in candidates:
                if item not in script_units:
                    script_units.append(item)
        product_fact_rows = [row for row in spoken_rows if row["has_product_fact"]]
        magic_terms = sorted({term for row in clip_rows for term in row["magic_terms"]})

        if delivery_mode not in SPEECH_LIMITS:
            errors.append(f"{clip_id} has unsupported delivery_mode: {delivery_mode}")
        else:
            allowed_seconds = clip_duration * (1.0 if schema5 and delivery_mode != "silent_or_music" else SPEECH_LIMITS[delivery_mode])
            if minimum_spoken_seconds > allowed_seconds + 0.01:
                errors.append(
                    f"{clip_id} needs at least {minimum_spoken_seconds:.2f}s of speech/{clip_duration:.2f}s; "
                    f"{delivery_mode} allows {allowed_seconds:.2f}s"
                )
        if scheduled_speech_rate > 4.2:
            errors.append(
                f"{clip_id} scheduled speech rate is {scheduled_speech_rate:.2f} Chinese characters/s; maximum is 4.20"
            )
        if not schema5:
            if len(script_units) > DEFAULT_MODEL_CAPACITY["max_script_units"]:
                errors.append(
                    f"{clip_id} contains {len(script_units)} timed script units; maximum is 3 per generated clip"
                )
            if delivery_mode == "dialogue_drama" and len(spoken_rows) > DEFAULT_MODEL_CAPACITY["max_spoken_turns"]:
                errors.append(f"{clip_id} contains {len(spoken_rows)} spoken turns; maximum is 2 for dialogue drama")
            if delivery_mode == "dialogue_drama" and len(product_fact_rows) > DEFAULT_MODEL_CAPACITY["max_product_fact_rows"]:
                errors.append(
                    f"{clip_id} puts product facts into {len(product_fact_rows)} dialogue rows; keep one hero fact in drama"
                )
        if not schema5 and not product_hook_allowed and any(row["start_seconds"] < opening_cutoff for row in product_fact_rows):
            errors.append(
                f"{clip_id} introduces product facts before the first 30% without product_hook_user_requested=true"
            )
        if schema5:
            model_capacity = clip.get("model_capacity")
            model_capacity = model_capacity if isinstance(model_capacity, dict) else {}
            capacity_counts = {
                "max_script_units": len(script_units),
                "max_spoken_turns": len(spoken_rows) if delivery_mode == "dialogue_drama" else 0,
                "max_product_fact_rows": len(product_fact_rows) if delivery_mode == "dialogue_drama" else 0,
            }
            override_used = False
            for key, count in capacity_counts.items():
                default = DEFAULT_MODEL_CAPACITY[key]
                capacity = model_capacity.get(key)
                if capacity is None:
                    if count > default:
                        errors.append(
                            f"{clip_id} has {count} {key.removeprefix('max_').replace('_', ' ')}; "
                            f"default capacity is {default}, so a tested model_capacity override is required"
                        )
                    continue
                if not isinstance(capacity, int) or isinstance(capacity, bool) or capacity < 1 or count > capacity:
                    errors.append(f"{clip_id} exceeds or has invalid declared model_capacity.{key}: {capacity}")
                if isinstance(capacity, int) and not isinstance(capacity, bool) and capacity > default:
                    override_used = True
            if override_used:
                evidence_file = model_capacity.get("evidence_file")
                evidence_path = (project / evidence_file).resolve() if isinstance(evidence_file, str) else None
                if evidence_path is None or not evidence_path.is_relative_to(project) or not evidence_path.is_file():
                    errors.append(f"{clip_id} model_capacity override requires an evidence_file inside the project")
                else:
                    if model_capacity.get("evidence_sha256") != file_digest(evidence_path):
                        errors.append(f"{clip_id} model_capacity.evidence_sha256 does not match its evidence_file")
                if not isinstance(model_capacity.get("evidence_note"), str) or not model_capacity.get("evidence_note", "").strip():
                    errors.append(f"{clip_id} model_capacity override requires a concrete evidence_note")
        if magic_terms and not allows_magic:
            errors.append(
                f"{clip_id} uses unexplained magic/teleport terms while the world rule forbids them: {', '.join(magic_terms)}"
            )

        clip_results.append(
            {
                "clip_id": clip_id,
                "delivery_mode": delivery_mode,
                "timed_row_count": len(clip_rows),
                "script_units": script_units,
                "spoken_turns": len(spoken_rows),
                "scheduled_spoken_window_seconds": round(scheduled_spoken_window, 3),
                "minimum_spoken_seconds_at_4_2_cps": round(minimum_spoken_seconds, 3),
                "spoken_characters": spoken_characters,
                "speech_ratio": round(speech_ratio, 3),
                "scheduled_speech_rate_characters_per_second": round(scheduled_speech_rate, 3),
                "product_fact_dialogue_rows": len(product_fact_rows),
                "magic_terms": magic_terms,
            }
        )

    return {
        "status": "ok" if not errors else "failed",
        "project": str(project),
        "script": str(script_path),
        "mode": mode,
        "parsed_timed_rows": len(rows),
        "clips": clip_results,
        "errors": errors,
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze timed screenplay density and speech automatically.")
    parser.add_argument("project")
    parser.add_argument("--out")
    args = parser.parse_args()
    result = analyze(Path(args.project))
    output = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).expanduser().write_text(output, encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
