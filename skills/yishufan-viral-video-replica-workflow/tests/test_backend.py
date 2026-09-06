from __future__ import annotations

import importlib.util
import json
import struct
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


prepare = load_module("prepare_reference", "prepare_reference.py")
configure = load_module("configure_asr", "configure_asr.py")
validator = load_module("validate_package", "validate_package.py")
script_analyzer = load_module("analyze_script", "analyze_script.py")
render_validator = load_module("validate_render", "validate_render.py")
delivery_validator = load_module("validate_delivery", "validate_delivery.py")
transcript_validator = load_module("validate_transcript", "validate_transcript.py")
director_validator = load_module("validate_director_qc", "validate_director_qc.py")
quality_gate = load_module("run_quality_gate", "run_quality_gate.py")
final_validator = load_module("validate_final_render", "validate_final_render.py")
audio = load_module("extract_reference_audio", "extract_reference_audio.py")


class PrepareReferenceTests(unittest.TestCase):
    def test_parse_range(self):
        self.assertEqual(prepare.parse_range("00:08-00:13"), ("00:08", "00:13"))

    def test_compare_segments_marks_difference(self):
        rows = prepare.compare_segments(
            [{"start": 0, "end": 1, "text": "你好"}],
            [{"start": 0, "end": 1, "text": "你号"}],
        )
        self.assertEqual(rows[0]["status"], "需复核")

    def test_compare_segments_accepts_punctuation_difference(self):
        rows = prepare.compare_segments(
            [{"start": 0, "end": 1, "text": "你好！"}],
            [{"start": 0, "end": 1, "text": "你好"}],
        )
        self.assertEqual(rows[0]["status"], "一致")


class ConfigureTests(unittest.TestCase):
    def test_update_lines_replaces_without_duplicate(self):
        updated = configure.update_lines(
            "GROQ_API_KEY=old\nDASHSCOPE_API_KEY=before\n",
            {"DASHSCOPE_API_KEY": "after", "DASHSCOPE_ENDPOINT": "https://example.test/v1"},
        )
        self.assertEqual(updated.count("DASHSCOPE_API_KEY="), 1)
        self.assertIn("DASHSCOPE_API_KEY=after", updated)
        self.assertIn("GROQ_API_KEY=old", updated)


class AudioExtractionTests(unittest.TestCase):
    def test_parse_time_formats(self):
        self.assertEqual(audio.parse_time("5.5"), 5.5)
        self.assertEqual(audio.parse_time("01:05.5"), 65.5)
        self.assertEqual(audio.parse_time("01:01:05"), 3665.0)

    def test_ffmpeg_command_keeps_original_mix_quality(self):
        command = audio.build_ffmpeg_command(Path("in.mp4"), Path("out.mp3"), 5.5, 4.5)
        self.assertIn("0:a:0", command)
        self.assertIn("48000", command)
        self.assertIn("320k", command)


class PackageValidatorTests(unittest.TestCase):
    @staticmethod
    def write_fake_png(path: Path, width: int = 1080, height: int = 1920) -> None:
        import zlib

        path.parent.mkdir(parents=True, exist_ok=True)
        def chunk(kind, data):
            return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        path.write_bytes(
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress((b"\x00" + b"\x00" * width) * height))
            + chunk(b"IEND", b"")
        )

    def build_project(self, project: Path) -> dict:
        files = {
            "00_source_manifest.json": json.dumps({"sha256": "source-hash", "duration_seconds": 40.7}),
            "01_reference_analysis.md": "原片节拍账本：R01 责问；R02 电视反转；R03 结尾循环。",
            "02_product_facts.md": "商品事实",
            "02_visual_lock.md": (
                "STYLE_LOCK_V1\n产品不可变：外形、比例、颜色、材质、结构、Logo。\n"
                "宋代写实电影光影，低饱和金棕色，真实材质"
            ),
            "03_structure_mapping.md": (
                "R01 → S01 → P01 → clip01_01.png\n"
                "R02 → S02 → P02 → clip02_01_银泰中心扇面.png\n"
                "R03 → S03 → P03 → clip03_01.png\n"
            ),
            "04_script.md": (
                "| 时间 | ID | 画面与对白 |\n"
                "|---|---|---|\n"
                "| 0-15 | S01/P01 | 秦始皇：\"责问六国。\" |\n"
                "| 15-30 | S02/P02 | 秦始皇：\"这是我新买的电视，银泰中心。\" |\n"
                "| 30-40.7 | S03/P03 | 兵马俑：\"结尾循环。\" |\n"
            ),
            "05_prompts.md": (
                "## Clip 01\nSTYLE_LOCK_V1 宋代写实电影光影，低饱和金棕色，真实材质 "
                "product_front.png character_sheet.png clip01_01.png P01 责问六国 ref_music.mp3 不换其他音乐\n"
                "## Clip 02\nSTYLE_LOCK_V1 宋代写实电影光影，低饱和金棕色，真实材质 "
                "product_front.png character_sheet.png clip02_01_银泰中心扇面.png P02 "
                "这是我新买的电视 银泰中心\n"
                "## Clip 03\nSTYLE_LOCK_V1 宋代写实电影光影，低饱和金棕色，真实材质 "
                "product_front.png character_sheet.png clip03_01.png P03 结尾循环\n"
            ),
            "06_pre_generation_qc.md": "已验图",
            "watch/timeline_0_5s/timeline_manifest.json": json.dumps(
                {
                    "duration_seconds": 40.7,
                    "interval_seconds": 0.5,
                    "frame_count": 82,
                    "last_timestamp_seconds": 40.5,
                }
            ),
            "audio/ref_music.mp3": "audio",
        }
        for relative, content in files.items():
            path = project / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        for relative in (
            "assets/product_front.png",
            "character/character_sheet.png",
            "storyboard/clip01_01.png",
            "storyboard/clip02_01_银泰中心扇面.png",
            "storyboard/clip03_01.png",
        ):
            self.write_fake_png(project / relative)

        contract = {
            "schema_version": 4,
            "mode": "高保真视觉复刻",
            "brief_alignment": {
                "requested_mode": "高保真视觉复刻",
                "resolved_mode": "高保真视觉复刻",
                "requested_duration_seconds": 40.7,
                "ai_table_requested": True,
                "production_scope": "ai_table_handoff",
            },
            "source_sha256": "source-hash",
            "target_duration_seconds": 40.7,
            "deliverables": {
                "source_manifest": "00_source_manifest.json",
                "analysis": "01_reference_analysis.md",
                "facts": "02_product_facts.md",
                "visual_lock": "02_visual_lock.md",
                "mapping": "03_structure_mapping.md",
                "script": "04_script.md",
                "qc": "06_pre_generation_qc.md",
                "character_sheet": "character/character_sheet.png",
                "timeline_manifest": "watch/timeline_0_5s/timeline_manifest.json",
            },
            "evidence_review": {
                "fixed_timeline_manual_reviewed": True,
                "reviewed_frame_count": 82,
                "reviewed_last_timestamp_seconds": 40.5,
            },
            "clips": [
                {
                    "id": "clip01",
                    "start_seconds": 0,
                    "end_seconds": 15,
                    "prompt_file": "05_prompts.md",
                    "prompt_marker": "## Clip 01",
                    "storyboard_files": ["storyboard/clip01_01.png"],
                },
                {
                    "id": "clip02",
                    "start_seconds": 15,
                    "end_seconds": 30,
                    "prompt_file": "05_prompts.md",
                    "prompt_marker": "## Clip 02",
                    "storyboard_files": ["storyboard/clip02_01_银泰中心扇面.png"],
                },
                {
                    "id": "clip03",
                    "start_seconds": 30,
                    "end_seconds": 40.7,
                    "prompt_file": "05_prompts.md",
                    "prompt_marker": "## Clip 03",
                    "storyboard_files": ["storyboard/clip03_01.png"],
                },
            ],
            "continuity": [],
            "reference_beats": [
                {
                    "reference_id": "R01",
                    "script_id": "S01",
                    "prompt_id": "P01",
                    "clip_id": "clip01",
                    "source_start_seconds": 0,
                    "source_end_seconds": 12,
                    "target_start_seconds": 0,
                    "target_end_seconds": 15,
                    "storyboard_file": "storyboard/clip01_01.png",
                    "required_terms": ["责问六国"],
                },
                {
                    "reference_id": "R02",
                    "script_id": "S02",
                    "prompt_id": "P02",
                    "clip_id": "clip02",
                    "source_start_seconds": 12,
                    "source_end_seconds": 30,
                    "target_start_seconds": 15,
                    "target_end_seconds": 30,
                    "storyboard_file": "storyboard/clip02_01_银泰中心扇面.png",
                    "required_terms": ["这是我新买的电视"],
                },
                {
                    "reference_id": "R03",
                    "script_id": "S03",
                    "prompt_id": "P03",
                    "clip_id": "clip03",
                    "source_start_seconds": 30,
                    "source_end_seconds": 40.7,
                    "target_start_seconds": 30,
                    "target_end_seconds": 40.7,
                    "storyboard_file": "storyboard/clip03_01.png",
                    "required_terms": ["结尾循环"],
                },
            ],
            "audio_assets": [
                {
                    "file": "audio/ref_music.mp3",
                    "clip_id": "clip01",
                    "source_start_seconds": 5.5,
                    "source_end_seconds": 10,
                    "use_start_seconds": 5.5,
                    "use_end_seconds": 10,
                    "must_use_original_mix": True,
                }
            ],
            "visual_text_requirements": [
                {
                    "storyboard_file": "storyboard/clip02_01_银泰中心扇面.png",
                    "clip_id": "clip02",
                    "exact_text": "银泰中心",
                    "manual_visual_verified": True,
                }
            ],
            "production_design": {
                "product_identity": {
                    "reference_assets": [
                        {
                            "file": "assets/product_front.png",
                            "sha256": validator.file_hash(project / "assets/product_front.png"),
                            "role": "front",
                        }
                    ],
                    "locked_features": {
                        "shape": "16:9矩形电视外框",
                        "proportion": "屏幕与窄边框比例固定",
                        "color": "深黑色边框",
                        "material": "哑光金属边框与玻璃屏幕",
                        "structure": "正面屏幕与底部支架不变",
                        "logo": "只保留原图可见Logo，不新增文字",
                    },
                    "unknown_view_policy": "do_not_invent",
                },
                "visual_style": {
                    "lock_id": "STYLE_LOCK_V1",
                    "lighting": "宋代室内自然窗光与烛光",
                    "color_palette": "低饱和金棕色",
                    "composition": "人物与产品保持清晰的前中景关系",
                    "lens_and_camera": "写实电影镜头，运动服务于人物动作",
                    "character_rules": "秦始皇身份、服装和身体比例连续",
                    "environment_rules": "宋代写实空间，不引入无关现代霓虹",
                    "image_texture": "真实材质，避免廉价AI塑料感",
                    "reusable_prompt": "宋代写实电影光影，低饱和金棕色，真实材质",
                    "negative_style_constraints": ["赛博朋克", "廉价霓虹粒子"],
                },
                "motion_profile": "reference_led",
                "music_strategy": {"status": "source_locked", "source_file": "audio/ref_music.mp3"},
                "motion_beats": [
                    {
                        "prompt_id": "P01",
                        "script_id": "S01",
                        "clip_id": "clip01",
                        "start_state": "秦始皇面向屏幕站定",
                        "character_action": "抬手责问并向屏幕迈近一步",
                        "product_action": "电视持续播放战报画面",
                        "product_visibility": "visible",
                        "environment_reaction": "殿内众人随抬手动作后退",
                        "camera_motion": "中景轻推后保持轴线",
                        "speed_change": "由静止到快速抬手再停顿",
                        "end_state": "手指停在屏幕前",
                        "transition_trigger": "抬手遮挡画面形成切点",
                        "music_cue": "开场鼓点落在抬手瞬间",
                        "handoff_in": "START",
                        "handoff_out": "HAND_RAISED",
                        "motion_intent": "dynamic",
                        "camera_removal_still_dynamic": True,
                        "motion_level": 2,
                        "complex_action": False,
                        "keyframe_files": [],
                    },
                    {
                        "prompt_id": "P02",
                        "script_id": "S02",
                        "clip_id": "clip02",
                        "start_state": "手仍停在屏幕前",
                        "character_action": "收手抓起遥控器并按下",
                        "product_action": "电视随按键动作熄屏",
                        "product_visibility": "visible",
                        "environment_reaction": "爆炸光消失，殿内恢复暗金光",
                        "camera_motion": "跟手下移到遥控器特写",
                        "speed_change": "快速抓取后短促按压",
                        "end_state": "遥控器按键被压下",
                        "transition_trigger": "屏幕黑场触发硬切",
                        "music_cue": "关机声对齐音乐断点",
                        "handoff_in": "HAND_RAISED",
                        "handoff_out": "SCREEN_OFF",
                        "motion_intent": "dynamic",
                        "camera_removal_still_dynamic": True,
                        "motion_level": 3,
                        "complex_action": False,
                        "keyframe_files": [],
                    },
                    {
                        "prompt_id": "P03",
                        "script_id": "S03",
                        "clip_id": "clip03",
                        "start_state": "黑屏映出众人倒影",
                        "character_action": "兵马俑伸手再次按下播放键",
                        "product_action": "电视重新亮起并重播爆炸",
                        "product_visibility": "visible",
                        "environment_reaction": "爆炸光再次扫过众人面部",
                        "camera_motion": "从遥控器拉回群像",
                        "speed_change": "按键瞬间加速后定格反应",
                        "end_state": "众人再次被爆炸光照亮",
                        "transition_trigger": "爆炸闪光完成循环收束",
                        "music_cue": "末拍撞击音回扣开场",
                        "handoff_in": "SCREEN_OFF",
                        "handoff_out": "END",
                        "motion_intent": "dynamic",
                        "camera_removal_still_dynamic": True,
                        "motion_level": 4,
                        "complex_action": False,
                        "keyframe_files": [],
                    },
                ],
            },
            "creative_room": {
                "reference_mechanism_dna": {
                    "opening_hook": "帝王把屏幕爆炸误认成真实战报",
                    "viewer_question": "他何时发现自己误会了？",
                    "misbelief": "屏幕里的爆炸发生在现实中",
                    "conflict_engine": "帝王权威与现代媒介认知错位",
                    "reversal_mechanism": "遥控器关屏揭示误会",
                    "emotional_payoff": "威严人物被日常物件反制的喜剧释放",
                    "final_memory_point": "节目重播让误会重新循环",
                },
                "candidates": [
                    {
                        "id": f"C{index:02d}",
                        "logline": f"候选{index}用不同关系和动作重演媒介误判",
                        "conflict": f"候选{index}的权力冲突",
                        "character_choice": f"主角主动执行动作{index}",
                        "visible_consequence": f"画面出现可见结果{index}",
                        "unexpected_turn": f"道具意义发生反转{index}",
                        "setup_evidence": f"前段埋下道具证据{index}",
                        "product_role": f"商品承担解决工具{index}",
                        "ending_payoff": f"结尾回扣开头问题{index}",
                        "difference_axes": ["人物关系", f"冲突来源{index}"],
                        "mechanism_signature": f"误判-选择-{index}-后果-循环",
                        "rejection_reason": "不是本轮最清晰可执行的方案" if index != 1 else "",
                        "scorecard": {
                            "hook": 18,
                            "causality": 22,
                            "novelty": 17,
                            "product_causality": 14,
                            "reference_mechanism_fidelity": 9,
                            "generatability": 9,
                            "total": 89,
                            "hard_vetoes": [],
                        },
                    }
                    for index in range(1, 6)
                ],
                "selected_candidate_id": "C01",
                "selection_reason": "保留原片误判循环，同时动作最容易被模型稳定生成",
                "table_read": {
                    "passed": True,
                    "product_removal_breaks_story": True,
                    "dialogue_read_aloud": True,
                    "issues": [],
                    "checks": [
                        {
                            "story_step_id": step_id,
                            "viewer_question": f"观众等待{step_id}如何推进",
                            "beat_change": f"{step_id}带来新的动作或认知",
                            "next_cause": f"{step_id}直接推动下一拍或回扣",
                            "performable_in_seconds": True,
                        }
                        for step_id in ("problem", "choice", "consequence", "resolution")
                    ],
                },
            },
            "narrative_qc": {
                "dramatic_question": "秦始皇如何确认电视中的爆炸是否真实？",
                "world_rule": {"allows_unexplained_magic": False},
                "product_hook_user_requested": True,
                "story_chain": [
                    {
                        "id": "problem",
                        "type": "problem",
                        "script_ids": ["S01"],
                        "actor": "秦始皇",
                        "action": "责问六国任务为何未完成",
                        "product_role": "incentive",
                    },
                    {
                        "id": "choice",
                        "type": "choice",
                        "script_ids": ["S02"],
                        "actor": "秦始皇",
                        "action": "拿起遥控器核验爆炸",
                        "caused_by": "problem",
                        "product_role": "none",
                    },
                    {
                        "id": "consequence",
                        "type": "consequence",
                        "script_ids": ["S02"],
                        "actor": "秦始皇",
                        "action": "按下遥控器",
                        "visible_result": "电视关闭并暴露误会",
                        "caused_by": "choice",
                        "product_role": "none",
                    },
                    {
                        "id": "resolution",
                        "type": "resolution",
                        "script_ids": ["S03"],
                        "actor": "兵马俑",
                        "action": "重新播放节目",
                        "visible_result": "同一爆炸再次出现形成循环",
                        "caused_by": "consequence",
                        "answers": "problem",
                        "product_role": "none",
                    },
                ],
                "resolution": {"script_id": "S03", "answer": "电视循环证明误会还会重演。"},
                "clip_policies": [
                    {"clip_id": "clip01", "delivery_mode": "dialogue_drama"},
                    {"clip_id": "clip02", "delivery_mode": "dialogue_drama"},
                    {"clip_id": "clip03", "delivery_mode": "dialogue_drama"},
                ],
            },
            "dialogue_requirements": [
                {"id": "d1", "clip_id": "clip01", "match_mode": "terms", "required_terms": ["责问六国"]},
                {"id": "d2", "clip_id": "clip02", "match_mode": "exact", "expected_text": "这是我新买的电视"},
                {"id": "d3", "clip_id": "clip03", "match_mode": "terms", "required_terms": ["结尾循环"]},
            ],
            "prop_continuity_requirements": [
                {
                    "id": "remote",
                    "introduction_script_id": "S02",
                    "event_ids": ["remote_pickup", "remote_press", "screen_off"],
                }
            ],
            "director_requirements": {
                "final_memory_step_id": "resolution",
                "performance_arcs": [
                    {
                        "id": "qin_arc",
                        "character": "秦始皇",
                        "states": [
                            {"id": "anger", "script_id": "S01"},
                            {"id": "realization", "script_id": "S02"},
                            {"id": "resolved", "script_id": "S03"},
                        ],
                    }
                ],
            },
            "aitable_handoff": {
                "protected_field_ids": ["video_result"],
                "records": [
                    {
                        "clip_id": "clip01",
                        "write_field_ids": ["prompt", "attachment"],
                        "attachment_filenames": ["character_sheet.png", "clip01_01.png", "ref_music.mp3"],
                    },
                    {
                        "clip_id": "clip02",
                        "write_field_ids": ["prompt", "attachment"],
                        "attachment_filenames": ["character_sheet.png", "clip02_01_银泰中心扇面.png"],
                    },
                    {
                        "clip_id": "clip03",
                        "write_field_ids": ["prompt", "attachment"],
                        "attachment_filenames": ["character_sheet.png", "clip03_01.png"],
                    },
                ],
            },
        }
        (project / validator.CONTRACT_FILE).write_text(
            json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return contract

    def test_valid_dynamic_three_clip_package(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            self.build_project(project)
            result = validator.validate(project)
            self.assertEqual(result["status"], "ok", result["errors"])
            self.assertEqual(result["clip_count"], 3)
            self.assertEqual(result["audio_asset_count"], 1)
            self.assertEqual(result["motion_beat_count"], 3)

    def test_schema_three_remains_readable_with_upgrade_warning(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            contract = self.build_project(project)
            contract["schema_version"] = 3
            contract["deliverables"].pop("visual_lock")
            contract.pop("production_design")
            (project / validator.CONTRACT_FILE).write_text(json.dumps(contract), encoding="utf-8")

            result = validator.validate(project)

            self.assertEqual(result["status"], "ok", result["errors"])
            self.assertTrue(any("schema v3 remains readable" in item for item in result["warnings"]))

    def test_schema_four_rejects_missing_visual_lock(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            contract = self.build_project(project)
            contract["deliverables"].pop("visual_lock")
            (project / validator.CONTRACT_FILE).write_text(json.dumps(contract), encoding="utf-8")

            result = validator.validate(project)

            self.assertTrue(any("deliverable visual_lock" in error for error in result["errors"]))

    def test_schema_four_rejects_camera_only_motion(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            contract = self.build_project(project)
            contract["production_design"]["motion_beats"][0]["camera_removal_still_dynamic"] = False
            (project / validator.CONTRACT_FILE).write_text(json.dumps(contract), encoding="utf-8")

            result = validator.validate(project)

            self.assertTrue(any("camera-only motion" in error for error in result["errors"]))

    def test_visible_product_requires_locked_asset_in_its_prompt(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            contract = self.build_project(project)
            prompt = project / "05_prompts.md"
            prompt.write_text(prompt.read_text(encoding="utf-8").replace("product_front.png", ""), encoding="utf-8")

            result = validator.validate(project)

            self.assertTrue(any("visible product must reference" in error for error in result["errors"]))

    def test_schema_four_rejects_broken_motion_handoff(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            contract = self.build_project(project)
            contract["production_design"]["motion_beats"][1]["handoff_in"] = "UNRELATED_POSE"
            (project / validator.CONTRACT_FILE).write_text(json.dumps(contract), encoding="utf-8")

            result = validator.validate(project)

            self.assertTrue(any("handoff_in" in error for error in result["errors"]))

    def test_schema_four_rejects_complex_action_without_three_keyframes(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            contract = self.build_project(project)
            motion = contract["production_design"]["motion_beats"][0]
            motion["complex_action"] = True
            motion["keyframe_files"] = ["storyboard/clip01_01.png"]
            (project / validator.CONTRACT_FILE).write_text(json.dumps(contract), encoding="utf-8")

            result = validator.validate(project)

            self.assertTrue(any("start, middle, and end keyframes" in error for error in result["errors"]))

    def test_full_video_rejects_unconfirmed_music(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            contract = self.build_project(project)
            contract["brief_alignment"]["production_scope"] = "full_video"
            contract["production_design"]["music_strategy"]["status"] = "pending_selection"
            (project / validator.CONTRACT_FILE).write_text(json.dumps(contract), encoding="utf-8")

            result = validator.validate(project)

            self.assertTrue(any("requires locked or user-confirmed music" in error for error in result["errors"]))

    def test_historical_vector_mechanism_mode_accepts_reviewed_archive_without_timeline(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            contract = self.build_project(project)
            contract["mode"] = "爆款机制迁移"
            contract["brief_alignment"]["requested_mode"] = "爆款机制迁移"
            contract["brief_alignment"]["resolved_mode"] = "爆款机制迁移"
            contract["deliverables"].pop("timeline_manifest")
            manifest_path = project / "00_source_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["source_type"] = "historical_vector_library"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            (project / "00_historical_match.md").write_text("已人工复核历史匹配证据", encoding="utf-8")
            contract["evidence_review"] = {
                "historical_evidence_reviewed": True,
                "historical_match_report": "00_historical_match.md",
            }
            (project / validator.CONTRACT_FILE).write_text(json.dumps(contract), encoding="utf-8")

            result = validator.validate(project)

            self.assertEqual(result["status"], "ok", result["errors"])

    def test_rejects_clip_longer_than_fifteen_seconds(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            contract = self.build_project(project)
            contract["clips"][0]["end_seconds"] = 16
            (project / validator.CONTRACT_FILE).write_text(json.dumps(contract), encoding="utf-8")
            result = validator.validate(project)
            self.assertTrue(any("allowed range is 1-15s" in error for error in result["errors"]))

    def test_rejects_storyboard_filename_missing_from_prompt(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            self.build_project(project)
            prompt = project / "05_prompts.md"
            prompt.write_text(prompt.read_text().replace("clip03_01.png", "未命名图片"), encoding="utf-8")
            result = validator.validate(project)
            self.assertTrue(any("does not reference storyboard filename" in error for error in result["errors"]))

    def test_rejects_storyboard_filename_listed_only_in_another_clip(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            self.build_project(project)
            prompt = project / "05_prompts.md"
            text = prompt.read_text(encoding="utf-8")
            text = text.replace(
                "## Clip 01\ncharacter_sheet.png clip01_01.png P01 责问六国 ref_music.mp3",
                "## Clip 01\ncharacter_sheet.png clip01_01.png clip02_01_银泰中心扇面.png P01 责问六国 ref_music.mp3",
            ).replace(
                "character_sheet.png clip02_01_银泰中心扇面.png P02",
                "character_sheet.png P02",
            )
            prompt.write_text(text, encoding="utf-8")
            result = validator.validate(project)
            self.assertTrue(any("clip02 prompt does not reference storyboard filename" in error for error in result["errors"]))

    def test_rejects_unmapped_reference_beat(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            self.build_project(project)
            analysis = project / "01_reference_analysis.md"
            analysis.write_text(analysis.read_text() + " R04 片尾动作", encoding="utf-8")
            result = validator.validate(project)
            self.assertTrue(any("reference beat ledger is not fully mapped" in error for error in result["errors"]))

    def test_rejects_unreviewed_fixed_timeline(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            contract = self.build_project(project)
            contract["evidence_review"]["fixed_timeline_manual_reviewed"] = False
            (project / validator.CONTRACT_FILE).write_text(json.dumps(contract), encoding="utf-8")
            result = validator.validate(project)
            self.assertTrue(any("fixed_timeline_manual_reviewed" in error for error in result["errors"]))

    def test_rejects_overloaded_high_fidelity_clip(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            contract = self.build_project(project)
            for index in range(4, 7):
                beat = dict(contract["reference_beats"][0])
                beat.update(
                    {
                        "reference_id": f"R{index:02d}",
                        "script_id": f"S{index:02d}",
                        "prompt_id": f"P{index:02d}",
                    }
                )
                contract["reference_beats"].append(beat)
            (project / validator.CONTRACT_FILE).write_text(json.dumps(contract), encoding="utf-8")
            result = validator.validate(project)
            self.assertTrue(any("more than 3 causal beats" in error for error in result["errors"]))

    def test_rejects_reference_audio_without_hard_binding(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            self.build_project(project)
            prompt = project / "05_prompts.md"
            prompt.write_text(prompt.read_text().replace(" 不换其他音乐", ""), encoding="utf-8")
            result = validator.validate(project)
            self.assertTrue(any("must say 不换其他音乐" in error for error in result["errors"]))

    def test_rejects_generic_no_text_conflict_with_whitelist(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            self.build_project(project)
            prompt = project / "05_prompts.md"
            prompt.write_text(
                prompt.read_text().replace("这是我新买的电视 银泰中心", "这是我新买的电视 银泰中心 画面无任何文字"),
                encoding="utf-8",
            )
            result = validator.validate(project)
            self.assertTrue(any("generic no-text prompt" in error for error in result["errors"]))

    def test_rejects_unverified_exact_visual_text(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            contract = self.build_project(project)
            contract["visual_text_requirements"][0]["manual_visual_verified"] = False
            (project / validator.CONTRACT_FILE).write_text(json.dumps(contract), encoding="utf-8")
            result = validator.validate(project)
            self.assertTrue(any("manual_visual_verified=true" in error for error in result["errors"]))

    def test_rejects_aitable_protected_field_write(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            contract = self.build_project(project)
            contract["aitable_handoff"]["records"][0]["write_field_ids"].append("video_result")
            (project / validator.CONTRACT_FILE).write_text(json.dumps(contract), encoding="utf-8")
            result = validator.validate(project)
            self.assertTrue(any("writes protected fields" in error for error in result["errors"]))

    def test_rejects_more_than_nine_total_aitable_attachments(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            contract = self.build_project(project)
            contract["aitable_handoff"]["records"][0]["attachment_filenames"].extend(
                [f"extra_{index}.png" for index in range(7)]
            )
            (project / validator.CONTRACT_FILE).write_text(json.dumps(contract), encoding="utf-8")
            result = validator.validate(project)
            self.assertTrue(any("10 total attachments" in error for error in result["errors"]))

    def test_rejects_missing_requested_aitable_handoff(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            contract = self.build_project(project)
            del contract["aitable_handoff"]
            (project / validator.CONTRACT_FILE).write_text(json.dumps(contract), encoding="utf-8")
            result = validator.validate(project)
            self.assertTrue(any("aitable_handoff is missing" in error for error in result["errors"]))

    def test_rejects_unconfirmed_replica_mode_change(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            contract = self.build_project(project)
            contract["mode"] = "爆款机制迁移"
            contract["brief_alignment"]["resolved_mode"] = "爆款机制迁移"
            contract["brief_alignment"]["mode_change_reason"] = "reference is shorter than requested"
            (project / validator.CONTRACT_FILE).write_text(json.dumps(contract), encoding="utf-8")
            result = validator.validate(project)
            self.assertTrue(any("without explicit user confirmation" in error for error in result["errors"]))

    def test_rejects_story_chain_without_character_choice(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            contract = self.build_project(project)
            contract["narrative_qc"]["story_chain"][1]["type"] = "escalation"
            (project / validator.CONTRACT_FILE).write_text(json.dumps(contract), encoding="utf-8")
            result = validator.validate(project)
            self.assertTrue(any("must include a character choice" in error for error in result["errors"]))

    def test_rejects_fewer_than_five_creative_candidates(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            contract = self.build_project(project)
            contract["creative_room"]["candidates"] = contract["creative_room"]["candidates"][:4]
            (project / validator.CONTRACT_FILE).write_text(json.dumps(contract), encoding="utf-8")
            result = validator.validate(project)
            self.assertTrue(any("at least 5" in error for error in result["errors"]))

    def test_rejects_selected_concept_below_threshold(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            contract = self.build_project(project)
            selected = contract["creative_room"]["candidates"][0]
            selected["scorecard"].update({"novelty": 10, "total": 82})
            (project / validator.CONTRACT_FILE).write_text(json.dumps(contract), encoding="utf-8")
            result = validator.validate(project)
            self.assertTrue(any("at least 85" in error for error in result["errors"]))

    def test_rejects_unresolved_table_read_issue(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            contract = self.build_project(project)
            contract["creative_room"]["table_read"]["issues"] = ["S02到S03缺少动作因果"]
            (project / validator.CONTRACT_FILE).write_text(json.dumps(contract), encoding="utf-8")
            result = validator.validate(project)
            self.assertTrue(any("issues must be an empty array" in error for error in result["errors"]))

    def test_rejects_decorative_product_after_table_read(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            contract = self.build_project(project)
            contract["creative_room"]["table_read"]["product_removal_breaks_story"] = False
            (project / validator.CONTRACT_FILE).write_text(json.dumps(contract), encoding="utf-8")
            result = validator.validate(project)
            self.assertTrue(any("removing the product breaks the story" in error for error in result["errors"]))

    def test_new_package_requires_contract(self):
        with tempfile.TemporaryDirectory() as temp:
            result = validator.validate(Path(temp))
            self.assertEqual(result["status"], "failed")
            self.assertIn(validator.CONTRACT_FILE, result["errors"][0])


class ScriptAnalyzerTests(unittest.TestCase):
    def test_parses_time_when_it_is_the_second_column(self):
        rows = script_analyzer.parse_rows(
            "| ID | 时间 | 画面 | 对白 |\n"
            "|---|---:|---|---|\n"
            "| S01/P01 | 0.00-3.00 | 女主拍桌 | 女主：\"你又说随便？\" |\n"
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["script_ids"], ["S01"])
        self.assertGreater(rows[0]["spoken_characters"], 0)

    def test_ignores_quoted_visual_notes_and_negated_magic(self):
        rows = script_analyzer.parse_rows(
            "| 时间 | 画面 | 普通话对白/嘴型 |\n"
            "|---|---|---|\n"
            "| 0-3 | 插片证明“喜宴被减”，禁止凭空出现道具 | 无对白 |\n"
        )
        self.assertEqual(rows[0]["spoken_characters"], 0)
        self.assertEqual(rows[0]["magic_terms"], [])

    def test_detects_product_fact_written_with_chinese_numerals(self):
        rows = script_analyzer.parse_rows(
            "| 时间 | 画面 | 普通话对白/嘴型 |\n"
            "|---|---|---|\n"
            "| 0-3 | 长姐递券 | 长姐：\"六十九抵一百。\" |\n"
        )
        self.assertTrue(rows[0]["has_product_fact"])

    def test_rejects_overloaded_dialogue_and_unexplained_magic(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            script = (
                "| 时间 | ID | 画面与对白 |\n"
                "|---|---|---|\n"
                "| 0-3 | S01/P01 | 女主：\"凭什么她能嫁到合肥而我不行？\" |\n"
                "| 3-6 | S02/P02 | 蓝紫光带传送；女主：\"九元奶茶、九十五元双人餐。\" |\n"
                "| 6-10 | S03/P03 | 女主：\"还有美容和搏击体验券。\" |\n"
                "| 10-15 | S04/P04 | 女主：\"我终于如愿嫁到合肥了。\" |\n"
            )
            (project / "04_script.md").write_text(script, encoding="utf-8")
            contract = {
                "mode": "商业混合复刻",
                "target_duration_seconds": 15,
                "deliverables": {"script": "04_script.md"},
                "clips": [{"id": "clip01", "start_seconds": 0, "end_seconds": 15}],
                "narrative_qc": {
                    "world_rule": {"allows_unexplained_magic": False},
                    "product_hook_user_requested": False,
                    "clip_policies": [{"clip_id": "clip01", "delivery_mode": "dialogue_drama"}],
                },
            }
            (project / script_analyzer.CONTRACT_FILE).write_text(json.dumps(contract), encoding="utf-8")
            result = script_analyzer.analyze(project)
            self.assertEqual(result["status"], "failed")
            self.assertTrue(any("maximum is 3" in error for error in result["errors"]))
            self.assertTrue(any("hero fact" in error for error in result["errors"]))
            self.assertTrue(any("unexplained magic" in error for error in result["errors"]))

    def test_real_failure_regression_cases(self):
        cases = json.loads((ROOT / "tests" / "fixtures" / "regression_cases.json").read_text(encoding="utf-8"))
        for case in cases:
            with self.subTest(case=case["name"]), tempfile.TemporaryDirectory() as temp:
                project = Path(temp)
                (project / "04_script.md").write_text(case["script"], encoding="utf-8")
                contract = {
                    "mode": "商业混合复刻",
                    "target_duration_seconds": 10 if case["expected_status"] == "ok" else 15,
                    "deliverables": {"script": "04_script.md"},
                    "clips": [
                        {
                            "id": "clip01",
                            "start_seconds": 0,
                            "end_seconds": 10 if case["expected_status"] == "ok" else 15,
                        }
                    ],
                    "narrative_qc": {
                        "world_rule": {"allows_unexplained_magic": case["allows_magic"]},
                        "product_hook_user_requested": case["product_hook_user_requested"],
                        "clip_policies": [
                            {"clip_id": "clip01", "delivery_mode": case["delivery_mode"]}
                        ],
                    },
                }
                (project / script_analyzer.CONTRACT_FILE).write_text(json.dumps(contract), encoding="utf-8")
                result = script_analyzer.analyze(project)
                self.assertEqual(result["status"], case["expected_status"], result["errors"])
                if case["expected_error"]:
                    self.assertTrue(
                        any(case["expected_error"] in error for error in result["errors"]),
                        result["errors"],
                    )


class RenderValidatorTests(unittest.TestCase):
    def test_rejects_short_static_quiet_render(self):
        reference = {
            "duration_seconds": 40.7,
            "width": 1080,
            "height": 1920,
            "scene_change_count": 45,
            "median_halfsecond_rms_db": -11.9,
            "p10_halfsecond_rms_db": -23.55,
            "has_audio": True,
        }
        candidate = {
            "duration_seconds": 37.17,
            "width": 720,
            "height": 1280,
            "scene_change_count": 16,
            "median_halfsecond_rms_db": -16.6,
            "p10_halfsecond_rms_db": -35.59,
            "has_audio": True,
        }
        errors, _ = render_validator.evaluate_metrics(reference, candidate)
        self.assertTrue(any("duration differs" in error for error in errors))
        self.assertTrue(any("scene-change density" in error for error in errors))
        self.assertTrue(any("audio energy" in error for error in errors))
        self.assertTrue(any("music/effect continuity" in error for error in errors))

    def test_accepts_structurally_aligned_render(self):
        reference = {
            "duration_seconds": 40.7,
            "width": 1080,
            "height": 1920,
            "scene_change_count": 45,
            "median_halfsecond_rms_db": -11.9,
            "p10_halfsecond_rms_db": -23.55,
            "has_audio": True,
        }
        candidate = {
            "duration_seconds": 40.5,
            "width": 1080,
            "height": 1920,
            "scene_change_count": 40,
            "median_halfsecond_rms_db": -13.0,
            "p10_halfsecond_rms_db": -26.0,
            "has_audio": True,
        }
        errors, warnings = render_validator.evaluate_metrics(reference, candidate)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])


class DeliveryValidatorTests(unittest.TestCase):
    def test_accepts_ordered_matching_delivery(self):
        contract = {"clips": [{"id": "clip01", "start_seconds": 0, "end_seconds": 10}]}
        outputs = [
            {"clip_id": "clip01", "duration_seconds": 10.1, "width": 720, "height": 1280, "has_audio": True}
        ]
        result = delivery_validator.evaluate_delivery(contract, outputs)
        self.assertEqual(result["status"], "ok", result["errors"])

    def test_rejects_wrong_order_and_duration(self):
        contract = {
            "clips": [
                {"id": "clip01", "start_seconds": 0, "end_seconds": 10},
                {"id": "clip02", "start_seconds": 10, "end_seconds": 20},
            ]
        }
        outputs = [
            {"clip_id": "clip02", "duration_seconds": 10.0, "width": 720, "height": 1280, "has_audio": True},
            {"clip_id": "clip01", "duration_seconds": 15.1, "width": 720, "height": 1280, "has_audio": True},
        ]
        result = delivery_validator.evaluate_delivery(contract, outputs)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("order/identity" in error for error in result["errors"]))
        self.assertTrue(any("duration differs" in error for error in result["errors"]))


class TranscriptValidatorTests(unittest.TestCase):
    def test_accepts_exact_dialogue_inside_time_window(self):
        contract = {
            "dialogue_requirements": [
                {
                    "id": "hook",
                    "clip_id": "clip01",
                    "match_mode": "exact",
                    "expected_text": "凭什么她能嫁到合肥而我不行",
                    "start_seconds": 0,
                    "end_seconds": 3,
                }
            ]
        }
        manifest = {
            "clips": [
                {
                    "clip_id": "clip01",
                    "segments": [
                        {"start_seconds": 0, "end_seconds": 2.8, "text": "凭什么她能嫁到合肥，而我不行？"}
                    ],
                }
            ]
        }
        result = transcript_validator.validate_transcript(contract, manifest)
        self.assertEqual(result["status"], "ok", result["errors"])

    def test_rejects_missing_product_phrase(self):
        contract = {
            "dialogue_requirements": [
                {
                    "id": "opening",
                    "clip_id": "clip01",
                    "match_mode": "contains",
                    "expected_text": "一元好吃小会券",
                }
            ]
        }
        manifest = {
            "clips": [
                {
                    "clip_id": "clip01",
                    "segments": [
                        {"start_seconds": 0, "end_seconds": 3, "text": "让你请其他六国来吃饭"}
                    ],
                }
            ]
        }
        result = transcript_validator.validate_transcript(contract, manifest)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("一元好吃小会券" in error for error in result["errors"]))

    def test_accepts_arabic_digits_for_chinese_single_digit_terms(self):
        contract = {
            "dialogue_requirements": [
                {
                    "id": "rights",
                    "clip_id": "clip01",
                    "match_mode": "terms",
                    "required_terms": ["双人餐", "五选一"],
                }
            ]
        }
        manifest = {
            "clips": [
                {
                    "clip_id": "clip01",
                    "segments": [{"start_seconds": 0, "end_seconds": 2, "text": "双人餐5选1"}],
                }
            ]
        }
        result = transcript_validator.validate_transcript(contract, manifest)
        self.assertEqual(result["status"], "ok", result["errors"])

    def test_accepts_exact_dialogue_inside_merged_asr_segment(self):
        contract = {
            "dialogue_requirements": [
                {
                    "id": "hook",
                    "clip_id": "clip01",
                    "match_mode": "exact",
                    "expected_text": "两人约会就请我吃桃",
                    "start_seconds": 0,
                    "end_seconds": 3,
                }
            ]
        }
        manifest = {
            "clips": [
                {
                    "clip_id": "clip01",
                    "segments": [
                        {
                            "start_seconds": 0.31,
                            "end_seconds": 4.81,
                            "text": "两人约会就请我吃桃，急什么跟我来。",
                        }
                    ],
                }
            ]
        }
        result = transcript_validator.validate_transcript(contract, manifest)
        self.assertEqual(result["status"], "ok", result["errors"])

    def test_rejects_speech_that_only_grazes_canonical_window(self):
        contract = {
            "clips": [{"id": "clip02", "start_seconds": 15, "end_seconds": 30}],
            "dialogue_requirements": [
                {
                    "id": "trial_benefit",
                    "clip_id": "clip02",
                    "match_mode": "exact",
                    "expected_text": "多家品牌免费试吃",
                    "speech_start_seconds": 16.5,
                    "speech_end_seconds": 19.0,
                }
            ],
        }
        manifest = {
            "clips": [
                {
                    "clip_id": "clip02",
                    "segments": [
                        {"start_seconds": 0.03, "end_seconds": 1.99, "text": "多家品牌免费试吃。"}
                    ],
                }
            ]
        }
        result = transcript_validator.validate_transcript(contract, manifest)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("dialogue timing failed" in error for error in result["errors"]))

    def test_order_uses_estimated_time_after_merged_segment(self):
        contract = {
            "clips": [{"id": "clip01", "start_seconds": 0, "end_seconds": 15}],
            "dialogue_requirements": [
                {"id": "wait", "clip_id": "clip01", "match_mode": "exact",
                 "expected_text": "等等", "speech_start_seconds": 0.15, "speech_end_seconds": 0.85},
                {"id": "taste", "clip_id": "clip01", "match_mode": "exact",
                 "expected_text": "先尝再说", "speech_start_seconds": 1.35, "speech_end_seconds": 2.65},
                {"id": "choose", "clip_id": "clip01", "match_mode": "exact",
                 "expected_text": "就选这家", "speech_start_seconds": 6.15, "speech_end_seconds": 7.4},
            ],
        }
        manifest = {"clips": [{"clip_id": "clip01", "segments": [
            {"start_seconds": 0.69, "end_seconds": 3.55, "text": "等等，先尝再说。"},
            {"start_seconds": 6.86, "end_seconds": 7.63, "text": "就选这家。"},
        ]}]}
        result = transcript_validator.validate_transcript(contract, manifest)
        self.assertEqual(result["status"], "ok", result["errors"])

    def test_reports_late_exact_line_as_timing_failure(self):
        contract = {
            "clips": [{"id": "clip02", "start_seconds": 15, "end_seconds": 30}],
            "dialogue_requirements": [
                {"id": "choice", "clip_id": "clip02", "match_mode": "exact",
                 "expected_text": "这下更难选了", "speech_start_seconds": 20.2,
                 "speech_end_seconds": 22.1}
            ],
        }
        manifest = {"clips": [{"clip_id": "clip02", "segments": [
            {"start_seconds": 7.94, "end_seconds": 10.03, "text": "这下更难选了。"}
        ]}]}
        result = transcript_validator.validate_transcript(contract, manifest)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("dialogue timing failed" in error for error in result["errors"]))
        self.assertFalse(any("dialogue requirement failed" in error for error in result["errors"]))

    def test_uses_clip_relative_asr_time_for_later_clip(self):
        contract = {
            "clips": [
                {"id": "clip01", "start_seconds": 0, "end_seconds": 10},
                {"id": "clip02", "start_seconds": 10, "end_seconds": 20},
            ],
            "dialogue_requirements": [
                {
                    "id": "second_clip_line",
                    "clip_id": "clip02",
                    "match_mode": "terms",
                    "required_terms": ["给我上刑", "就这"],
                    "start_seconds": 10,
                    "end_seconds": 20,
                }
            ],
        }
        manifest = {
            "clips": [
                {
                    "clip_id": "clip02",
                    "segments": [
                        {"start_seconds": 0.37, "end_seconds": 3.31, "text": "你是追我还是给我上刑？"},
                        {"start_seconds": 6.57, "end_seconds": 7.39, "text": "就这。"},
                    ],
                }
            ]
        }
        result = transcript_validator.validate_transcript(contract, manifest)
        self.assertEqual(result["status"], "ok", result["errors"])


class DirectorValidatorTests(unittest.TestCase):
    def test_accepts_complete_watch_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            evidence = project / "watch" / "frame.ppm"
            evidence.parent.mkdir(parents=True)
            evidence.write_bytes(b"P6\n1 1\n255\n\x00\x00\x00")
            evidence_file = "watch/frame.ppm"
            contract = {
                "clips": [{"id": "clip01", "start_seconds": 0, "end_seconds": 15}],
                "narrative_qc": {
                    "story_chain": [
                        {"id": "problem"},
                        {"id": "choice"},
                        {"id": "consequence"},
                        {"id": "resolution"},
                    ]
                },
                "director_requirements": {
                    "final_memory_step_id": "resolution",
                    "performance_arcs": [
                        {
                            "id": "hero_arc",
                            "states": [{"id": "start"}, {"id": "turn"}, {"id": "result"}],
                        }
                    ],
                },
                "prop_continuity_requirements": [
                    {"id": "coupon", "event_ids": ["take", "hand", "accept"]}
                ],
                "continuity": [],
            }
            manifest = {
                "timeline_reviews": [
                    {"clip_id": "clip01", "fixed_timeline_manual_reviewed": True, "reviewed_frame_count": 30, "reviewed_last_timestamp_seconds": 14.5}
                ],
                "story_steps": [
                    {"id": "problem", "timestamp_seconds": 0.5, "observed": True, "observed_action": "发现问题", "evidence_file": evidence_file},
                    {"id": "choice", "timestamp_seconds": 3.5, "observed": True, "observed_action": "作出选择", "evidence_file": evidence_file},
                    {"id": "consequence", "timestamp_seconds": 7.0, "observed": True, "observed_action": "出现后果", "evidence_file": evidence_file},
                    {"id": "resolution", "timestamp_seconds": 12.0, "observed": True, "observed_action": "问题解决", "evidence_file": evidence_file},
                ],
                "performance_arcs": [
                    {
                        "id": "hero_arc",
                        "states": [
                            {"id": "start", "timestamp_seconds": 0.5, "observed": True, "evidence_file": evidence_file},
                            {"id": "turn", "timestamp_seconds": 6.0, "observed": True, "evidence_file": evidence_file},
                            {"id": "result", "timestamp_seconds": 12.0, "observed": True, "evidence_file": evidence_file},
                        ],
                    }
                ],
                "prop_events": [
                    {"prop_id": "coupon", "event_id": "take", "timestamp_seconds": 3.0, "observed": True, "evidence_file": evidence_file},
                    {"prop_id": "coupon", "event_id": "hand", "timestamp_seconds": 4.0, "observed": True, "evidence_file": evidence_file},
                    {"prop_id": "coupon", "event_id": "accept", "timestamp_seconds": 5.0, "observed": True, "evidence_file": evidence_file},
                ],
                "continuity_checks": [],
                "hard_vetoes": [],
                "scores": {
                    "causality": 23,
                    "performance": 18,
                    "reference_mechanism": 13,
                    "product_integration": 14,
                    "generatability": 9,
                    "camera_sound": 8,
                    "fact_accuracy": 5,
                },
            }
            result = director_validator.validate_director_qc(project, contract, manifest)
            self.assertEqual(result["status"], "ok", result["errors"])

    def test_rejects_text_file_disguised_as_image_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            evidence = project / "watch" / "frame.jpg"
            evidence.parent.mkdir(parents=True)
            evidence.write_text("not an image", encoding="utf-8")
            errors = []
            director_validator.evidence_path(project, "watch/frame.jpg", errors, "story_steps[0]")
            self.assertTrue(any("readable image" in error for error in errors), errors)

    def test_rejects_missing_resolution_and_prop_event(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            evidence = project / "watch" / "frame_0001.jpg"
            evidence.parent.mkdir(parents=True)
            evidence.write_text("frame", encoding="utf-8")
            contract = {
                "clips": [{"id": "clip01", "start_seconds": 0, "end_seconds": 15}],
                "narrative_qc": {
                    "story_chain": [
                        {"id": "problem"},
                        {"id": "choice"},
                        {"id": "consequence"},
                        {"id": "resolution"},
                    ]
                },
                "director_requirements": {
                    "final_memory_step_id": "resolution",
                    "performance_arcs": [],
                },
                "prop_continuity_requirements": [
                    {"id": "remote", "event_ids": ["pickup", "press", "screen_off"]}
                ],
                "continuity": [],
            }
            manifest = {
                "timeline_reviews": [
                    {
                        "clip_id": "clip01",
                        "fixed_timeline_manual_reviewed": True,
                        "reviewed_frame_count": 30,
                        "reviewed_last_timestamp_seconds": 14.5,
                    }
                ],
                "story_steps": [
                    {"id": "problem", "timestamp_seconds": 0, "observed": True, "observed_action": "质问", "evidence_file": "watch/frame_0001.jpg"},
                    {"id": "choice", "timestamp_seconds": 3, "observed": True, "observed_action": "按键", "evidence_file": "watch/frame_0001.jpg"},
                    {"id": "consequence", "timestamp_seconds": 6, "observed": True, "observed_action": "黑屏", "evidence_file": "watch/frame_0001.jpg"},
                ],
                "performance_arcs": [],
                "prop_events": [
                    {"prop_id": "remote", "event_id": "pickup", "timestamp_seconds": 3, "observed": True, "evidence_file": "watch/frame_0001.jpg"}
                ],
                "continuity_checks": [],
                "hard_vetoes": [],
                "scores": {
                    "causality": 25,
                    "performance": 20,
                    "reference_mechanism": 15,
                    "product_integration": 15,
                    "generatability": 10,
                    "camera_sound": 10,
                    "fact_accuracy": 5,
                },
            }
            result = director_validator.validate_director_qc(project, contract, manifest)
            self.assertEqual(result["status"], "failed")
            self.assertTrue(any("story step evidence" in error for error in result["errors"]))
            self.assertTrue(any("prop remote events" in error for error in result["errors"]))
            self.assertTrue(any("final memory" in error for error in result["errors"]))


class FinalRenderValidatorTests(unittest.TestCase):
    @staticmethod
    def contract() -> dict:
        return {
            "brief_alignment": {"resolved_duration_seconds": 10},
            "clips": [{"id": "clip01", "start_seconds": 0, "end_seconds": 10}],
            "dialogue_requirements": [
                {
                    "id": "brand_line",
                    "clip_id": "clip01",
                    "match_mode": "exact",
                    "expected_text": "西湖银泰",
                    "start_seconds": 0,
                    "end_seconds": 3,
                }
            ],
        }

    @staticmethod
    def asr_run(model: str, video_sha256: str = "video-hash") -> dict:
        return {
            "model": model,
            "video_sha256": video_sha256,
        }

    @staticmethod
    def human_qc() -> dict:
        return {
            "listened": True,
            "voice_consistency_passed": True,
            "double_voice_absent": True,
            "speech_audible_over_music": True,
            "reviewer": "test reviewer",
            "reviewed_at": "2026-08-28T16:00:00+08:00",
            "confirmed_requirement_ids": [],
            "override_reason": "",
        }

    def test_rejects_wrong_final_duration(self):
        metrics = {"duration_seconds": 15.1, "width": 720, "height": 1280, "has_audio": True}
        errors, _ = final_validator.evaluate_final_metrics(self.contract(), metrics)
        self.assertTrue(any("duration differs" in error for error in errors), errors)

    def test_requires_two_distinct_asr_models_bound_to_final_hash(self):
        manifest = {
            "asr_runs": [self.asr_run("paraformer-v2", "wrong-hash")],
            "human_audio_qc": self.human_qc(),
        }
        result = final_validator.validate_asr_consensus(Path.cwd(), self.contract(), manifest, "video-hash")
        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("at least two" in error for error in result["errors"]), result["errors"])

    def test_asr_disagreement_requires_audited_human_override(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            evidence = {
                "source": {"sha256": "video-hash"},
                "transcripts": {
                    "paraformer-v2": [{"start": 0, "end": 2, "text": "西湖银泰"}],
                    "paraformer-v1": [{"start": 0, "end": 2, "text": "西湖一泰"}],
                },
            }
            evidence_path = project / "asr_evidence.json"
            evidence_path.write_text(json.dumps(evidence, ensure_ascii=False), encoding="utf-8")
            manifest = {
                "asr_evidence_file": "asr_evidence.json",
                "asr_evidence_sha256": final_validator.sha256_file(evidence_path),
                "asr_runs": [
                    self.asr_run("paraformer-v2"),
                    self.asr_run("paraformer-v1"),
                ],
                "human_audio_qc": self.human_qc(),
            }
            blocked = final_validator.validate_asr_consensus(project, self.contract(), manifest, "video-hash")
            self.assertEqual(blocked["status"], "failed")
            self.assertTrue(any("models disagree" in error for error in blocked["errors"]), blocked["errors"])

            manifest["human_audio_qc"]["confirmed_requirement_ids"] = ["brand_line"]
            manifest["human_audio_qc"]["override_reason"] = "人工逐句听音确认品牌词为西湖银泰"
            allowed = final_validator.validate_asr_consensus(project, self.contract(), manifest, "video-hash")
            self.assertEqual(allowed["status"], "ok", allowed["errors"])


class QualityGateTests(unittest.TestCase):
    def test_missing_contract_returns_structured_block(self):
        with tempfile.TemporaryDirectory() as temp:
            result = quality_gate.run_gate(Path(temp), "pre-generation")
            self.assertEqual(result["decision"], "block_generation")
            self.assertEqual(result["return_to_stage"], "brief")

    def test_valid_legacy_package_is_audit_only(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            PackageValidatorTests().build_project(project)
            result = quality_gate.run_gate(project, "pre-generation", audit_legacy=True)
            self.assertEqual(result["decision"], "audit_only", result["errors"])
            self.assertFalse(result["production_authorized"])

    def test_routes_dialogue_failure_back_to_dialogue_prompt(self):
        errors = ["transcript: opening dialogue requirement failed in clip01; ASR normalized text []"]
        self.assertEqual(quality_gate.return_stage(errors), "dialogue_prompt")

    def test_routes_overloaded_script_back_to_screenplay(self):
        errors = ["screenplay: clip01 contains 8 timed script units; maximum is 3"]
        self.assertEqual(quality_gate.return_stage(errors), "screenplay")

    def test_routes_final_audio_failure_to_audio_qc(self):
        errors = ["final: human_audio_qc.listened must be true"]
        self.assertEqual(quality_gate.return_stage(errors), "final_audio_qc")

    def test_routes_visual_lock_failure_back_to_visual_lock(self):
        errors = ["package: production_design.product_identity.locked_features.logo is required"]
        self.assertEqual(quality_gate.return_stage(errors), "visual_lock")

    def test_routes_motion_failure_back_to_motion_design(self):
        errors = ["package: production_design.motion_beats[1] is camera-only motion"]
        self.assertEqual(quality_gate.return_stage(errors), "motion_design")

    def test_pre_publish_requires_final_manifest_in_every_mode(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            PackageValidatorTests().build_project(project)
            result = quality_gate.run_gate(project, "pre-publish")
            self.assertEqual(result["decision"], "block_publish")
            self.assertTrue(any("final_manifest is required" in error for error in result["errors"]), result["errors"])

if __name__ == "__main__":
    unittest.main()
