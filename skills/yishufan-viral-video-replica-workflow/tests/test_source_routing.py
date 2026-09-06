import json
import struct
import tempfile
import unittest
from pathlib import Path

from PIL import Image

import test_backend as backend


class StaticSourceRoutingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name)
        self.contract = backend.PackageValidatorTests().build_project(self.project)
        self.contract["schema_version"] = 5
        self.contract["creative_room"]["table_read"].update(
            product_removal_observation="删除1元不影响笑点，但失去参与价格的信息。",
            commercial_relevance_evidence="试吃帮助人物在买整份前做选择，结尾承接真实券。",
        )
        self.contract["mode"] = "商业混合复刻"
        self.contract["brief_alignment"].update(
            requested_mode="商业混合复刻", resolved_mode="商业混合复刻"
        )
        self.contract["reference_source"] = {"kind": "static_images"}
        self.contract["deliverables"].pop("timeline_manifest")
        source_path = self.project / "assets/source_style.png"
        Image.new("RGB", (64, 48), "#59795d").save(source_path)
        digest = backend.validator.file_hash(source_path)
        self.source = {
            "source_type": "static_images", "sha256": "source-hash",
            "duration_seconds": None, "audio_present": False,
            "assets": [{"id": "I01", "file": "assets/source_style.png", "sha256": digest, "role": "scene"}],
        }
        self.review = {"assets": [{"id": "I01", "source_sha256": digest, "observation": "石绿底色与赭红局部形成冷暖对照。"}]}
        self.contract["evidence_review"] = {"static_review_file": "static_review.json"}
        for beat in self.contract["reference_beats"]:
            beat.update(source_start_seconds=None, source_end_seconds=None, source_asset_ids=["I01"])

    def tearDown(self):
        self.temp.cleanup()

    def validate(self, stage="pre-generation"):
        (self.project / "00_source_manifest.json").write_text(json.dumps(self.source), encoding="utf-8")
        (self.project / "static_review.json").write_text(json.dumps(self.review), encoding="utf-8")
        (self.project / backend.validator.CONTRACT_FILE).write_text(json.dumps(self.contract), encoding="utf-8")
        return backend.validator.validate(self.project, stage=stage)

    def test_static_source_passes_without_video_timeline_or_asr(self):
        result = self.validate()
        self.assertEqual(result["status"], "ok", result["errors"])

    def test_user_delegated_duration_preserves_the_original_brief(self):
        self.contract["brief_alignment"].update(requested_duration_seconds=None,
            duration_policy="user_delegated", duration_authority="用户原话：时间自定义")
        self.assertEqual(self.validate("pre-visual")["errors"], [])
        self.contract["brief_alignment"]["requested_duration_seconds"] = 10
        self.assertTrue(any("must not erase" in e for e in self.validate()["errors"]))

    def test_handoff_can_wait_until_pre_generation(self):
        self.contract["brief_alignment"]["ai_table_requested"] = True
        self.contract.pop("aitable_handoff", None)
        self.assertEqual(self.validate("pre-visual")["errors"], [])
        self.assertTrue(any("aitable_handoff is missing" in e for e in self.validate()["errors"]))

    def test_schema5_three_concepts_and_evidence_not_score_threshold(self):
        self.contract["creative_room"]["candidates"] = self.contract["creative_room"]["candidates"][:3]
        candidate = self.contract["creative_room"]["candidates"][0]
        self.contract["creative_room"]["selected_candidate_id"] = candidate["id"]
        for row in self.contract["creative_room"]["candidates"]:
            row["rejection_reason"] = "候选对照，测试所需"
        for key in backend.validator.CREATIVE_SCORE_LIMITS:
            candidate["scorecard"][key] = 0
        candidate["scorecard"]["total"] = sum(candidate["scorecard"].get(k, 0) for k in backend.validator.CREATIVE_SCORE_LIMITS)
        self.assertEqual(self.validate()["errors"], [])

    def test_rejects_empty_facts_and_non_image_product_reference(self):
        (self.project / self.contract["deliverables"]["facts"]).write_text(" ", encoding="utf-8")
        product = self.contract["production_design"]["product_identity"]["reference_assets"][0]
        (self.project / product["file"]).write_text("fake image", encoding="utf-8")
        product["sha256"] = backend.validator.file_hash(self.project / product["file"])
        errors = self.validate("pre-visual")["errors"]
        self.assertTrue(any("not an empty file" in e for e in errors))
        self.assertTrue(any("not a decodable image" in e for e in errors))

    def test_pre_visual_does_not_require_future_images_or_prompt_file(self):
        future = {self.contract["deliverables"]["character_sheet"]}
        for clip in self.contract["clips"]:
            future.update(clip["storyboard_files"])
            future.add(clip["prompt_file"])
        for name in future:
            (self.project / name).unlink()
        self.contract["visual_text_requirements"][0]["manual_visual_verified"] = False
        result = self.validate("pre-visual")
        self.assertEqual(result["status"], "ok", result["errors"])
        result = self.validate("pre-generation")
        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("missing clip01 storyboard" in error for error in result["errors"]))

    def test_pre_visual_rejects_escaping_future_asset(self):
        self.contract["deliverables"]["character_sheet"] = "../not-in-project.png"
        result = self.validate("pre-visual")
        self.assertTrue(any("escapes project" in error for error in result["errors"]))

    def test_pre_visual_still_requires_real_source(self):
        (self.project / "assets/source_style.png").unlink()
        result = self.validate("pre-visual")
        self.assertTrue(any("missing static source" in error for error in result["errors"]))

    def test_rejects_fabricated_source_duration_and_timeline(self):
        self.source["duration_seconds"] = 45
        self.contract["deliverables"]["timeline_manifest"] = "watch/timeline_0_5s/timeline_manifest.json"
        self.contract["evidence_review"]["fixed_timeline_manual_reviewed"] = True
        result = self.validate()
        self.assertTrue(any("duration_seconds must be null" in error for error in result["errors"]))
        self.assertTrue(any("must not declare a video timeline" in error for error in result["errors"]))
        self.assertTrue(any("must not declare video field" in error for error in result["errors"]))

    def test_rejects_fabricated_static_beat_time_and_unknown_asset(self):
        self.contract["reference_beats"][0].update(source_start_seconds=0, source_asset_ids=["missing"])
        result = self.validate()
        self.assertTrue(any("must be null for static" in error for error in result["errors"]))
        self.assertTrue(any("source_asset_ids" in error for error in result["errors"]))

    def test_rejects_changed_source_and_stale_review_hash(self):
        self.source["assets"][0]["sha256"] = "a" * 64
        result = self.validate()
        self.assertTrue(any("does not match the static source asset" in error for error in result["errors"]))
        self.assertTrue(any("source_sha256 does not match" in error for error in result["errors"]))

    def test_rejects_empty_or_incomplete_review(self):
        self.review["assets"][0]["observation"] = " "
        result = self.validate()
        self.assertTrue(any("concrete source observation" in error for error in result["errors"]))
        self.review["assets"] = []
        result = self.validate()
        self.assertTrue(any("cover every source asset" in error for error in result["errors"]))

    def test_static_target_beats_still_must_cover_target_and_stay_in_clip(self):
        self.contract["reference_beats"][0]["target_end_seconds"] = 16
        result = self.validate()
        self.assertTrue(any("outside clip01" in error for error in result["errors"]))
        self.assertTrue(any("target timeline gap" in error for error in result["errors"]))

    def test_rejects_header_only_png_at_pre_generation(self):
        path = self.project / self.contract["clips"][0]["storyboard_files"][0]
        path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8 + struct.pack(">II", 1080, 1920))
        result = self.validate()
        self.assertTrue(any(path.name in error for error in result["errors"]))
        self.assertEqual(result["status"], "failed")


if __name__ == "__main__":
    unittest.main()
