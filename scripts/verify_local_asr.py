from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

import numpy as np
import soundfile as sf
import torch
from funasr import AutoModel

from app.config import settings


def main() -> None:
    print(f"torch={torch.__version__} cuda_build={torch.version.cuda}")
    print(f"cuda_available={torch.cuda.is_available()}")
    if not torch.cuda.is_available():
        raise SystemExit("CUDA is not available to PyTorch")
    print(f"gpu={torch.cuda.get_device_name(0)}")
    print(f"loading_model={settings.funasr_model} device={settings.funasr_device}")

    model = AutoModel(
        model=settings.funasr_model,
        device=settings.funasr_device,
        disable_update=True,
    )
    model_path = Path(model.model_path)
    candidates = sorted(model_path.rglob("*.wav"))
    if not candidates:
        raise SystemExit(f"Model loaded at {model_path}, but no bundled WAV sample was found")
    sample = candidates[0]
    speech, sample_rate = sf.read(sample, dtype="float32")
    if speech.ndim > 1:
        speech = np.mean(speech, axis=1)
    if sample_rate != 16000:
        raise SystemExit(f"Bundled sample rate is {sample_rate}, expected 16000")

    chunk_size = [0, 10, 5]
    chunk_stride = chunk_size[1] * 960
    cache: dict = {}
    transcript: list[str] = []
    total_chunks = (len(speech) + chunk_stride - 1) // chunk_stride
    for index in range(total_chunks):
        start = index * chunk_stride
        end = min(len(speech), (index + 1) * chunk_stride)
        result = model.generate(
            input=speech[start:end],
            cache=cache,
            is_final=end == len(speech),
            chunk_size=chunk_size,
            encoder_chunk_look_back=4,
            decoder_chunk_look_back=1,
            batch_size=1,
        )
        if isinstance(result, tuple):
            result = result[0]
        transcript.extend(item.get("text", "") for item in (result or []) if item.get("text"))

    text = "".join(transcript).strip()
    print(f"sample={sample}")
    print(f"transcript={text}")
    if not text:
        raise SystemExit("Local ASR returned an empty transcript")
    print("LOCAL_ASR_OK")


if __name__ == "__main__":
    main()
