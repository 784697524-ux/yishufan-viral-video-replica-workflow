import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "viral_library.py"
SPEC = importlib.util.spec_from_file_location("viral_library", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ViralLibraryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name) / "爆款视频图文"
        self.outputs = self.workspace / "outputs"
        self.chat_root = Path(self.temp.name) / ".codex"
        self.library = self.workspace / "viral_library"
        self.outputs.mkdir(parents=True)
        (self.chat_root / "archived_sessions").mkdir(parents=True)

        good = self.outputs / "成功_古典名画双人权益卡"
        self.good = good
        (good / "storyboard").mkdir(parents=True)
        (good / "01_reference_analysis.md").write_text(
            "名画油画世界，情侣求爱，双方用礼物竞争。卡券作为道具改变选择，结尾首尾呼应。",
            encoding="utf-8",
        )
        (good / "04_script.md").write_text(
            "梵高送花失败，另一位追求者送昂贵珠宝，最后双人逛吃卡解决约会预算冲突。",
            encoding="utf-8",
        )
        (good / "storyboard" / "shot01.png").write_bytes(b"png")
        (good / "transcript.txt").write_text("这只是ASR，不是脚本。", encoding="utf-8")
        (good / "uniform_frames").mkdir()
        (good / "uniform_frames" / "frame_001.jpg").write_bytes(b"jpg")
        (good / "00_source_manifest.json").write_text(json.dumps({
            "source_path": "/missing/reference.mp4",
            "sha256": "a" * 64,
        }), encoding="utf-8")

        failed = self.outputs / "失败_名画求爱"
        failed.mkdir()
        (failed / "01_reference_analysis.md").write_text(
            "名画油画，梵高追求蒙娜丽莎，礼物竞争，3秒反转。", encoding="utf-8"
        )
        (failed / "04_script.md").write_text("失败脚本不应被复用。", encoding="utf-8")
        (failed / "17_director_review.md").write_text(
            "block_publish：故事连续性弱，人物表情和镜头语言不到位。", encoding="utf-8"
        )

        session = self.chat_root / "archived_sessions" / "history.jsonl"
        events = [
            {"type": "session_meta", "payload": {"id": "00000000-0000-0000-0000-000000000001", "cwd": str(self.workspace)}},
            {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [
                {"type": "input_text", "text": "艺术范爆款脚本复盘，api_key=example-secret-value，名画求爱反转。"}
            ]}},
        ]
        session.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in events), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_build_search_and_blocked_case_policy(self):
        summary = MODULE.build_library(self.workspace, self.library, self.chat_root, True)
        self.assertEqual(summary["workspace_case_count"], 2)
        self.assertEqual(summary["chat_case_count"], 1)
        self.assertEqual(summary["blocked_case_count"], 1)

        result = MODULE.search_library(
            self.library / "index.sqlite3",
            "双人权益卡，名画油画，梵高追求蒙娜丽莎，礼物竞争反转",
            5,
        )
        self.assertEqual(result["decision"], "matched")
        self.assertIsNotNone(result["production_template"])
        self.assertIn("成功_古典名画双人权益卡", result["production_template"]["title"])
        failed = next(item for item in [result["main_reference"]] + result["alternatives"]
                      if item and "失败_名画求爱" in item["title"])
        self.assertEqual(failed["reuse_scope"], "reference_analysis_only")
        self.assertEqual(failed["script_files"], [])
        self.assertTrue(result["negative_lessons"])
        production = result["production_template"]
        self.assertTrue(production["matched_documents"][0]["excerpt"])
        self.assertNotIn(str(self.good / "transcript.txt"), production["script_files"])
        self.assertNotIn(str(self.good / "uniform_frames" / "frame_001.jpg"), production["storyboard_files"])
        self.assertEqual(production["source_video_path"], "/missing/reference.mp4")
        self.assertFalse(production["source_video_available"])

    def test_chat_secrets_are_redacted(self):
        MODULE.build_library(self.workspace, self.library, self.chat_root, True)
        connection = sqlite3.connect(self.library / "index.sqlite3")
        try:
            chat_text = "\n".join(row[0] for row in connection.execute(
                "SELECT text FROM documents WHERE doc_type='chat_history'"
            ))
        finally:
            connection.close()
        self.assertNotIn("example-secret-value", chat_text)
        self.assertIn("[REDACTED]", chat_text)

    def test_portable_build_omits_chats_and_redacts_local_data(self):
        (self.good / "04_script.md").write_text(
            "爆款脚本参考 /Users/alice/Desktop/private.mp4，联系 test@example.com，fileToken=abcdef123456。",
            encoding="utf-8",
        )
        summary = MODULE.build_library(
            self.workspace, self.library, self.chat_root, False, portable=True
        )
        self.assertTrue(summary["portable"])
        self.assertEqual(summary["workspace_case_count"], 2)
        self.assertEqual(summary["chat_case_count"], 0)
        self.assertEqual(summary["index"], "index.sqlite3")

        connection = sqlite3.connect(self.library / "index.sqlite3")
        try:
            case_rows = list(connection.execute(
                "SELECT root_path,source_video_path,source_video_available,source_kind FROM cases"
            ))
            all_text = "\n".join(row[0] for row in connection.execute("SELECT text FROM documents"))
        finally:
            connection.close()
        self.assertTrue(all(row[0].startswith("case://") for row in case_rows))
        self.assertTrue(all(row[2] == 0 and row[3] == "seed_case" for row in case_rows))
        self.assertNotIn("/Users/", all_text)
        self.assertNotIn("test@example.com", all_text)
        self.assertNotIn("abcdef123456", all_text)
        self.assertIn("[REDACTED]", all_text)
        self.assertNotIn(str(self.workspace), (self.library / "catalog.json").read_text(encoding="utf-8"))
        result = MODULE.search_library(
            self.library / "index.sqlite3", "双人权益卡名画求爱礼物反转", 5
        )
        self.assertIsNotNone(result["production_template"])

    def test_local_build_merges_seed_and_new_cases(self):
        seed_dir = Path(self.temp.name) / "seed"
        MODULE.build_library(self.workspace, seed_dir, self.chat_root, False, portable=True)

        new_workspace = Path(self.temp.name) / "new-workspace"
        new_case = new_workspace / "outputs" / "新视频_亲子周末卡"
        new_case.mkdir(parents=True)
        (new_case / "01_reference_analysis.md").write_text(
            "爆款视频机制：亲子家庭在商场闯关，周末卡作为解决道具，结尾回扣。",
            encoding="utf-8",
        )
        merged_dir = new_workspace / "viral_library"
        summary = MODULE.build_library(
            new_workspace,
            merged_dir,
            self.chat_root,
            False,
            seed_index=seed_dir / "index.sqlite3",
        )
        self.assertEqual(summary["seed_case_count"], 2)
        self.assertEqual(summary["workspace_case_count"], 1)
        self.assertEqual(summary["case_count"], 3)
        result = MODULE.search_library(merged_dir / "index.sqlite3", "亲子周末卡商场闯关", 5)
        self.assertEqual(result["decision"], "matched")
        self.assertIn("新视频_亲子周末卡", result["main_reference"]["title"])

    def test_show_case_returns_archived_documents(self):
        MODULE.build_library(self.workspace, self.library, self.chat_root, False, portable=True)
        connection = sqlite3.connect(self.library / "index.sqlite3")
        try:
            case_id = connection.execute(
                "SELECT case_id FROM cases WHERE title LIKE '%成功_%'"
            ).fetchone()[0]
        finally:
            connection.close()
        result = MODULE.show_case(self.library / "index.sqlite3", case_id)
        self.assertEqual(result["case"]["case_id"], case_id)
        self.assertTrue(any("名画油画世界" in item["text"] for item in result["documents"]))


if __name__ == "__main__":
    unittest.main()
