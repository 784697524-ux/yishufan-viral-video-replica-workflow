import copy
import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path

from PIL import Image

import test_backend as backend


director = backend.director_validator


class DirectorEvidenceV5Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.project = Path(cls.temp.name)
        cls.contract = {
            "schema_version": 5,
            "creative_direction": {"required_scene_actions": ["多摊递样"]},
            "clips": [
                {"id": "clip01", "start_seconds": 0, "end_seconds": 2},
                {"id": "clip02", "start_seconds": 2, "end_seconds": 4},
            ],
            "narrative_qc": {"story_chain": [{"id": name} for name in ("problem", "choice", "consequence", "resolution")]},
            "director_requirements": {
                "final_memory_step_id": "resolution",
                "performance_arcs": [{"id": "hero", "states": [{"id": name} for name in ("start", "turn", "result")]}],
            },
            "prop_continuity_requirements": [{"id": "pass", "event_ids": ["take", "hand", "accept"]}],
            "continuity": [],
        }
        cls.base = {"timeline_reviews": [], "story_steps": [], "performance_arcs": [],
                    "prop_events": [], "continuity_checks": [], "hard_vetoes": [], "scores": dict(director.SCORE_MAX)}
        reference = cls.project / "source_style.png"
        Image.new("RGB", (48, 48), "#2a795d").save(reference)
        for clip_id, first, second in (("clip01", "red", "blue"), ("clip02", "blue", "green")):
            directory = cls.project / clip_id
            directory.mkdir()
            video = directory / "result.mp4"
            subprocess.run(
                ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"color=c={first}:size=90x160:rate=4:duration=1",
                 "-f", "lavfi", "-i", f"color=c={second}:size=90x160:rate=4:duration=1",
                 "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0,format=yuv420p[out]", "-map", "[out]",
                 "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18", str(video)],
                capture_output=True, check=True, timeout=30,
            )
            subprocess.run(
                ["ffmpeg", "-v", "error", "-i", str(video), "-vf", "fps=fps=2:start_time=0",
                 "-q:v", "3", str(directory / "sample_%02d.jpg")], capture_output=True, check=True, timeout=30,
            )
            subprocess.run(
                ["ffmpeg", "-v", "error", "-i", str(video), "-vf", "select='eq(n,0)+eq(n,7)'",
                 "-vsync", "0", str(directory / "boundary_%02d.png")], capture_output=True, check=True, timeout=30,
            )
            frames = [cls.frame(f"{clip_id}/sample_{index + 1:02d}.jpg", index * 0.5) for index in range(4)]
            cls.base["timeline_reviews"].append({
                "clip_id": clip_id, "video_file": str(video.relative_to(cls.project)),
                "video_sha256": cls.digest(video), "fixed_timeline_manual_reviewed": True,
                "reviewed_frame_count": 4, "reviewed_last_timestamp_seconds": 1.5, "frames": frames,
                "visual_comparisons": {axis: {
                    "reference_file": "source_style.png", "reference_sha256": cls.digest(reference),
                    "evidence_file": f"{clip_id}/sample_01.jpg", "source_observation": "源图为测试青绿平涂色块。",
                    "output_observation": "实片为测试色块；此夹具只验证来源与观察字段，不证明画风。", "verdict": "pass",
                } for axis in director.VISUAL_AXES},
            })
        cls.base["scene_action_checks"] = [{"requirement": "多摊递样", "clip_id": "clip02",
            "evidence_file": "clip02/sample_03.jpg", "observed_action": "测试帧由蓝色块改变为绿色块。", "verdict": "pass"}]
        cls.base["retention_checks"] = [
            {"criterion": "hook_salience", "clip_id": "clip01", "reviewed_start_seconds": 0.0,
             "reviewed_end_seconds": 2.0, "evidence_files": ["clip01/sample_01.jpg", "clip01/sample_04.jpg"],
             "observation": "测试开头两秒由红色切为蓝色，形成清晰可见的状态变化。", "verdict": "pass"},
            {"criterion": "dead_time", "clip_id": "clip01", "reviewed_start_seconds": 0.0,
             "reviewed_end_seconds": 2.0, "evidence_files": ["clip01/sample_01.jpg", "clip01/sample_04.jpg"],
             "observation": "完整网格均有色块状态变化，无未解释的空白停顿。", "verdict": "pass"},
            {"criterion": "dead_time", "clip_id": "clip02", "reviewed_start_seconds": 0.0,
             "reviewed_end_seconds": 2.0, "evidence_files": ["clip02/sample_01.jpg", "clip02/sample_04.jpg"],
             "observation": "完整网格均有色块状态变化，无未解释的空白停顿。", "verdict": "pass"},
        ]

        def observation(name, clip_id, relative, action_field="observed_action"):
            return {"id": name, "clip_id": clip_id, "timestamp_seconds": relative + (2 if clip_id == "clip02" else 0),
                    "observed": True, action_field: "测试色块由红色切到蓝色，画面来源已取证。",
                    "evidence_file": f"{clip_id}/sample_{int(relative * 2) + 1:02d}.jpg"}

        for name, clip, time in (("problem", "clip01", 0), ("choice", "clip01", 1),
                                 ("consequence", "clip02", 0), ("resolution", "clip02", 1.5)):
            cls.base["story_steps"].append(observation(name, clip, time))
        cls.base["performance_arcs"] = [{"id": "hero", "states": [
            observation("start", "clip01", 0, "observed_state"), observation("turn", "clip01", 1, "observed_state"),
            observation("result", "clip02", 1.5, "observed_state"),
        ]}]
        for name, clip, time in (("take", "clip01", 0.5), ("hand", "clip01", 1), ("accept", "clip02", 1.5)):
            event = observation(name, clip, time)
            event.update(prop_id="pass", event_id=name)
            cls.base["prop_events"].append(event)
        cls.base["continuity_checks"] = [{
            "from_clip_id": "clip01", "to_clip_id": "clip02", "passed": True,
            "from_frame": cls.frame("clip01/boundary_02.png", 1.75),
            "to_frame": cls.frame("clip02/boundary_01.png", 0),
            "state_checks": {name: {"from_state": "中央蓝色测试色块保持原位", "to_state": "中央蓝色测试色块保持原位",
                                     "verdict": "consistent", "reason": "测试来源边界相符；不据此证明角色表演。"}
                             for name in ("character", "prop", "action_phase", "screen_direction",
                                          "background_cast", "scene_inventory")},
        }]

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    @staticmethod
    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @classmethod
    def frame(cls, relative, timestamp):
        return {"timestamp_seconds": timestamp, "evidence_file": relative,
                "sha256": cls.digest(cls.project / relative), "observation": "完整竖幅内为可见测试色块，无裁切。"}

    def setUp(self):
        self.manifest = copy.deepcopy(self.base)

    def validate(self):
        return director.validate_director_qc(self.project, self.contract, self.manifest)

    def test_accepts_actual_video_bound_complete_grid_and_boundaries(self):
        result = self.validate()
        self.assertEqual(result["status"], "ok", result["errors"])
        self.assertTrue(any("not semantic truth" in text for text in result["warnings"]))

    def test_rejects_true_flags_and_perfect_score_without_media_evidence(self):
        for item in self.manifest["timeline_reviews"]:
            item.pop("video_file")
            item.pop("frames")
        result = self.validate()
        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("video_file" in error for error in result["errors"]))

    def test_rejects_incomplete_grid_despite_self_reported_full_count(self):
        self.manifest["timeline_reviews"][0]["frames"].pop(1)
        result = self.validate()
        self.assertTrue(any("all 4 decoded" in error for error in result["errors"]))

    def test_rejects_wrong_video_or_frame_hash(self):
        review = self.manifest["timeline_reviews"][0]
        review["video_sha256"] = "a" * 64
        review["frames"][0]["sha256"] = "b" * 64
        result = self.validate()
        self.assertTrue(any("video_sha256 does not match" in error for error in result["errors"]))
        self.assertTrue(any("sha256 does not match the evidence frame" in error for error in result["errors"]))

    def test_rejects_real_image_from_wrong_time_even_with_correct_image_hash(self):
        review = self.manifest["timeline_reviews"][0]
        substitute = copy.deepcopy(review["frames"][2])
        substitute["timestamp_seconds"] = 0
        review["frames"][0] = substitute
        result = self.validate()
        self.assertTrue(any("does not match the decoded video frame" in error for error in result["errors"]))

    def test_accepts_rescaled_jpeg_evidence(self):
        path = self.project / "rescaled.jpg"
        with Image.open(self.project / "clip01/sample_01.jpg") as image:
            image.resize((180, 320)).save(path, quality=70)
        self.manifest["timeline_reviews"][0]["frames"][0] = self.frame("rescaled.jpg", 0)
        self.manifest["story_steps"][0]["evidence_file"] = "rescaled.jpg"
        self.manifest["performance_arcs"][0]["states"][0]["evidence_file"] = "rescaled.jpg"
        for comparison in self.manifest["timeline_reviews"][0]["visual_comparisons"].values():
            comparison["evidence_file"] = "rescaled.jpg"
        for check in self.manifest["retention_checks"][:2]:
            check["evidence_files"][0] = "rescaled.jpg"
        result = self.validate()
        self.assertEqual(result["status"], "ok", result["errors"])

    def test_rejects_story_image_not_bound_to_reviewed_video(self):
        self.manifest["story_steps"][0]["evidence_file"] = "clip02/boundary_01.png"
        result = self.validate()
        self.assertTrue(any("must reference a verified frame" in error for error in result["errors"]))

    def test_rejects_missing_boundary_check_even_when_contract_omits_continuity(self):
        self.manifest["continuity_checks"] = []
        result = self.validate()
        self.assertTrue(any("continuity checks" in error for error in result["errors"]))

    def test_rejects_fixed_grid_tail_instead_of_actual_last_frame(self):
        self.manifest["continuity_checks"][0]["from_frame"]["timestamp_seconds"] = 1.5
        result = self.validate()
        self.assertTrue(any("actual last decoded frame time" in error for error in result["errors"]))

    def test_rejects_unresolved_prop_reset_and_hard_veto_despite_perfect_score(self):
        self.manifest["continuity_checks"][0]["state_checks"]["prop"].update(
            from_state="券已交到姑娘左手", to_state="券重新回到商户手中", verdict="mismatch", reason="同一交接状态倒灌"
        )
        self.manifest["hard_vetoes"] = ["同一角色重复领取卡券"]
        result = self.validate()
        self.assertTrue(any("unresolved continuity mismatch" in error for error in result["errors"]))
        self.assertTrue(any("hard vetoes" in error for error in result["errors"]))

    def test_rejects_unchecked_background_population_at_clip_boundary(self):
        self.manifest["continuity_checks"][0]["state_checks"].pop("background_cast")
        result = self.validate()
        self.assertTrue(any("state_checks.background_cast is required" in error for error in result["errors"]))

    def test_rejects_failed_hook_or_dead_time_review(self):
        self.manifest["retention_checks"][0]["verdict"] = "fail"
        self.manifest["retention_checks"][2]["verdict"] = "fail"
        result = self.validate()
        self.assertEqual(sum("unresolved retention failure" in error for error in result["errors"]), 2)

    def test_rejects_empty_frame_observation(self):
        self.manifest["timeline_reviews"][0]["frames"][0]["observation"] = " "
        result = self.validate()
        self.assertTrue(any("observation must describe" in error for error in result["errors"]))

    def test_rejects_missing_actual_video_visual_axis(self):
        self.manifest["timeline_reviews"][1]["visual_comparisons"].pop("palette")
        result = self.validate()
        self.assertTrue(any("visual_comparisons.palette is required" in error for error in result["errors"]))

    def test_rejects_failed_actual_palette_even_with_complete_provenance(self):
        self.manifest["timeline_reviews"][0]["visual_comparisons"]["palette"].update(
            output_observation="生成实片青绿朱红已褪成灰褐，色块对比消失。", verdict="fail"
        )
        result = self.validate()
        self.assertTrue(any("unresolved actual-video visual failure" in error for error in result["errors"]))

    def test_visual_comparison_cannot_use_proof_image_or_another_clips_frame(self):
        self.manifest["timeline_reviews"][0]["visual_comparisons"]["palette"]["evidence_file"] = "source_style.png"
        self.manifest["timeline_reviews"][0]["visual_comparisons"]["texture"]["evidence_file"] = "clip02/sample_01.jpg"
        result = self.validate()
        self.assertEqual(sum("visual_comparisons" in error and "verified timeline frame" in error for error in result["errors"]), 2)

    def test_visual_source_requires_real_hash_and_cannot_be_output_itself(self):
        comparisons = self.manifest["timeline_reviews"][0]["visual_comparisons"]
        comparisons["palette"]["reference_sha256"] = "a" * 64
        comparisons["texture"].update(reference_file="clip01/sample_01.jpg", reference_sha256=self.digest(self.project / "clip01/sample_01.jpg"))
        result = self.validate()
        self.assertTrue(any("reference_sha256 does not match" in error for error in result["errors"]))
        self.assertTrue(any("not itself" in error for error in result["errors"]))

    def test_missing_or_failed_scene_action_cannot_pass(self):
        self.manifest["scene_action_checks"] = []
        result = self.validate()
        self.assertTrue(any("cover every required scene action" in error for error in result["errors"]))
        self.manifest["scene_action_checks"] = copy.deepcopy(self.base["scene_action_checks"])
        self.manifest["scene_action_checks"][0].update(observed_action="只有三人在单一茶亭，无多摊递样。", verdict="fail")
        result = self.validate()
        self.assertTrue(any("unresolved scene-action failure" in error for error in result["errors"]))

    def test_scene_action_must_reference_its_own_verified_clip_frame(self):
        self.manifest["scene_action_checks"][0]["evidence_file"] = "clip01/sample_01.jpg"
        result = self.validate()
        self.assertTrue(any("scene_action_checks" in error and "verified timeline frame" in error for error in result["errors"]))


if __name__ == "__main__":
    unittest.main()
