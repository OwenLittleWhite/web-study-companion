from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from server.app.config import Settings
from server.app.llm import ChatLLM, LLMRequestError
from server.app.llm_config import ChatModelConfig, LLMConfigStore
from server.app.store import SessionStore


class FakeChatLLM(ChatLLM):
    def __init__(self, config_store: LLMConfigStore, responses: list[object]):
        super().__init__(config_store)
        self.responses = responses
        self.calls: list[list[dict[str, str]]] = []

    async def _request(self, config, messages, *, max_tokens=None):
        self.calls.append(messages)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return str(response)


class LLMConfigStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.settings = Settings(data_dir=Path(self.temp.name), dashscope_api_key="")
        self.config_store = LLMConfigStore(self.settings)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_config_is_masked_and_saved_outside_sessions(self) -> None:
        config = ChatModelConfig(
            provider="custom",
            base_url="https://model.example.test/v1/",
            model="study-model",
            api_key="secret-value",
        )
        public = self.config_store.save(config)
        self.assertTrue(public["has_api_key"])
        self.assertNotIn("secret-value", str(public))
        self.assertEqual(self.config_store.get().base_url, "https://model.example.test/v1")
        self.assertEqual(self.config_store.path.parent, Path(self.temp.name))
        self.assertEqual(self.config_store.path.stat().st_mode & 0o777, 0o600)

    def test_candidate_keeps_existing_key_when_input_is_blank(self) -> None:
        self.config_store.save(
            ChatModelConfig("qwen", "https://example.test/v1", "qwen-plus", "saved-key")
        )
        candidate = self.config_store.candidate(
            provider="qwen",
            base_url="https://example.test/v1",
            model="qwen-max",
            api_key=None,
        )
        self.assertEqual(candidate.api_key, "saved-key")
        self.assertEqual(candidate.model, "qwen-max")


class ChatLLMTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        settings = Settings(data_dir=root, dashscope_api_key="test-key")
        self.config_store = LLMConfigStore(settings)
        self.store = SessionStore(root / "sessions-data")
        self.session = self.store.create_session("课程", "https://example.test", "local-funasr", "zh")
        for index, text in enumerate(("第一段", "第二段", "第三段", "第四段")):
            self.store.add_segment(
                self.session["id"], index * 1000, (index + 1) * 1000, text, "local-funasr", "zh"
            )
        self.store.add_message(self.session["id"], "user", "上一问")
        self.store.add_message(self.session["id"], "assistant", "上一答")

    async def asyncTearDown(self) -> None:
        self.temp.cleanup()

    async def test_context_error_retries_once_with_recent_half(self) -> None:
        llm = FakeChatLLM(
            self.config_store,
            [LLMRequestError(400, "maximum context length exceeded"), "缩减后回答"],
        )
        result = await llm.answer(self.store, self.session["id"], "继续问", True)
        self.assertEqual(result["transcript_scope"], "recent_half")
        self.assertEqual(len(llm.calls), 2)
        first_prompt = "\n".join(item["content"] for item in llm.calls[0])
        retry_prompt = "\n".join(item["content"] for item in llm.calls[1])
        self.assertIn("第一段", first_prompt)
        self.assertNotIn("第一段", retry_prompt)
        self.assertIn("第三段", retry_prompt)
        self.assertIn("上一问", retry_prompt)

    async def test_unchecked_request_sends_history_without_transcript(self) -> None:
        llm = FakeChatLLM(self.config_store, ["连续回答"])
        result = await llm.answer(self.store, self.session["id"], "不带稿子", False)
        prompt = "\n".join(item["content"] for item in llm.calls[0])
        self.assertEqual(result["transcript_scope"], "none")
        self.assertIn("上一问", prompt)
        self.assertNotIn("第一段", prompt)

    async def test_second_context_error_is_returned_without_more_retries(self) -> None:
        llm = FakeChatLLM(
            self.config_store,
            [
                LLMRequestError(400, "maximum context length exceeded"),
                LLMRequestError(400, "maximum context length exceeded again"),
                "不应调用第三次",
            ],
        )
        with self.assertRaises(LLMRequestError):
            await llm.answer(self.store, self.session["id"], "继续问", True)
        self.assertEqual(len(llm.calls), 2)
