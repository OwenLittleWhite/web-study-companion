from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx
import numpy as np
import soundfile as sf
import websockets


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

from app.config import settings


def pcm16(sample: Path) -> bytes:
    speech, sample_rate = sf.read(sample, dtype="float32")
    if speech.ndim > 1:
        speech = np.mean(speech, axis=1)
    if sample_rate != 16000:
        raise RuntimeError(f"Expected a 16 kHz sample, got {sample_rate} Hz")
    return (np.clip(speech, -1, 1) * 32767).astype("<i2").tobytes()


def find_sample() -> Path:
    cache_root = Path.home() / ".cache" / "modelscope"
    candidates = sorted(cache_root.rglob("*.wav"))
    if not candidates:
        raise RuntimeError("No bundled ModelScope WAV sample found; run verify_local_asr.py first")
    return candidates[0]


async def main() -> None:
    base_url = f"http://{settings.host}:{settings.port}"
    async with httpx.AsyncClient(timeout=10) as client:
        health = (await client.get(f"{base_url}/health")).json()
        if not health.get("ok"):
            raise RuntimeError(f"Server health check failed: {health}")
        session = (
            await client.post(
                f"{base_url}/api/sessions",
                json={
                    "title": "Local ASR WebSocket smoke test",
                    "url": "local://bundled-sample",
                    "provider": "local-funasr",
                    "language": "zh",
                },
            )
        ).json()

    sample = find_sample()
    audio = pcm16(sample)
    events: list[dict] = []
    ws_url = f"ws://{settings.host}:{settings.port}/ws/transcribe"
    async with websockets.connect(ws_url, max_size=4 * 1024 * 1024) as socket:
        await socket.send(
            json.dumps(
                {
                    "type": "start",
                    "session_id": session["id"],
                    "provider": "local-funasr",
                    "language": "zh",
                    "sample_rate": 16000,
                    "format": "pcm_s16le",
                }
            )
        )
        while True:
            event = json.loads(await asyncio.wait_for(socket.recv(), timeout=600))
            events.append(event)
            if event.get("type") in {"provider.ready", "capture.error"}:
                break
        if events[-1].get("type") == "capture.error":
            raise RuntimeError(events[-1]["error"])
        for offset in range(0, len(audio), 3200):
            await socket.send(audio[offset : offset + 3200])
        await socket.send(json.dumps({"type": "stop"}))
        try:
            while True:
                events.append(json.loads(await asyncio.wait_for(socket.recv(), timeout=600)))
        except websockets.ConnectionClosed:
            pass

    finals = [event["segment"]["text"] for event in events if event.get("type") == "transcript.final"]
    if not finals:
        raise RuntimeError(f"Pipeline returned no final transcript: {events}")
    print(f"sample={sample}")
    print(f"session_id={session['id']}")
    print(f"transcript={''.join(finals)}")
    print("WS_PIPELINE_OK")


if __name__ == "__main__":
    asyncio.run(main())
