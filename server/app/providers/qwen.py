from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

import websockets

from ..asr_config import QwenASRConfig, qwen_vocabulary
from .base import EventHandler, StreamingProvider


class QwenStreamingProvider(StreamingProvider):
    name = "qwen-cloud"

    def __init__(
        self,
        config: QwenASRConfig,
        language: str,
        on_event: EventHandler,
        *,
        context_text: str = "",
    ):
        super().__init__(language, on_event)
        self.config = config
        self.context_text = context_text.strip()[:400]
        self.task_id = uuid.uuid4().hex
        self.websocket: Any = None
        self.receiver: asyncio.Task | None = None
        self.started = asyncio.Event()
        self.finished = asyncio.Event()
        self.failure: Exception | None = None

    async def start(self) -> None:
        if not self.config.api_key:
            raise RuntimeError("缺少 DASHSCOPE_API_KEY，Qwen 云端转写不可用。")
        self.websocket = await websockets.connect(
            self.config.ws_url,
            additional_headers={"Authorization": f"bearer {self.config.api_key}"},
            ping_interval=20,
            ping_timeout=20,
            max_size=4 * 1024 * 1024,
        )
        self.receiver = asyncio.create_task(self._receive_loop())
        parameters: dict[str, Any] = {
            "sample_rate": 16000,
            "format": "pcm",
            "heartbeat": True,
            "semantic_punctuation_enabled": True,
        }
        if self.language in {"zh", "en"}:
            parameters["language_hints"] = [self.language]
        vocabulary = qwen_vocabulary(self.config.terms)
        if vocabulary:
            parameters["vocabulary"] = vocabulary
        input_payload: dict[str, Any] = {}
        if self.context_text:
            input_payload["context"] = self._context(self.context_text)
        await self.websocket.send(
            json.dumps(
                {
                    "header": {"action": "run-task", "task_id": self.task_id, "streaming": "duplex"},
                    "payload": {
                        "task_group": "audio",
                        "task": "asr",
                        "function": "recognition",
                        "model": self.config.model,
                        "parameters": parameters,
                        "input": input_payload,
                    },
                }
            )
        )
        try:
            await asyncio.wait_for(self.started.wait(), timeout=15)
        except TimeoutError as error:
            raise RuntimeError("Qwen ASR 连接成功，但等待 task-started 超时。") from error
        if self.failure:
            raise self.failure

    async def _receive_loop(self) -> None:
        try:
            async for raw in self.websocket:
                message = json.loads(raw)
                header = message.get("header", {})
                event = header.get("event")
                if event == "task-started":
                    self.started.set()
                    await self.on_event(
                        {"type": "provider.ready", "provider": self.name, "model": self.config.model}
                    )
                elif event == "result-generated":
                    sentence = message.get("payload", {}).get("output", {}).get("sentence", {})
                    text = (sentence.get("text") or "").strip()
                    if not text:
                        continue
                    is_final = bool(sentence.get("sentence_end"))
                    await self.on_event(
                        {
                            "type": "transcript.final" if is_final else "transcript.partial",
                            "text": text,
                            "start_ms": sentence.get("begin_time"),
                            "end_ms": sentence.get("end_time"),
                            "revision": not is_final,
                        }
                    )
                elif event == "task-finished":
                    self.finished.set()
                    return
                elif event == "task-failed":
                    self.failure = RuntimeError(header.get("error_message") or "Qwen ASR task failed")
                    self.started.set()
                    self.finished.set()
                    await self.on_event({"type": "capture.error", "error": str(self.failure)})
                    return
        except Exception as error:
            self.failure = error
            self.started.set()
            self.finished.set()
            await self.on_event({"type": "capture.error", "error": f"Qwen ASR 连接异常：{error}"})
        finally:
            self.finished.set()

    async def feed(self, pcm_s16le: bytes) -> None:
        if self.failure:
            raise self.failure
        await self.websocket.send(pcm_s16le)

    @staticmethod
    def _context(text: str) -> list[dict[str, Any]]:
        return [
            {
                "role": "user",
                "content": [{"type": "input_text", "text": text[:400]}],
            }
        ]

    async def update_context(self, context_text: str) -> None:
        context_text = context_text.strip()[:400]
        if not context_text or self.websocket is None or getattr(self.websocket, "closed", False):
            return
        self.context_text = context_text
        await self.websocket.send(
            json.dumps(
                {
                    "header": {
                        "action": "continue-task",
                        "task_id": self.task_id,
                        "streaming": "duplex",
                    },
                    "payload": {"input": {"context": self._context(context_text)}},
                }
            )
        )

    async def finish(self) -> None:
        if self.websocket is None:
            return
        if not self.failure:
            await self.websocket.send(
                json.dumps(
                    {
                        "header": {
                            "action": "finish-task",
                            "task_id": self.task_id,
                            "streaming": "duplex",
                        },
                        "payload": {"input": {}},
                    }
                )
            )
            try:
                await asyncio.wait_for(self.finished.wait(), timeout=15)
            except TimeoutError:
                pass
        await self.websocket.close()
        if self.receiver and not self.receiver.done():
            self.receiver.cancel()
