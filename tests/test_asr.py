from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from server.app.asr_config import (
    ASRConfigStore,
    QwenASRConfig,
    qwen_context_text,
    qwen_vocabulary,
)
from server.app.config import Settings
from server.app.providers.qwen import QwenStreamingProvider


class ASRConfigStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.settings = Settings(data_dir=Path(self.temp.name), dashscope_api_key="")
        self.store = ASRConfigStore(self.settings)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_public_defaults_work_without_a_key(self) -> None:
        public = self.store.public()
        self.assertFalse(public["has_api_key"])
        self.assertNotIn("api_key", public)
        self.assertEqual(public["model"], "qwen-audio-3.1-asr-flash-streaming")

    def test_public_config_never_returns_key(self) -> None:
        config = QwenASRConfig(
            region="cn-beijing",
            ws_url="wss://dashscope.aliyuncs.com/api-ws/v1/inference",
            model="qwen-audio-3.1-asr-flash-streaming",
            api_key="test-secret-value",
            terms="ETH Zurich, Robot Learning",
            use_page_context=True,
        )
        public = self.store.save(config)
        self.assertTrue(public["has_api_key"])
        self.assertNotIn("test-secret-value", json.dumps(public))
        self.assertEqual(self.store.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.store.get().api_key, "test-secret-value")

    def test_candidate_keeps_saved_key_and_maps_region_endpoint(self) -> None:
        self.store.save(
            QwenASRConfig(
                "cn-beijing",
                "wss://dashscope.aliyuncs.com/api-ws/v1/inference",
                "qwen-audio-3.0-asr-flash-streaming",
                "saved-key",
                "policy",
                True,
            )
        )
        candidate = self.store.candidate(
            region="ap-southeast-1",
            model="qwen-audio-3.1-asr-flash-streaming",
            api_key=None,
            terms="vision-language model",
            use_page_context=False,
        )
        self.assertEqual(candidate.api_key, "saved-key")
        self.assertIn("dashscope-intl", candidate.ws_url)

    def test_context_is_bounded_and_keeps_terms_title_and_recent_text(self) -> None:
        config = QwenASRConfig(
            "cn-beijing",
            "wss://dashscope.aliyuncs.com/api-ws/v1/inference",
            "qwen-audio-3.1-asr-flash-streaming",
            "key",
            "ETH Zurich, Robot Learning",
            True,
        )
        context = qwen_context_text(
            config,
            page_title="Robot Learning 2026",
            recent_transcript="older words " + "recent phrase " * 20,
        )
        self.assertLessEqual(len(context), 400)
        self.assertIn("Robot Learning", context)
        self.assertIn("页面标题", context)
        self.assertIn("最近逐字稿", context)
        self.assertEqual(qwen_vocabulary("policy, VLM\nreinforcement learning")["VLM"], 5)


class FakeWebSocket:
    def __init__(self, messages: list[dict]):
        self.messages = [json.dumps(message) for message in messages]
        self.sent: list[bytes | str] = []
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.messages:
            raise StopAsyncIteration
        await asyncio.sleep(0)
        return self.messages.pop(0)

    async def send(self, value):
        self.sent.append(value)

    async def close(self, *_args):
        self.closed = True


class QwenStreamingProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_streaming_payload_context_hotwords_and_revisions(self) -> None:
        websocket = FakeWebSocket(
            [
                {"header": {"event": "task-started"}, "payload": {}},
                {
                    "header": {"event": "result-generated"},
                    "payload": {"output": {"sentence": {"text": "vision language", "sentence_end": False}}},
                },
                {
                    "header": {"event": "result-generated"},
                    "payload": {
                        "output": {
                            "sentence": {
                                "text": "vision-language model",
                                "sentence_end": True,
                                "begin_time": 100,
                                "end_time": 900,
                            }
                        }
                    },
                },
                {"header": {"event": "task-finished"}, "payload": {}},
            ]
        )
        events: list[dict] = []

        async def on_event(event: dict) -> None:
            events.append(event)

        config = QwenASRConfig(
            "cn-beijing",
            "wss://example.test/api-ws/v1/inference",
            "qwen-audio-3.1-asr-flash-streaming",
            "secret-key",
            "vision-language model, policy",
            True,
        )
        provider = QwenStreamingProvider(
            config,
            "en",
            on_event,
            context_text="Page title: Robot Learning",
        )
        with patch(
            "server.app.providers.qwen.websockets.connect",
            new=AsyncMock(return_value=websocket),
        ) as connect:
            await provider.start()
            await asyncio.sleep(0)
            await provider.update_context("Recent transcript: robot policy")
            await provider.finish()

        connect.assert_awaited_once()
        self.assertNotIn("secret-key", str(websocket.sent))
        run_task = json.loads(websocket.sent[0])
        parameters = run_task["payload"]["parameters"]
        self.assertEqual(parameters["language_hints"], ["en"])
        self.assertEqual(parameters["vocabulary"]["vision-language model"], 5)
        self.assertIn("Page title", str(run_task["payload"]["input"]))
        self.assertTrue(any(json.loads(item).get("header", {}).get("action") == "continue-task" for item in websocket.sent if isinstance(item, str)))
        partial = next(event for event in events if event["type"] == "transcript.partial")
        final = next(event for event in events if event["type"] == "transcript.final")
        self.assertTrue(partial["revision"])
        self.assertEqual(final["text"], "vision-language model")


if __name__ == "__main__":
    unittest.main()
