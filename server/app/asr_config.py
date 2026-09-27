from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass

from .config import Settings


REGION_ENDPOINTS = {
    "cn-beijing": "wss://dashscope.aliyuncs.com/api-ws/v1/inference",
    "ap-southeast-1": "wss://dashscope-intl.aliyuncs.com/api-ws/v1/inference",
}
ALLOWED_MODELS = {
    "qwen-audio-3.1-asr-flash-streaming",
    "qwen-audio-3.0-asr-flash-streaming",
}


@dataclass(frozen=True)
class QwenASRConfig:
    region: str
    ws_url: str
    model: str
    api_key: str
    terms: str
    use_page_context: bool


class ASRConfigStore:
    """Persist Alibaba Cloud ASR settings outside browser storage and Session archives."""

    def __init__(self, settings: Settings):
        self.path = settings.data_dir / "asr_config.json"
        default_region = next(
            (region for region, endpoint in REGION_ENDPOINTS.items() if endpoint == settings.qwen_asr_ws_url),
            "cn-beijing",
        )
        self._defaults = QwenASRConfig(
            region=default_region,
            ws_url=settings.qwen_asr_ws_url,
            model=settings.qwen_asr_model,
            api_key=settings.dashscope_api_key,
            terms="",
            use_page_context=True,
        )
        self._lock = threading.RLock()

    def get(self) -> QwenASRConfig:
        with self._lock:
            if not self.path.exists():
                return self._defaults
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise RuntimeError("本机阿里云转写配置损坏，请重新保存配置。") from error
            try:
                region = str(payload.get("region") or self._defaults.region)
                return self.validate(
                    QwenASRConfig(
                        region=region,
                        ws_url=REGION_ENDPOINTS.get(region, ""),
                        model=str(payload.get("model") or self._defaults.model),
                        api_key=str(payload.get("api_key") or self._defaults.api_key),
                        terms=str(payload.get("terms") or ""),
                        use_page_context=bool(payload.get("use_page_context", True)),
                    )
                )
            except ValueError as error:
                raise RuntimeError("本机阿里云转写配置无效，请重新保存配置。") from error

    def public(self) -> dict[str, object]:
        config = self.get()
        return {
            "region": config.region,
            "model": config.model,
            "terms": config.terms,
            "use_page_context": config.use_page_context,
            "has_api_key": bool(config.api_key),
            "masked_api_key": "••••••••" if config.api_key else "",
        }

    def candidate(
        self,
        *,
        region: str,
        model: str,
        api_key: str | None,
        terms: str,
        use_page_context: bool,
    ) -> QwenASRConfig:
        current = self.get()
        region = region.strip()
        return self.validate(
            QwenASRConfig(
                region=region,
                ws_url=REGION_ENDPOINTS.get(region, ""),
                model=model,
                api_key=api_key.strip() if api_key and api_key.strip() else current.api_key,
                terms=terms,
                use_page_context=use_page_context,
            )
        )

    def save(self, config: QwenASRConfig) -> dict[str, object]:
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
    def validate(cls, config: QwenASRConfig) -> QwenASRConfig:
        region = config.region.strip()
        if region not in REGION_ENDPOINTS:
            raise ValueError("不支持的阿里云地域。")
        model = config.model.strip()
        if model not in ALLOWED_MODELS:
            raise ValueError("当前只支持 Qwen Audio 3.1/3.0 Streaming 实时模型。")
        api_key = config.api_key.strip()
        if not api_key:
            raise ValueError("DashScope API Key 不能为空。")
        if len(api_key) > 2000:
            raise ValueError("DashScope API Key 过长。")
        terms = config.terms.strip()
        if len(terms) > 400:
            raise ValueError("专业词上下文不能超过 400 个字符。")
        return QwenASRConfig(
            region=region,
            ws_url=REGION_ENDPOINTS[region],
            model=model,
            api_key=api_key,
            terms=terms,
            use_page_context=bool(config.use_page_context),
        )


def qwen_context_text(
    config: QwenASRConfig,
    *,
    page_title: str = "",
    recent_transcript: str = "",
) -> str:
    """Build one bounded input_text context item; the provider limit is 400 characters."""
    parts: list[str] = []
    if config.terms:
        parts.append(f"专业词：{config.terms[:180]}")
    if config.use_page_context and page_title.strip():
        parts.append(f"页面标题：{page_title.strip()[:100]}")
    if config.use_page_context and recent_transcript.strip():
        parts.append(f"最近逐字稿：{recent_transcript.strip()[-100:]}")
    return "\n".join(parts)[:400]


def qwen_vocabulary(terms: str) -> dict[str, int]:
    normalized = terms.replace("；", ",").replace("，", ",").replace("\n", ",")
    values = [item.strip() for item in normalized.split(",") if item.strip()]
    return {item[:100]: 5 for item in values[:50]}
