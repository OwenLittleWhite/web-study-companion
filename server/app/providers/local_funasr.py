from __future__ import annotations

import asyncio
import importlib.util
from typing import Any

from ..config import Settings
from .base import EventHandler, StreamingProvider


class LocalFunASRProvider(StreamingProvider):
    name = "local-funasr"
    _model: Any = None
    _model_name: str | None = None
    _warmed_model_name: str | None = None
    _model_lock = asyncio.Lock()
    _inference_lock = asyncio.Lock()

    def __init__(self, settings: Settings, language: str, on_event: EventHandler):
        super().__init__(language, on_event)
        self.settings = settings
        self.buffer = bytearray()
        self.cache: dict[str, Any] = {}
        self.process_lock = asyncio.Lock()
        self.processed_samples = 0
        self.chunk_samples = 9600  # 600 ms at 16 kHz

    @staticmethod
    def available() -> bool:
        return importlib.util.find_spec("funasr") is not None and importlib.util.find_spec("numpy") is not None

    async def start(self) -> None:
        if not self.available():
            raise RuntimeError(
                "本地 FunASR 尚未安装。执行 pip install -r server/requirements-local-asr.txt 后重启服务。"
            )
        async with self._model_lock:
            if self.__class__._model is None or self.__class__._model_name != self.settings.funasr_model:
                await self.on_event({"type": "provider.loading", "provider": self.name})
                self.__class__._model = await asyncio.to_thread(self._load_model)
                self.__class__._model_name = self.settings.funasr_model
                self.__class__._warmed_model_name = None
            if self.__class__._warmed_model_name != self.settings.funasr_model:
                await self.on_event({"type": "provider.warming", "provider": self.name})
                await asyncio.to_thread(self._warm_model)
                self.__class__._warmed_model_name = self.settings.funasr_model
        await self.on_event({"type": "provider.ready", "provider": self.name})

    def _load_model(self) -> Any:
        from funasr import AutoModel

        return AutoModel(
            model=self.settings.funasr_model,
            device=self.settings.funasr_device,
            disable_update=True,
        )

    def _warm_model(self) -> None:
        import numpy as np

        # Trigger CUDA kernels before live audio arrives. Keep this cache separate from the Session.
        self.__class__._model.generate(
            input=np.zeros(self.chunk_samples, dtype="float32"),
            cache={},
            is_final=True,
            chunk_size=[0, 10, 5],
            encoder_chunk_look_back=4,
            decoder_chunk_look_back=1,
            batch_size=1,
        )

    async def feed(self, pcm_s16le: bytes) -> None:
        self.buffer.extend(pcm_s16le)
        chunk_bytes = self.chunk_samples * 2
        async with self.process_lock:
            while len(self.buffer) >= chunk_bytes:
                chunk = bytes(self.buffer[:chunk_bytes])
                del self.buffer[:chunk_bytes]
                await self._recognize(chunk, is_final=False)

    async def _recognize(self, chunk: bytes, is_final: bool) -> None:
        import numpy as np

        samples = np.frombuffer(chunk, dtype="<i2").astype("float32") / 32768.0
        if not len(samples):
            return
        start_ms = int(self.processed_samples / 16)
        self.processed_samples += len(samples)
        end_ms = int(self.processed_samples / 16)

        def run() -> Any:
            return self.__class__._model.generate(
                input=samples,
                cache=self.cache,
                is_final=is_final,
                chunk_size=[0, 10, 5],
                encoder_chunk_look_back=4,
                decoder_chunk_look_back=1,
                batch_size=1,
            )

        async with self._inference_lock:
            result = await asyncio.to_thread(run)
        if isinstance(result, tuple):
            result = result[0]
        text = "".join((item.get("text") or "") for item in (result or [])).strip()
        if text:
            await self.on_event(
                {
                    "type": "transcript.final",
                    "text": text,
                    "start_ms": start_ms,
                    "end_ms": end_ms,
                }
            )

    async def finish(self) -> None:
        async with self.process_lock:
            if self.buffer:
                chunk = bytes(self.buffer)
                self.buffer.clear()
            else:
                # Flush Paraformer's look-ahead cache at an exact chunk boundary.
                chunk = bytes(960 * 2)
            await self._recognize(chunk, is_final=True)
