import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_quality_gate as gate
import validate_creative as creative


class CreativeEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name)
        (self.project / "script.md").write_text("S01 阻止买整份 S02 递样 S03 多摊揭示 S04 老饕回队", encoding="utf-8")
        for name, color in (("source.png", "green"), ("master.png", "seagreen"), ("detail.png", "coral")):
            Image.new("RGB", (32, 32), color).save(self.project / name)
        self.contract = {
            "schema_version": 5, "target_duration_seconds": 30,
            "deliverables": {"script": "script.md"},
            "creative_direction": {"audience_desire": "怕买整份踩雷", "commercial_promise": "一元券，参与品牌免费试吃",
                "scene_promise": "多摊热闹古街", "minimum_reversals": 2,
                "required_scene_actions": ["多摊递样"], "review_file": "review.json"}}
        self.review = {"script": self.asset("script.md"), "decision": "approved", "unresolved_issues": [],
            "editor": {"kind": "independent_agent", "name": "测试审阅者", "most_likely_swipe_away": "重复付钱段", "revision_evidence": "删除第二次付钱，改为下一摊动作"},
            "hook": {"script_id": "S01", "end_seconds": 3, "visible_action": "手挡整份付款递来试样", "viewer_question": "为何拦付钱", "benefit_cue": "先尝再决定"},
            "retention_beats": [], "scene_action_coverage": [{"requirement": "多摊递样", "script_id": "S03", "visible_action": "不同摊主接力递样"}],
            "style_calibration": {"reviewer": {"kind": "independent_agent", "name": "visual-reviewer", "asset_author": "artist", "comparison_method": "source and output at matching subject scale"},
                "references": [{**self.asset("source.png"), "id": "I01", "role": "style_only", "observation": "青绿色块配朱红廊柱"}],
                "source_axes": {axis: "本轴源图具体观察" for axis in creative.AXES}, "originality_plan": "新人物与街道布局", "decision": "approved", "proofs": []}}
        for n, kind in enumerate(("setup", "reversal", "reversal", "payoff"), 1):
            self.review["retention_beats"].append({"id": f"E{n}", "script_id": f"S0{n}", "timestamp_seconds": (n-1)*8,
                "type": kind, "setup_id": f"E{n-1}", "expectation_before": f"原认知{n}", "visible_change": "动作揭示新信息",
                "expectation_after": f"新认知{n}", "consequence": "因此走向下一摊", "next_question": "接下来谁来尝"})
        for role, file in (("master_scene", "master.png"), ("character_detail", "detail.png")):
            record = {"tool_call_id": "synthetic-test-only", "input_assets": [self.asset("source.png")], "output_asset": self.asset(file)}
            record_name = file + ".json"
            (self.project / record_name).write_text(json.dumps(record), encoding="utf-8")
            self.review["style_calibration"]["proofs"].append({**self.asset(file), "role": role,
                "generation_reference_ids": ["I01"], "generation_evidence": self.asset(record_name),
                "comparisons": {axis: {"source_observation": "源图观察", "candidate_observation": "候选观察", "verdict": "pass"} for axis in creative.AXES}})

    def tearDown(self):
        self.temp.cleanup()

    def asset(self, name):
        return {"file": name, "sha256": creative.digest(self.project / name)}

    def save(self):
        (self.project / "review.json").write_text(json.dumps(self.review), encoding="utf-8")
        (self.project / "08_replica_contract.json").write_text(json.dumps(self.contract), encoding="utf-8")

    def check(self, stage="pre-generation"):
        self.save()
        return creative.validate(self.project, self.contract, stage)

    def test_complete_evidence(self):
        self.assertEqual(self.check()["errors"], [])

    def test_style_author_cannot_approve_own_fallback(self):
        self.enable_manual_fallback()
        self.review["style_calibration"]["reviewer"]["name"] = "artist"
        self.assertTrue(any("cannot approve" in error for error in self.check()["errors"]))

    def test_master_pass_does_not_approve_later_character_sheet(self):
        self.contract["deliverables"]["character_sheet"] = "detail.png"
        self.assertTrue(any("every actual character" in error for error in self.check()["errors"]))
        detail = {**self.asset("detail.png"), "identity_and_state_observation": "one character with the agreed costume", "identity_and_state_verdict": "pass",
                  "comparisons": {axis: {"source_observation": "reference detail", "candidate_observation": "candidate detail", "verdict": "pass"} for axis in creative.AXES}}
        self.review["style_calibration"]["production_asset_reviews"] = [detail]
        self.assertEqual(self.check()["errors"], [])
        detail["comparisons"]["character_rendering"]["verdict"] = "fail"
        self.assertTrue(any("character_rendering not approved" in error for error in self.check()["errors"]))

    def test_replaced_reviewed_storyboard_invalidates_visual_approval(self):
        self.contract["clips"] = [{"storyboard_files": ["master.png"]}]
        self.review["style_calibration"]["production_asset_reviews"] = [{
            **self.asset("master.png"), "identity_and_state_observation": "consistent staging", "identity_and_state_verdict": "pass",
            "comparisons": {axis: {"source_observation": "source", "candidate_observation": "sample", "verdict": "pass"} for axis in creative.AXES}}]
        self.assertEqual(self.check()["errors"], [])
        Image.new("RGB", (32, 32), "blue").save(self.project / "master.png")
        self.assertTrue(any("stale sha256" in error for error in self.check()["errors"]))

    def test_pre_visual_allows_no_future_proof_but_not_production(self):
        self.review["style_calibration"].pop("proofs")
        self.review["style_calibration"].pop("decision")
        self.assertEqual(self.check("pre-visual")["errors"], [])
        self.assertTrue(self.check()["errors"])

    def test_changed_script_invalidates_editor_review(self):
        (self.project / "script.md").write_text("S01 改成慢慢付钱", encoding="utf-8")
        self.assertTrue(any("stale sha256" in e for e in self.check()["errors"]))

    def test_self_score_cannot_replace_editor(self):
        self.review["editor"] = {"kind": "author", "score": 100}
        self.assertTrue(self.check()["errors"])

    def test_rejected_or_unresolved_cannot_pass(self):
        for key, value in (("decision", "rejected"), ("unresolved_issues", ["duplicate heroine"])):
            original = self.review[key]
            self.review[key] = value
            self.assertTrue(self.check()["errors"])
            self.review[key] = original

    def test_reversal_needs_setup_and_changed_expectation(self):
        self.review["retention_beats"][1].update(setup_id="missing", expectation_after="原认知2")
        self.assertGreaterEqual(len(self.check()["errors"]), 2)

    def test_scene_promise_cannot_be_empty_garden(self):
        self.review["scene_action_coverage"] = []
        self.assertTrue(any("scene promise" in e for e in self.check()["errors"]))

    def test_generated_proof_cannot_be_reference_itself(self):
        self.review["style_calibration"]["proofs"][0].update(self.asset("source.png"))
        self.assertTrue(any("masquerade" in e for e in self.check()["errors"]))

    def test_style_inputs_and_six_axes_are_required(self):
        proof = self.review["style_calibration"]["proofs"][0]
        proof["generation_reference_ids"] = []
        proof["comparisons"].pop("palette")
        self.assertTrue(self.check()["errors"])

    def test_visual_failure_blocks(self):
        self.review["style_calibration"]["proofs"][0]["comparisons"]["palette"]["verdict"] = "fail"
        self.assertTrue(self.check()["errors"])

    def test_one_image_cannot_fill_both_calibration_roles(self):
        proofs = self.review["style_calibration"]["proofs"]
        proofs[1] = {**proofs[0], "role": "character_detail"}
        self.assertTrue(any("same SHA" in e for e in self.check()["errors"]))

    def test_static_style_cannot_silently_replace_user_source(self):
        self.contract["reference_source"] = {"kind": "static_images"}
        self.contract["deliverables"]["source_manifest"] = "source.json"
        (self.project / "source.json").write_text(json.dumps({"assets": [{**self.asset("detail.png"), "id": "I01"}]}), encoding="utf-8")
        self.assertTrue(any("static source asset identity" in e for e in self.check()["errors"]))

    def test_generation_evidence_is_a_real_bound_record(self):
        proof = self.review["style_calibration"]["proofs"][0]
        proof["generation_evidence"] = "声称已经生成，不是证据"
        self.assertTrue(self.check()["errors"])
        record = {"tool_call_id": "test", "input_assets": [], "output_asset": self.asset("source.png")}
        (self.project / "wrong_record.json").write_text(json.dumps(record), encoding="utf-8")
        proof["generation_evidence"] = self.asset("wrong_record.json")
        self.assertGreaterEqual(len(self.check()["errors"]), 2)

    def enable_manual_fallback(self):
        failures = {"attempts": [
            {"status": "failed", "output_received": False, "error": "source-image endpoint unavailable"},
            {"status": "failed", "output_received": False, "error": "source-image endpoint unavailable"},
        ]}
        (self.project / "failures.json").write_text(json.dumps(failures), encoding="utf-8")
        (self.project / "style-brief.json").write_text(json.dumps({"axes": "manual observations"}), encoding="utf-8")
        calibration = self.review["style_calibration"]
        calibration["manual_observation_fallback"] = {
            "reason": "source-image endpoint failed twice without an output",
            "source_reference_ids": ["I01"],
            "failure_evidence": self.asset("failures.json"),
            "manual_style_brief": self.asset("style-brief.json"),
        }
        for proof in calibration["proofs"]:
            proof["generation_reference_ids"] = []
            record = {
                "tool_call_id": "text-only-tool-call",
                "input_mode": "manual_observation_fallback",
                "manual_reference_ids": ["I01"],
                "manual_style_brief": calibration["manual_observation_fallback"]["manual_style_brief"],
                "input_assets": [],
                "output_asset": {"file": proof["file"], "sha256": proof["sha256"]},
            }
            record_name = proof["file"] + ".fallback.json"
            (self.project / record_name).write_text(json.dumps(record), encoding="utf-8")
            proof["generation_evidence"] = self.asset(record_name)

    def test_manual_observation_fallback_requires_real_failure_evidence(self):
        self.enable_manual_fallback()
        self.assertEqual(self.check()["errors"], [])
        (self.project / "failures.json").write_text(json.dumps({"attempts": []}), encoding="utf-8")
        self.assertTrue(any("at least two failed" in error for error in self.check()["errors"]))

    def test_manual_observation_fallback_cannot_claim_source_input(self):
        self.enable_manual_fallback()
        proof = self.review["style_calibration"]["proofs"][0]
        proof["generation_reference_ids"] = ["I01"]
        self.assertTrue(any("cannot claim direct" in error for error in self.check()["errors"]))

    def test_gate_stages_and_stale_review(self):
        self.save()
        ok = {"status": "ok", "errors": [], "warnings": []}
        with patch.object(gate.validate_package, "validate", return_value=ok), patch.object(gate.analyze_script, "analyze", return_value=ok):
            self.assertEqual(gate.run_gate(self.project, "pre-visual")["decision"], "allow_visual_tests")
            result = gate.run_gate(self.project, "pre-generation")
            self.assertEqual(result["decision"], "allow_generation")
            (self.project / "script.md").write_text("changed S01", encoding="utf-8")
            changed = gate.run_gate(self.project, "pre-generation")
            self.assertEqual(changed["decision"], "block_generation")
            self.assertNotEqual(result["input_fingerprint"], changed["input_fingerprint"])

    def test_legacy_default_does_not_authorize(self):
        self.contract["schema_version"] = 4
        self.save()
        ok = {"status": "ok", "errors": [], "warnings": []}
        with patch.object(gate.validate_package, "validate", return_value=ok), patch.object(gate.analyze_script, "analyze", return_value=ok):
            self.assertEqual(gate.run_gate(self.project, "pre-generation")["decision"], "block_generation")
            self.assertEqual(gate.run_gate(self.project, "pre-generation", audit_legacy=True)["decision"], "audit_only")


if __name__ == "__main__":
    unittest.main()
