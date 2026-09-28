from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


load_dotenv(PROJECT_ROOT / ".env")


def project_path(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def env_flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    host: str = os.getenv("COMPANION_HOST", "127.0.0.1")
    port: int = int(os.getenv("COMPANION_PORT", "8765"))
    data_dir: Path = project_path(os.getenv("COMPANION_DATA_DIR", "data"))
    dashscope_api_key: str = os.getenv("DASHSCOPE_API_KEY", "")
    qwen_asr_ws_url: str = os.getenv(
        "QWEN_ASR_WS_URL", "wss://dashscope.aliyuncs.com/api-ws/v1/inference"
    )
    qwen_asr_model: str = os.getenv("QWEN_ASR_MODEL", "qwen-audio-3.1-asr-flash-streaming")
    qwen_llm_base_url: str = os.getenv(
        "QWEN_LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
    ).rstrip("/")
    qwen_llm_model: str = os.getenv("QWEN_LLM_MODEL", "qwen-plus")
    funasr_model: str = os.getenv("FUNASR_MODEL", "paraformer-zh-streaming")
    funasr_device: str = os.getenv("FUNASR_DEVICE", "cuda:0")
    funasr_preload: bool = env_flag("FUNASR_PRELOAD", False)


settings = Settings()
