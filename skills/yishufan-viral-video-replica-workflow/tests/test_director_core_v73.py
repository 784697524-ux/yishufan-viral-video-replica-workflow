import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("director_core_v73", ROOT / "scripts/validate_director_core.py")
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)
sys.path.insert(0, str(ROOT / "scripts"))
import run_quality_gate as GATE


def state(marker):
    return {
        "protagonist_id": "G01",
        "left_hand": marker,
        "right_hand": "empty",
        "prop_holders": "dish:G01-left",
        "position": "first_stall",
        "gaze_target": "third_stall",
        "action_phase": marker,
        "crowd_signature": "three_distinct_groups",
    }


def beat(beat_id, start, end, state_in, state_out, cause, event_id, phase, purpose="development", dialogue=None):
    value = {
        "id": beat_id,
        "start_seconds": start,
        "end_seconds": end,
        "purpose": purpose,
        "caused_by": cause,
        "viewer_question": f"question {beat_id}",
        "new_information": f"new information {beat_id}",
        "visible_action": f"visible action {beat_id}",
        "state_in": copy.deepcopy(state_in),
        "state_out": copy.deepcopy(state_out),
        "action_event": {"id": event_id, "phase": phase},
        "shot": {
            "framing": "medium",
            "primary_character_action": "one readable action",
            "primary_camera_action": "locked camera",
            "camera_purpose": "show the action consequence",
            "transition_trigger": "action completes",
        },
    }
    if dialogue:
        value["dialogue"] = dialogue
    return value


def valid_plan():
    s0, s1, s2, s3, s4, s5, s6 = [state(f"state_{i}") for i in range(7)]
    return {
        "version": "7.3",
        "story_question": "Will the shopper keep exploring after the first taste?",
        "scene_promise": "Three busy tasting stalls in one coherent old street.",
        "commercial_truth_cues": [{
            "start_seconds": 0.25,
            "end_seconds": 4,
            "source": "post_overlay",
            "text": "1元购券参加｜参与品牌试吃免费",
            "supports_beat_ids": ["S01"],
        }],
        "clips": [
            {"clip_id": "clip01", "start_seconds": 0, "end_seconds": 15, "beats": [
                beat("S01", 0, 4, s0, s1, "START", "hook_exchange", "payoff", "hook", {
                    "speaker_mode": "character", "text": "等等，不用付钱，姑娘，先尝再说。"
                }),
                beat("S02", 4, 9, s1, s2, "S01", "first_taste", "payoff", dialogue={
                    "speaker_mode": "character", "text": "就这家！"
                }),
                beat("S03", 9, 15, s2, s3, "S02", "other_taste", "setup"),
            ]},
            {"clip_id": "clip02", "start_seconds": 15, "end_seconds": 30, "beats": [
                beat("S04", 15, 20, s3, s4, "S03", "other_taste", "payoff"),
                beat("S05", 20, 25, s4, s5, "S04", "choice_reversal", "payoff", dialogue={
                    "speaker_mode": "character", "text": "这下，更难选了！"
                }),
                beat("S06", 25, 30, s5, s6, "S05", "walk_payoff", "payoff", dialogue={
                    "speaker_mode": "controlled_voiceover", "text": "合肥高新银泰，一元购券，参加品牌免费试吃。"
                }),
            ]},
        ],
        "required_scene_actions": [
            {"requirement": "handoff", "covered_by_beat_ids": ["S01", "S03"]},
            {"requirement": "two people taste", "covered_by_beat_ids": ["S02", "S04"]},
            {"requirement": "choice changes", "covered_by_beat_ids": ["S05", "S06"]},
        ],
        "ending": {"beat_id": "S06", "visible_resolution": "The shopper walks into the street while another sample lands."},
    }


class DirectorCoreV73Tests(unittest.TestCase):
    def run_plan(self, plan):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            contract = {
                "schema_version": 5,
                "director_core_version": "7.3",
                "director_plan_file": "03_director_plan.json",
                "clips": [{"id": "clip01"}, {"id": "clip02"}],
            }
            (project / "03_director_plan.json").write_text(json.dumps(plan), encoding="utf-8")
            return MOD.validate(project, contract)

    def test_valid_plan_passes(self):
        self.assertEqual(self.run_plan(valid_plan())["status"], "ok")

    def test_hand_state_jump_fails(self):
        plan = valid_plan()
        plan["clips"][0]["beats"][1]["state_in"]["left_hand"] = "different dish"
        self.assertTrue(any("state discontinuity S01->S02" in e for e in self.run_plan(plan)["errors"]))

    def test_duplicate_payoff_fails(self):
        plan = valid_plan()
        plan["clips"][0]["beats"][2]["action_event"]["phase"] = "payoff"
        self.assertTrue(any("duplicate payoff owners" in e for e in self.run_plan(plan)["errors"]))

    def test_character_claim_requires_early_truth_cue(self):
        plan = valid_plan()
        plan["commercial_truth_cues"] = []
        self.assertTrue(any("commercial claim needs an early controlled truth cue" in e for e in self.run_plan(plan)["errors"]))

    def test_more_than_three_beats_per_clip_fails(self):
        plan = valid_plan()
        last = copy.deepcopy(plan["clips"][0]["beats"][-1])
        last["id"] = "S03B"
        last["start_seconds"] = 15
        last["end_seconds"] = 16
        last["caused_by"] = "S03"
        last["action_event"] = {"id": "extra", "phase": "payoff"}
        plan["clips"][0]["beats"].append(last)
        self.assertTrue(any("default maximum is 3" in e for e in self.run_plan(plan)["errors"]))

    def test_missing_cause_fails(self):
        plan = valid_plan()
        plan["clips"][1]["beats"][0]["caused_by"] = "UNKNOWN"
        self.assertTrue(any("must name an earlier beat" in e for e in self.run_plan(plan)["errors"]))

    def test_official_gate_blocks_and_returns_to_director_plan(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            contract = {
                "schema_version": 5,
                "director_core_version": "7.3",
                "director_plan_file": "03_director_plan.json",
                "clips": [{"id": "clip01"}, {"id": "clip02"}],
            }
            plan = valid_plan()
            plan["clips"][1]["beats"][0]["state_in"]["left_hand"] = "jumped state"
            (project / "08_replica_contract.json").write_text(json.dumps(contract), encoding="utf-8")
            (project / "03_director_plan.json").write_text(json.dumps(plan), encoding="utf-8")
            clean = {"status": "ok", "errors": [], "warnings": []}
            with patch.object(GATE.validate_package, "validate", return_value=clean), \
                    patch.object(GATE.analyze_script, "analyze", return_value=clean), \
                    patch.object(GATE.validate_creative, "validate", return_value=clean):
                result = GATE.run_gate(project, "pre-generation")
            self.assertEqual(result["decision"], "block_generation")
            self.assertEqual(result["return_to_stage"], "director_plan")
            self.assertIn("director_core", result["results"])


if __name__ == "__main__":
    unittest.main()
