from __future__ import annotations

import re
from typing import Any

from .store import format_clock


def terms(text: str) -> set[str]:
    lowered = text.lower()
    latin = set(re.findall(r"[a-z0-9_+-]{2,}", lowered))
    chinese_runs = re.findall(r"[\u4e00-\u9fff]+", lowered)
    chinese = {
        run[index : index + 2]
        for run in chinese_runs
        for index in range(max(1, len(run) - 1))
        if run[index : index + 2]
    }
    return latin | chinese


def retrieve_segments(
    segments: list[dict[str, Any]], question: str, max_segments: int = 32
) -> list[dict[str, Any]]:
    if len(segments) <= max_segments:
        return segments
    query_terms = terms(question)
    scored: list[tuple[int, int]] = []
    for index, segment in enumerate(segments):
        segment_terms = terms(segment.get("final_text", ""))
        score = len(query_terms & segment_terms)
        if score:
            scored.append((score, index))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)

    selected = set(range(max(0, len(segments) - 8), len(segments)))
    for _score, index in scored[:12]:
        selected.update(range(max(0, index - 1), min(len(segments), index + 2)))
        if len(selected) >= max_segments:
            break
    return [segments[index] for index in sorted(selected)[:max_segments]]


def transcript_context(segments: list[dict[str, Any]]) -> str:
    return "\n".join(
        f"[{format_clock(segment['start_ms'])}-{format_clock(segment['end_ms'])}] "
        f"{segment.get('final_text') or segment.get('text', '')}"
        for segment in segments
    )
