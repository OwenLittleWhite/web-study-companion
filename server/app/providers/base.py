from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any


EventHandler = Callable[[dict[str, Any]], Awaitable[None]]


class StreamingProvider:
    name = "base"

    def __init__(self, language: str, on_event: EventHandler):
        self.language = language
        self.on_event = on_event

    async def start(self) -> None:
        raise NotImplementedError

    async def feed(self, pcm_s16le: bytes) -> None:
        raise NotImplementedError

    async def finish(self) -> None:
        raise NotImplementedError

    async def update_context(self, context_text: str) -> None:
        return None
