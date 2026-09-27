from __future__ import annotations

from typing import Any

from ..asr_config import QwenASRConfig
from ..config import Settings
from .base import EventHandler, StreamingProvider
from .local_funasr import LocalFunASRProvider
from .qwen import QwenStreamingProvider


def provider_status(settings: Settings, qwen_config: QwenASRConfig) -> dict[str, dict[str, Any]]:
    return {
        "local-funasr": {
            "ready": LocalFunASRProvider.available(),
            "reason": (
                "已检测到 FunASR。"
                if LocalFunASRProvider.available()
                else "本地 FunASR 未安装，请安装 server/requirements-local-asr.txt。"
            ),
        },
        "qwen-cloud": {
            "ready": bool(qwen_config.api_key),
            "reason": (
                f"阿里云实时转写已配置：{qwen_config.model}。"
                if qwen_config.api_key
                else "缺少 DashScope API Key。"
            ),
            "model": qwen_config.model,
            "region": qwen_config.region,
        },
    }


def streaming_provider(
    name: str,
    settings: Settings,
    language: str,
    on_event: EventHandler,
    *,
    qwen_config: QwenASRConfig | None = None,
    context_text: str = "",
) -> StreamingProvider:
    if name == "local-funasr":
        return LocalFunASRProvider(settings, language, on_event)
    if name == "qwen-cloud":
        if qwen_config is None:
            qwen_config = QwenASRConfig(
                region="cn-beijing",
                ws_url=settings.qwen_asr_ws_url,
                model=settings.qwen_asr_model,
                api_key=settings.dashscope_api_key,
                terms="",
                use_page_context=True,
            )
        return QwenStreamingProvider(
            qwen_config,
            language,
            on_event,
            context_text=context_text,
        )
    raise ValueError(f"Unknown ASR provider: {name}")
