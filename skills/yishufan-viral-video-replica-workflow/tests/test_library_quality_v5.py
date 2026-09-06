import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import test_viral_library as library_tests


library = library_tests.MODULE


class LibraryQualityV5Tests(unittest.TestCase):
    def build_case(self, qc=None):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        workspace = Path(temp.name)
        case = workspace / "outputs" / "古街插画试吃"
        case.mkdir(parents=True)
        (case / "01_reference_analysis.md").write_text("艺术范古街手绘插画，试吃多商户群像。", encoding="utf-8")
        (case / "04_script.md").write_text("掌柜邀客试吃，古街插画群像反转。", encoding="utf-8")
        if qc is not None:
            (case / "07_quality_gate.json").write_text(json.dumps(qc, ensure_ascii=False), encoding="utf-8")
        output = workspace / "library"
        library.build_library(workspace, output, workspace / "chat", False)
        return output / "index.sqlite3", case

    def test_business_brand_does_not_override_ancient_illustration_world(self):
        tags = library.extract_tags("合肥高新银泰百货，古街青绿手绘插画动画，一元试吃卡券")
        self.assertIn("商业场所", tags)
        self.assertIn("东方古装", tags)
        self.assertIn("手绘插画", tags)
        self.assertNotIn("现代商场", tags)
        self.assertIn("现代商场", library.extract_tags("银泰现代商场实景短视频"))

    def test_unknown_stays_reference_candidate_without_production_template(self):
        index, _ = self.build_case()
        result = library.search_library(index, "古街插画试吃多商户群像", 5)
        self.assertIsNone(result["production_template"])
        self.assertEqual(result["main_reference"]["quality_status"], "unknown")
        self.assertEqual(result["main_reference"]["reuse_scope"], "reference_candidate")
        self.assertEqual(result["main_reference"]["script_files"], [])
        archived = library.show_case(index, result["main_reference"]["case_id"])
        self.assertIn("reference_candidate", library.render_case_markdown(archived))

    def test_cached_success_without_structured_evidence_is_not_template(self):
        index, _ = self.build_case()
        with sqlite3.connect(index) as connection:
            connection.execute("UPDATE cases SET quality_status='allow_publish'")
        result = library.search_library(index, "古街插画试吃多商户群像", 5)
        self.assertIsNone(result["production_template"])

    @staticmethod
    def output_review(decision="allow_stitch"):
        qc = {
            "status": "ok", "decision": decision,
            "stage": "pre-stitch" if decision == "allow_stitch" else "pre-publish",
            "results": {
                "delivery": {"status": "ok", "outputs": [{
                    "clip_id": "clip01", "file": "renders/clip01.mp4", "duration_seconds": 15,
                    "width": 720, "height": 1280, "has_audio": True,
                }]},
                "director": {"status": "ok", "errors": []},
                "transcript": {"status": "ok", "errors": []},
            },
        }
        if decision == "allow_publish":
            qc["results"]["final"] = {"status": "ok", "file": "renders/final.mp4", "sha256": "b" * 64}
        return qc

    def test_pregeneration_success_remains_design_reference(self):
        index, _ = self.build_case({"status": "ok", "stage": "pre-generation", "decision": "allow_generation"})
        result = library.search_library(index, "古街插画试吃多商户群像", 5)
        self.assertIsNone(result["production_template"])
        self.assertEqual(result["main_reference"]["reuse_scope"], "reference_candidate")
        self.assertEqual(result["main_reference"]["template_scope"], "design_reference")
        self.assertEqual(result["main_reference"]["matched_stage"], "pre-generation")

    def test_success_label_without_actual_output_review_is_not_template(self):
        for decision in ("allow_stitch", "allow_publish"):
            with self.subTest(decision=decision):
                qc = self.output_review(decision)
                qc["results"]["delivery"]["outputs"] = []
                index, _ = self.build_case(qc)
                result = library.search_library(index, "古街插画试吃多商户群像", 5)
                self.assertIsNone(result["production_template"])

    def test_template_exposes_verified_stage_and_reassembled_evidence(self):
        qc = self.output_review()
        qc["notes"] = "插画" * 4000
        index, case = self.build_case(qc)
        result = library.search_library(index, "古街插画试吃多商户群像", 5)
        template = result["production_template"]
        self.assertIsNotNone(template)
        self.assertEqual(template["quality_status"], "allow_stitch")
        self.assertEqual(template["matched_stage"], "pre-stitch")
        self.assertEqual(template["template_scope"], "reviewed_clips")
        self.assertEqual(template["quality_evidence"], [{
            "file": str(case / "07_quality_gate.json"), "decision": "allow_stitch",
            "archived_content_sha256": hashlib.sha256(json.dumps(qc, ensure_ascii=False).encode("utf-8")).hexdigest(),
            "matched_stage": "pre-stitch", "template_scope": "reviewed_clips",
            "reviewed_outputs": qc["results"]["delivery"]["outputs"],
        }])
        self.assertIn("已验证阶段：pre-stitch", library.render_markdown(result))

    def test_publish_template_requires_final_file_and_hash(self):
        qc = self.output_review("allow_publish")
        index, _ = self.build_case(qc)
        result = library.search_library(index, "古街插画试吃多商户群像", 5)
        self.assertEqual(result["production_template"]["template_scope"], "reviewed_final_video")
        self.assertEqual(result["production_template"]["matched_stage"], "pre-publish")
        qc["results"]["final"].pop("sha256")
        index, _ = self.build_case(qc)
        self.assertIsNone(library.search_library(index, "古街插画试吃多商户群像", 5)["production_template"])

    def test_failed_director_review_cannot_support_success_label(self):
        qc = self.output_review()
        qc["results"]["director"]["status"] = "failed"
        index, _ = self.build_case(qc)
        self.assertIsNone(library.search_library(index, "古街插画试吃多商户群像", 5)["production_template"])

    def test_needs_review_does_not_become_template(self):
        index, _ = self.build_case({"status": "needs_review"})
        result = library.search_library(index, "古街插画试吃多商户群像", 5)
        self.assertIsNone(result["production_template"])
        self.assertEqual(result["main_reference"]["reuse_scope"], "reference_candidate")

    def test_block_generation_is_blocked_not_unknown(self):
        self.assertEqual(library.infer_quality(json.dumps({"decision": "block_generation", "status": "failed"})), "blocked")

    def test_negated_or_quoted_success_prose_cannot_certify_success(self):
        for text in ("不得声称 allow_generation", "只有 allow_publish 才能发布", '示例：{"decision":"allow_stitch"}'):
            self.assertNotIn(library.infer_quality(text), {"allow_generation", "allow_stitch", "allow_publish"})

    def test_success_requires_structured_success_status_and_decision(self):
        self.assertEqual(library.infer_quality('{"status":"ok","decision":"allow_generation"}'), "allow_generation")
        self.assertEqual(library.infer_quality('{"decision":"allow_generation"}'), "unknown")
        self.assertEqual(library.infer_quality('{"status":"failed","decision":"allow_generation"}'), "blocked")

    def test_user_rejected_overrides_old_success(self):
        documents = ['{"status":"ok","decision":"allow_publish"}', '{"quality_status":"user_rejected"}']
        self.assertEqual(library.combined_quality(documents), "blocked")

    def test_json_failure_without_video_keyword_is_indexed_and_excluded_from_template(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp)
            case = workspace / "outputs" / "插画试吃失败"
            case.mkdir(parents=True)
            (case / "01_reference_analysis.md").write_text("艺术范插画短视频复刻，试吃多商户群像。", encoding="utf-8")
            (case / "04_script.md").write_text("失败脚本，低密度叙事。", encoding="utf-8")
            (case / "07_quality_gate.json").write_text('{"status":"failed","decision":"block_generation"}', encoding="utf-8")
            output = workspace / "library"
            summary = library.build_library(workspace, output, workspace / "chat", False)
            self.assertEqual(summary["blocked_case_count"], 1)
            result = library.search_library(output / "index.sqlite3", "艺术范插画试吃多商户群像", 5)
            self.assertIsNone(result["production_template"])
            self.assertEqual(result["main_reference"]["reuse_scope"], "reference_analysis_only")
            self.assertEqual(result["main_reference"]["script_files"], [])

    def test_negative_lesson_uses_failed_document_not_similar_old_pass(self):
        query = "艺术范古街手绘插画试吃多商户群像"
        for padding in ("", query * 2000):
            with self.subTest(chunked=bool(padding)):
                old_pass = {"status": "ok", "decision": "allow_generation", "notes": query * 100}
                index, case = self.build_case(old_pass)
                failure = case / "14_actual_video_qc.json"
                failure.write_text(json.dumps({
                    "notes": padding, "status": "failed",
                    "finding": "首帧已经入口，拦选动作没有发生。",
                }, ensure_ascii=False), encoding="utf-8")
                library.build_library(case.parent.parent, index.parent, case.parent.parent / "chat", False)
                result = library.search_library(index, query, 5)
                lesson = result["negative_lessons"][0]
                self.assertEqual(lesson["matched_document"]["path"], str(failure))
                self.assertEqual(lesson["qc_files"], [str(failure)])
                self.assertIn("拦选动作没有发生", lesson["matched_document"]["excerpt"])
                self.assertIsNone(result["production_template"])

    def test_cached_block_without_failure_document_does_not_quote_success_as_lesson(self):
        index, _ = self.build_case({"status": "ok", "decision": "allow_generation"})
        with sqlite3.connect(index) as connection:
            connection.execute("UPDATE cases SET quality_status='blocked'")
        result = library.search_library(index, "古街插画试吃多商户群像", 5)
        self.assertEqual(result["negative_lessons"], [])


if __name__ == "__main__":
    unittest.main()
