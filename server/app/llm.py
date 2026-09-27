from __future__ import annotations

from typing import Any

import httpx

from .llm_config import ChatModelConfig, LLMConfigStore
from .retrieval import transcript_context
from .store import SessionStore


CONTEXT_ERROR_MARKERS = (
    "context length",
    "context_length",
    "maximum context",
    "max context",
    "token limit",
    "too many tokens",
    "input too long",
    "prompt is too long",
    "上下文长度",
    "上下文超限",
)


class LLMRequestError(RuntimeError):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        normalized = detail.lower()
        self.context_length_exceeded = status_code == 413 or any(
            marker in normalized for marker in CONTEXT_ERROR_MARKERS
        )
        super().__init__(f"对话模型调用失败（{status_code}）：{detail}")


class ChatLLM:
    def __init__(self, config_store: LLMConfigStore):
        self.config_store = config_store

    async def _request(
        self,
        config: ChatModelConfig,
        messages: list[dict[str, str]],
        *,
        max_tokens: int | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "model": config.model,
            "messages": messages,
            "temperature": 0.2,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        headers = {
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=90) as client:
            response = await client.post(
                f"{config.base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
        if response.is_error:
            detail = self._error_detail(response)
            raise LLMRequestError(response.status_code, detail)
        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise RuntimeError("对话模型返回格式不兼容，缺少 choices[0].message.content。") from error
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("对话模型返回了空内容。")
        return content.strip()

    @staticmethod
    def _error_detail(response: httpx.Response) -> str:
        try:
            body = response.json()
            if isinstance(body, dict):
                error = body.get("error")
                if isinstance(error, dict) and error.get("message"):
                    return str(error["message"])[:500]
                if isinstance(error, str):
                    return error[:500]
                if body.get("message"):
                    return str(body["message"])[:500]
        except (TypeError, ValueError):
            pass
        return response.text[:500] or "远端接口未返回错误详情。"

    async def test_config(self, config: ChatModelConfig) -> None:
        await self._request(
            config,
            [
                {"role": "system", "content": "你是连接测试助手。"},
                {"role": "user", "content": "只回复 OK"},
            ],
            max_tokens=8,
        )

    async def answer(
        self,
        store: SessionStore,
        session_id: str,
        question: str,
        include_transcript: bool,
    ) -> dict[str, str]:
        config = self.config_store.get()
        if not config.api_key:
            raise RuntimeError("尚未配置对话模型 API Key。")

        history = [
            {"role": item["role"], "content": item["content"]}
            for item in store.get_messages(session_id)
            if item["role"] in {"user", "assistant"}
        ]
        segments = store.get_segments(session_id) if include_transcript else []
        if include_transcript and not segments:
            raise RuntimeError("当前 Session 还没有可发送的逐字稿；请取消勾选后提问。")

        transcript_scope = "full" if include_transcript else "none"
        messages = self._messages(history, question, segments, include_transcript)
        try:
            answer = await self._request(config, messages)
        except LLMRequestError as error:
            if not include_transcript or not error.context_length_exceeded:
                raise
            recent_segments = segments[len(segments) // 2 :]
            retry_messages = self._messages(history, question, recent_segments, True)
            answer = await self._request(config, retry_messages)
            transcript_scope = "recent_half"
        return {"answer": answer, "transcript_scope": transcript_scope}

    @staticmethod
    def _messages(
        history: list[dict[str, str]],
        question: str,
        segments: list[dict[str, Any]],
        include_transcript: bool,
    ) -> list[dict[str, str]]:
        system = (
            "你是学习助手，需要延续同一 Session 中的多轮对话。"
            "不得把猜测冒充视频原文；使用与用户相同的语言，回答清晰简洁。"
        )
        messages: list[dict[str, str]] = [{"role": "system", "content": system}]
        if include_transcript:
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "以下是用户本次明确授权发送的当前 Session 逐字稿。"
                        "回答视频内容时应以此为依据，并尽量引用 [MM:SS-MM:SS] 时间段；"
                        "依据不足时必须说明。\n\n" + transcript_context(segments)
                    ),
                }
            )
        else:
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "用户本次没有授权发送逐字稿。只能依据已有对话和一般知识回答，"
                        "不得声称已查看或引用视频原文。"
                    ),
                }
            )
        messages.extend(history)
        messages.append({"role": "user", "content": question})
        return messages
