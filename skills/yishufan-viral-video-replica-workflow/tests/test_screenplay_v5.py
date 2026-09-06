from __future__ import annotations

import importlib.util
import hashlib
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("screenplay_v5", ROOT / "scripts/analyze_script.py")
analyzer = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(analyzer)


class ScreenplayV5Tests(unittest.TestCase):
    def analyze(self, script, schema=5, **updates):
        contract = {
            "schema_version": schema,
            "target_duration_seconds": 10,
            "deliverables": {"script": "04_script.md"},
            "clips": [{"id": "clip01", "start_seconds": 0, "end_seconds": 10}],
            "narrative_qc": {
                "product_hook_user_requested": False,
                "clip_policies": [{"clip_id": "clip01", "delivery_mode": "dialogue_drama"}],
            },
        }
        contract.update(updates)
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            (project / "04_script.md").write_text(script, encoding="utf-8")
            (project / analyzer.CONTRACT_FILE).write_text(json.dumps(contract), encoding="utf-8")
            return analyzer.analyze(project)

    @staticmethod
    def table(dialogue, window="0-3"):
        return ("| 时间 | ID | 画面 | 对白 | 口播窗口 |\n"
                "|---|---|---|---|---|\n"
                f"| 0-10 | S01/P01 | 递出试吃碟 | {dialogue} | {window} |\n")

    def test_unquoted_and_corner_quotes_are_not_silent_in_any_schema(self):
        for schema in (3, 4, 5):
            for dialogue in ("姑娘：先尝再说。", "姑娘：「先尝再说。」", "姑娘：『先尝再说。』"):
                with self.subTest(schema=schema, dialogue=dialogue):
                    result = self.analyze(self.table(dialogue), schema)
                    self.assertEqual(result["status"], "ok", result["errors"])
                    self.assertEqual(result["clips"][0]["spoken_characters"], 4)

    def test_unquoted_plain_dialogue_is_counted(self):
        rows = analyzer.parse_rows(self.table("先尝再说。"))
        self.assertEqual(rows[0]["spoken_characters"], 4)

    def test_visual_quotes_are_not_counted_as_dialogue(self):
        script = self.table("无对白").replace("递出试吃碟", "牌匾写着“请你来尝”")
        self.assertEqual(self.analyze(script)["clips"][0]["spoken_characters"], 0)

    def test_silence_prefix_cannot_hide_following_quoted_speech(self):
        rows = analyzer.parse_rows(self.table('无对白；姑娘：“其实我在讲话。”'))
        self.assertEqual(rows[0]["spoken_characters"], 6)

    def test_digits_and_latin_require_expansion_for_every_schema(self):
        for schema in (3, 4, 5):
            with self.subTest(schema=schema):
                result = self.analyze(self.table("掌柜：1元领券，N加品牌试吃。"), schema)
                self.assertEqual(result["status"], "failed")
                self.assertTrue(any("spoken_text" in error for error in result["errors"]))
                self.assertGreater(result["clips"][0]["spoken_characters"], 0)

    def test_spoken_expansion_counts_all_pronounced_characters(self):
        text = "1元领券，N加品牌试吃。"
        expanded = "一元领券，恩加品牌试吃。"
        result = self.analyze(self.table(f"掌柜：{text}"), dialogue_requirements=[{
            "script_id": "S01", "clip_id": "clip01", "expected_text": text,
            "spoken_text": expanded, "start_seconds": 0, "end_seconds": 3,
        }])
        self.assertEqual(result["status"], "ok", result["errors"])
        self.assertEqual(result["clips"][0]["spoken_characters"], 10)

    def test_expansion_cannot_erase_literal_chinese_or_bind_different_line(self):
        for expected, expanded in (("1元领券", "好"), ("另一句", "一元领券")):
            result = self.analyze(self.table("掌柜：1元领券"), dialogue_requirements=[{
                "script_id": "S01", "clip_id": "clip01", "expected_text": expected,
                "spoken_text": expanded,
            }])
            self.assertEqual(result["status"], "failed")

    def test_schema5_allows_early_confirmed_offer_but_legacy_rule_remains(self):
        script = self.table("掌柜：一元领券参加试吃大会。")
        self.assertEqual(self.analyze(script)["status"], "ok")
        for schema in (3, 4):
            result = self.analyze(script, schema)
            self.assertTrue(any("first 30%" in error for error in result["errors"]))

    def test_schema5_overload_requires_tested_model_capacity_evidence(self):
        script = ("| 时间 | ID | 对白 | 口播窗口 |\n|---|---|---|---|\n"
                  "| 0-2.5 | S01 | 好吃 | 0-1 |\n"
                  "| 2.5-5 | S02 | 再看 | 2.5-3.5 |\n"
                  "| 5-7.5 | S03 | 真香 | 5-6 |\n"
                  "| 7.5-10 | S04 | 走吧 | 7.5-8.5 |\n")
        result = self.analyze(script)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("tested model_capacity override is required" in error for error in result["errors"]))
        result = self.analyze(script, clips=[{
            "id": "clip01", "start_seconds": 0, "end_seconds": 10,
            "model_capacity": {"max_spoken_turns": 2},
        }])
        self.assertTrue(any("model_capacity.max_spoken_turns" in error for error in result["errors"]))

        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            evidence = project / "capacity_test.json"
            evidence.write_text('{"model":"tested","result":"four turns completed"}', encoding="utf-8")
            contract = {
                "schema_version": 5,
                "target_duration_seconds": 10,
                "deliverables": {"script": "04_script.md"},
                "clips": [{
                    "id": "clip01", "start_seconds": 0, "end_seconds": 10,
                    "model_capacity": {
                        "max_script_units": 4,
                        "max_spoken_turns": 4,
                        "max_product_fact_rows": 1,
                        "evidence_file": "capacity_test.json",
                        "evidence_sha256": hashlib.sha256(evidence.read_bytes()).hexdigest(),
                        "evidence_note": "同一模型、十秒时长、四轮短句的实际输出已逐句核验。",
                    },
                }],
                "narrative_qc": {
                    "product_hook_user_requested": False,
                    "clip_policies": [{"clip_id": "clip01", "delivery_mode": "dialogue_drama"}],
                },
            }
            (project / "04_script.md").write_text(script, encoding="utf-8")
            (project / analyzer.CONTRACT_FILE).write_text(json.dumps(contract), encoding="utf-8")
            self.assertEqual(analyzer.analyze(project)["status"], "ok")

    def test_more_turns_cannot_bypass_total_or_per_window_capacity(self):
        script = "| 时间 | ID | 对白 | 口播窗口 |\n|---|---|---|---|\n"
        for index in range(4):
            start = index * 2.5
            script += f"| {start}-{start + 2.5} | S{index + 1:02d} | 一二三四五六七八九十甲乙 | {start}-{start + 2.5} |\n"
        result = self.analyze(script)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("needs at least" in error for error in result["errors"]))
        self.assertTrue(any("actual speech window" in error for error in result["errors"]))

    def test_explicit_narrow_window_is_checked_for_legacy_too(self):
        for schema in (3, 4, 5):
            result = self.analyze(self.table("掌柜：先尝再说。", "0-0.5"), schema)
            self.assertTrue(any("actual speech window" in error for error in result["errors"]))

    def test_schema5_requires_window_and_accepts_requirement_absolute_window(self):
        script = "| 时间 | ID | 对白 |\n|---|---|---|\n| 0-10 | S01 | 姑娘：先尝再说 |\n"
        self.assertEqual(self.analyze(script)["status"], "failed")
        for keys in (("speech_start_seconds", "speech_end_seconds"), ("start_seconds", "end_seconds")):
            result = self.analyze(script, dialogue_requirements=[{
                "script_id": "S01", "clip_id": "clip01", keys[0]: 1, keys[1]: 3,
            }])
            self.assertEqual(result["status"], "ok", result["errors"])

    def test_requirement_window_cannot_extend_beyond_row(self):
        result = self.analyze(self.table("先尝再说"), dialogue_requirements=[{
            "script_id": "S01", "clip_id": "clip01", "start_seconds": 9, "end_seconds": 12,
        }])
        self.assertTrue(any("inside its timed row" in error for error in result["errors"]))

    def test_requirement_cannot_silently_override_a_shorter_written_window(self):
        result = self.analyze(self.table("先尝再说", "0-0.5"), dialogue_requirements=[{
            "script_id": "S01", "clip_id": "clip01", "start_seconds": 0, "end_seconds": 5,
        }])
        self.assertTrue(any("windows disagree" in error for error in result["errors"]))

    def test_cross_clip_row_is_not_silently_assigned_by_midpoint(self):
        result = self.analyze(self.table("先尝再说", "4-6"), clips=[
            {"id": "clip01", "start_seconds": 0, "end_seconds": 5},
            {"id": "clip02", "start_seconds": 5, "end_seconds": 10},
        ])
        self.assertTrue(any("crosses a clip boundary" in error for error in result["errors"]))
        self.assertTrue(all(clip["spoken_characters"] == 4 for clip in result["clips"]))

    def test_table_header_drift_or_missing_dialogue_is_explicit_failure(self):
        script = ("| 时间 | ID | 对白 |\n|---|---|---|\n| 0-5 | S01 | 无对白 |\n\n"
                  "| 时间 | 对白 | ID |\n|---|---|---|\n| 5-10 | 先尝再说 | S02 |\n")
        rows = analyzer.parse_rows(script)
        self.assertEqual(rows[1]["spoken_characters"], 4)
        script = script.replace("| 时间 | 对白 | ID |", "| 时间 | 画面 | ID |")
        result = self.analyze(script)
        self.assertTrue(any("own table header" in error for error in result["errors"]))

    def test_ambiguous_mixed_quotes_and_unbalanced_quotes_fail(self):
        for dialogue in ('女：“先尝”；男：再说', '女：「先尝再说'):
            self.assertEqual(self.analyze(self.table(dialogue))["status"], "failed")

    def test_malformed_time_row_cannot_disappear_before_a_valid_table(self):
        script = ("| 时间 | ID | 对白 |\n|---|---|---|\n| 零到三秒 | S99 | 忽略不得 |\n\n"
                  + self.table("先尝再说"))
        result = self.analyze(script)
        self.assertTrue(any("unparseable timed row" in error for error in result["errors"]))

    def test_clip_and_row_coverage_are_hard_requirements(self):
        result = self.analyze(self.table("先尝再说").replace("| 0-10 |", "| 1-10 |"))
        self.assertTrue(any("continuous" in error for error in result["errors"]))
        result = self.analyze(self.table("先尝再说"), target_duration_seconds=12)
        self.assertTrue(any("target_duration" in error for error in result["errors"]))


if __name__ == "__main__":
    unittest.main()
