from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SessionCreate(BaseModel):
    title: str = Field(default="Untitled page", max_length=500)
    url: str = Field(default="", max_length=4000)
    provider: Literal["local-funasr", "qwen-cloud"] = "local-funasr"
    language: Literal["auto", "zh", "en"] = "auto"


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    include_transcript: bool = True


class SessionRename(BaseModel):
    title: str = Field(min_length=1, max_length=500)


class LLMConfigUpdate(BaseModel):
    provider: Literal["qwen", "volcengine", "custom"] = "qwen"
    base_url: str = Field(min_length=1, max_length=2000)
    model: str = Field(min_length=1, max_length=200)
    api_key: str | None = Field(default=None, max_length=2000)


class ASRConfigUpdate(BaseModel):
    region: Literal["cn-beijing", "ap-southeast-1"] = "cn-beijing"
    model: Literal[
        "qwen-audio-3.1-asr-flash-streaming",
        "qwen-audio-3.0-asr-flash-streaming",
    ] = "qwen-audio-3.1-asr-flash-streaming"
    api_key: str | None = Field(default=None, max_length=2000)
    terms: str = Field(default="", max_length=400)
    use_page_context: bool = True


class TranscriptSegment(BaseModel):
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    text: str = Field(min_length=1)
    provider: str
    language: str = "auto"
    is_final: bool = True
