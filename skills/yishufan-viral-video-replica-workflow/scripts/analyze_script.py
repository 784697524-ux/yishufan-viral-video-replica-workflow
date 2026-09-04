#!/usr/bin/env python3
"""Parse the timed screenplay and reject content that a short-video model cannot perform clearly."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


CONTRACT_FILE = "08_replica_contract.json"
TIME_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*[–—-]\s*(\d+(?:\.\d+)?)\s*(?:秒|s)?\s*$", re.I)
SCRIPT_ID_RE = re.compile(r"\bS\d+[A-Za-z0-9_-]*\b", re.I)
QUOTE_RE = re.compile(r"[“\"]([^”\"]+)[”\"]")
HAN_RE = re.compile(r"[\u3400-\u9fff]")
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


def parse_rows(text: str) -> list[dict]:
    rows: list[dict] = []
    dialogue_index: int | None = None
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.lstrip().startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if not cells:
            continue
        time_index = next((index for index, cell in enumerate(cells[:3]) if TIME_RE.match(cell)), None)
        if time_index is None:
            header_dialogue_index = next(
                (index for index, cell in enumerate(cells) if any(term in cell for term in ("对白", "台词", "口播"))),
                None,
            )
            if header_dialogue_index is not None:
                dialogue_index = header_dialogue_index
            continue
        match = TIME_RE.match(cells[time_index])
        assert match
        start, end = float(match.group(1)), float(match.group(2))
        if end <= start:
            continue
        row_text = " | ".join(cell for index, cell in enumerate(cells) if index != time_index)
        speech_source = cells[dialogue_index] if dialogue_index is not None and dialogue_index < len(cells) else row_text
        quotes = [item.strip() for item in QUOTE_RE.findall(speech_source) if item.strip()]
        spoken_text = "".join(quotes)
        script_ids = SCRIPT_ID_RE.findall(row_text)
        rows.append(
            {
                "line_number": line_number,
                "start_seconds": start,
                "end_seconds": end,
                "script_ids": script_ids,
                "spoken_text": spoken_text,
                "spoken_characters": len(HAN_RE.findall(spoken_text)),
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

    for clip in contract.get("clips", []):
        clip_id = clip.get("id")
        clip_start = float(clip.get("start_seconds") or 0)
        clip_end = float(clip.get("end_seconds") or 0)
        clip_duration = clip_end - clip_start
        clip_rows = [
            row
            for row in rows
            if clip_start - 0.01 <= (row["start_seconds"] + row["end_seconds"]) / 2 < clip_end + 0.01
        ]
        delivery_mode = policies.get(clip_id) or infer_delivery_mode(script_text)
        spoken_rows = [row for row in clip_rows if row["spoken_characters"] > 0]
        scheduled_spoken_window = union_duration(
            [(row["start_seconds"], row["end_seconds"]) for row in spoken_rows]
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
            allowed_seconds = clip_duration * SPEECH_LIMITS[delivery_mode]
            if minimum_spoken_seconds > allowed_seconds + 0.01:
                errors.append(
                    f"{clip_id} needs at least {minimum_spoken_seconds:.2f}s of speech/{clip_duration:.2f}s; "
                    f"{delivery_mode} allows {allowed_seconds:.2f}s"
                )
        if scheduled_speech_rate > 4.2:
            errors.append(
                f"{clip_id} scheduled speech rate is {scheduled_speech_rate:.2f} Chinese characters/s; maximum is 4.20"
            )
        if len(script_units) > 3:
            errors.append(
                f"{clip_id} contains {len(script_units)} timed script units; maximum is 3 per generated clip"
            )
        if delivery_mode == "dialogue_drama" and len(spoken_rows) > 2:
            errors.append(f"{clip_id} contains {len(spoken_rows)} spoken turns; maximum is 2 for dialogue drama")
        if delivery_mode == "dialogue_drama" and len(product_fact_rows) > 1:
            errors.append(
                f"{clip_id} puts product facts into {len(product_fact_rows)} dialogue rows; keep one hero fact in drama"
            )
        if not product_hook_allowed and any(row["start_seconds"] < opening_cutoff for row in product_fact_rows):
            errors.append(
                f"{clip_id} introduces product facts before the first 30% without product_hook_user_requested=true"
            )
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
