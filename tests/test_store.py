from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from server.app.config import PROJECT_ROOT, env_flag, project_path
from server.app.retrieval import retrieve_segments, terms, transcript_context
from server.app.store import SessionStore, format_clock, format_srt, format_vtt


class SessionStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = SessionStore(Path(self.temp.name))
        self.session = self.store.create_session(
            "机器学习课程 / 第一讲", "https://example.com/course", "local-funasr", "zh"
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_append_only_transcript_and_exports(self) -> None:
        first = self.store.add_segment(
            self.session["id"], 0, 1250, "今天介绍梯度下降。", "local-funasr", "zh"
        )
        self.store.add_segment(
            self.session["id"], 1250, 3500, "学习率决定每一步的大小。", "local-funasr", "zh"
        )
        self.assertEqual(first["raw_text"], "今天介绍梯度下降。")
        segments = self.store.get_segments(self.session["id"])
        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[0]["text"], "今天介绍梯度下降。")
        self.assertEqual(segments[0]["final_text"], "今天介绍梯度下降。")

        raw_lines = (self.store.session_folder(self.session["id"]) / "transcript.raw.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        self.assertEqual(len(raw_lines), 2)
        self.assertEqual(json.loads(raw_lines[0])["text"], "今天介绍梯度下降。")

        for output_format in ("md", "txt", "json", "srt", "vtt"):
            content, filename, media_type = self.store.export(self.session["id"], output_format)
            self.assertTrue(content)
            self.assertTrue(filename.endswith(f".{output_format}"))
            self.assertIn("/", media_type)

    def test_messages_summary_and_materialized_files(self) -> None:
        session_id = self.session["id"]
        self.store.add_message(
            session_id,
            "user",
            "什么是梯度下降？",
            include_transcript=True,
            transcript_scope="recent_half",
        )
        self.store.add_message(session_id, "assistant", "逐步减小损失。")
        self.store.set_summary(session_id, "# 总结\n\n核心是优化。")
        self.store.end_session(session_id)
        folder = self.store.session_folder(session_id)
        self.assertTrue((folder / "session.json").exists())
        self.assertTrue((folder / "summary.md").exists())
        self.assertTrue((folder / "conversation.json").exists())
        markdown, _, _ = self.store.export(session_id, "md")
        self.assertNotIn("## 总结", markdown)
        messages = self.store.get_messages(session_id)
        self.assertTrue(messages[0]["include_transcript"])
        self.assertEqual(messages[0]["transcript_scope"], "recent_half")

    def test_list_sessions_reports_archive_state(self) -> None:
        session_id = self.session["id"]
        self.store.add_segment(session_id, 0, 1000, "归档测试。", "local-funasr", "zh")
        self.store.add_message(session_id, "user", "问题")
        self.store.add_message(session_id, "assistant", "回答")
        listed = self.store.list_sessions()
        self.assertEqual(listed[0]["id"], session_id)
        self.assertEqual(listed[0]["segment_count"], 1)
        self.assertEqual(listed[0]["message_count"], 2)

    def test_resume_capture_appends_after_existing_timeline(self) -> None:
        session_id = self.session["id"]
        self.store.add_segment(session_id, 0, 3500, "第一段采集。", "local-funasr", "zh")
        self.store.end_session(session_id)
        self.assertIsNotNone(self.store.get_session(session_id)["ended_at"])

        self.assertEqual(self.store.capture_offset_ms(session_id), 3500)
        resumed = self.store.begin_capture(session_id)
        self.assertIsNone(resumed["ended_at"])

        offset = self.store.capture_offset_ms(session_id)
        self.store.add_segment(
            session_id,
            offset,
            offset + 1200,
            "续采内容。",
            "qwen-cloud",
            "auto",
        )
        segments = self.store.get_segments(session_id)
        self.assertEqual([item["text"] for item in segments], ["第一段采集。", "续采内容。"])
        self.assertEqual(segments[-1]["start_ms"], 3500)

    def test_legacy_resumed_timestamps_are_repaired_without_rewriting_raw_values(self) -> None:
        session_id = self.session["id"]
        self.store.add_segment(session_id, 0, 10_000, "第一轮一。", "qwen-cloud", "zh")
        self.store.add_segment(session_id, 10_000, 20_000, "第一轮二。", "qwen-cloud", "zh")
        self.store.add_segment(session_id, 300, 5_000, "旧版续采一。", "qwen-cloud", "zh")
        self.store.add_segment(session_id, 5_500, 10_000, "旧版续采二。", "qwen-cloud", "zh")
        self.store.add_segment(session_id, 30_000, 35_000, "新版绝对时间。", "qwen-cloud", "zh")

        segments = self.store.get_segments(session_id)
        self.assertEqual([item["start_ms"] for item in segments], [0, 10_000, 20_300, 25_500, 30_000])
        self.assertEqual(segments[2]["stored_start_ms"], 300)
        self.assertTrue(segments[2]["timeline_repaired"])
        self.assertNotIn("stored_start_ms", segments[-1])
        self.assertEqual(self.store.capture_offset_ms(session_id), 35_000)

        raw_lines = (self.store.session_folder(session_id) / "transcript.raw.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        self.assertEqual(json.loads(raw_lines[2])["start_ms"], 300)

    def test_rename_preserves_folder_and_delete_removes_exact_session(self) -> None:
        session_id = self.session["id"]
        untouched = self.store.create_session(
            "另一个 Session", "https://example.com/other", "local-funasr", "zh"
        )
        original_folder = self.store.session_folder(session_id)
        self.store.add_segment(session_id, 0, 1000, "保留的数据。", "local-funasr", "zh")

        renamed = self.store.rename_session(session_id, "重命名后的课程")
        self.assertEqual(renamed["title"], "重命名后的课程")
        self.assertEqual(self.store.session_folder(session_id), original_folder)
        self.assertTrue((original_folder / "transcript.raw.jsonl").exists())

        self.store.delete_session(session_id)
        self.assertFalse(original_folder.exists())
        with self.assertRaises(KeyError):
            self.store.get_session(session_id)
        self.assertEqual(self.store.get_session(untouched["id"])["title"], "另一个 Session")


class RetrievalTests(unittest.TestCase):
    def test_relative_data_path_is_project_relative(self) -> None:
        self.assertEqual(project_path("data"), (PROJECT_ROOT / "data").resolve())

    def test_env_flag_default(self) -> None:
        self.assertTrue(env_flag("COMPANION_TEST_FLAG_THAT_DOES_NOT_EXIST", True))
        self.assertFalse(env_flag("COMPANION_TEST_FLAG_THAT_DOES_NOT_EXIST", False))

    def test_chinese_and_latin_terms(self) -> None:
        extracted = terms("学习率 learning_rate Transformer")
        self.assertIn("学习", extracted)
        self.assertIn("learning_rate", extracted)
        self.assertIn("transformer", extracted)

    def test_retrieval_keeps_matches_and_recent_context(self) -> None:
        segments = [
            {"start_ms": index * 1000, "end_ms": (index + 1) * 1000, "final_text": f"普通内容 {index}"}
            for index in range(50)
        ]
        segments[10]["final_text"] = "这里详细解释梯度下降和学习率"
        selected = retrieve_segments(segments, "梯度下降是什么", max_segments=16)
        self.assertTrue(any("梯度下降" in item["final_text"] for item in selected))
        self.assertTrue(any(item["start_ms"] == 49_000 for item in selected))
        self.assertIn("[00:10-00:11]", transcript_context([segments[10]]))

    def test_time_formats(self) -> None:
        self.assertEqual(format_clock(65_000), "01:05")
        self.assertEqual(format_srt(3_723_004), "01:02:03,004")
        self.assertEqual(format_vtt(3_723_004), "01:02:03.004")


if __name__ == "__main__":
    unittest.main()
