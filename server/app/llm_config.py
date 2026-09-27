from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlparse

from .config import Settings


@dataclass(frozen=True)
class ChatModelConfig:
    provider: str
    base_url: str
    model: str
    api_key: str


class LLMConfigStore:
    """Persist the global chat-model configuration outside Session archives."""

    allowed_providers = {"qwen", "volcengine", "custom"}

    def __init__(self, settings: Settings):
        self.path = settings.data_dir / "llm_config.json"
        self._defaults = ChatModelConfig(
            provider="qwen",
            base_url=settings.qwen_llm_base_url,
            model=settings.qwen_llm_model,
            api_key=settings.dashscope_api_key,
        )
        self._lock = threading.RLock()

    def get(self) -> ChatModelConfig:
        with self._lock:
            if not self.path.exists():
                return self._defaults
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise RuntimeError("本机对话模型配置损坏，请重新保存配置。") from error
            try:
                return self.validate(
                    ChatModelConfig(
                        provider=str(payload.get("provider") or self._defaults.provider),
                        base_url=str(payload.get("base_url") or self._defaults.base_url),
                        model=str(payload.get("model") or self._defaults.model),
                        api_key=str(payload.get("api_key") or self._defaults.api_key),
                    )
                )
            except ValueError as error:
                raise RuntimeError("本机对话模型配置无效，请重新保存配置。") from error

    def public(self) -> dict[str, object]:
        config = self.get()
        return {
            "provider": config.provider,
            "base_url": config.base_url,
            "model": config.model,
            "has_api_key": bool(config.api_key),
            "masked_api_key": "••••••••" if config.api_key else "",
        }

    def candidate(
        self,
        *,
        provider: str,
        base_url: str,
        model: str,
        api_key: str | None,
    ) -> ChatModelConfig:
        current = self.get()
        return self.validate(
            ChatModelConfig(
                provider=provider,
                base_url=base_url,
                model=model,
                api_key=api_key.strip() if api_key and api_key.strip() else current.api_key,
            )
        )

    def save(self, config: ChatModelConfig) -> dict[str, object]:
        config = self.validate(config)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".json.tmp")
        payload = json.dumps(asdict(config), ensure_ascii=False, indent=2)
        with self._lock:
            temporary.write_text(payload, encoding="utf-8")
            try:
                temporary.chmod(0o600)
            except OSError:
                pass
            os.replace(temporary, self.path)
            try:
                self.path.chmod(0o600)
            except OSError:
                pass
        return self.public()

    @classmethod
    def validate(cls, config: ChatModelConfig) -> ChatModelConfig:
        provider = config.provider.strip().lower()
        if provider not in cls.allowed_providers:
            raise ValueError("不支持的对话服务类型。")
        base_url = config.base_url.strip().rstrip("/")
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username:
            raise ValueError("Domain / Base URL 必须是有效的 HTTP(S) 地址，且不能包含账号信息。")
        if len(base_url) > 2000:
            raise ValueError("Domain / Base URL 过长。")
        model = config.model.strip()
        if not model or len(model) > 200:
            raise ValueError("Model 不能为空且不能超过 200 个字符。")
        api_key = config.api_key.strip()
        if not api_key:
            raise ValueError("API Key 不能为空。")
        if len(api_key) > 2000:
            raise ValueError("API Key 过长。")
        return ChatModelConfig(provider=provider, base_url=base_url, model=model, api_key=api_key)
