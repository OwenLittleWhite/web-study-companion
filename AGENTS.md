# Agent Guide

Read this file and `docs/ENVIRONMENT.md` before changing or running the project.

## Product boundary

- This is a generic browser learning companion, not a YouTube-specific extension.
- The extension captures only the active tab after an explicit user click.
- Raw audio is streamed for transcription and is not persisted by default.
- Keep the raw transcript append-only. Summaries or cleanup must never overwrite it.
- Keep the transcript display contract consistent across live events and restored Sessions: every
  segment returned to the UI must expose `text`, while preserving `raw_text` and `final_text`.
  Any transcript schema change requires a regression test for both live rendering and Session restore.
- When transcript content appears missing, inspect SQLite and the Session files before changing or
  deleting data; a blank UI must not be treated as data loss without storage evidence.
- API keys stay in the local `.env` or the mode-0600 `data/llm_config.json` / `data/asr_config.json`
  written by the localhost settings APIs; never place them in extension source, browser storage,
  Session data, exports, logs, fixtures, or prompts. Config read APIs must return only
  `has_api_key` and a fixed mask.
- A Qwen ASR Session snapshots its region, model, terms, and API key when capture starts. Saving ASR
  settings must not switch an active Session mid-stream. Only confirmed final segments are archived;
  partial hypotheses may replace earlier partial text in the UI but must not be persisted.
- Every chat request must carry an explicit per-message `include_transcript` boolean. Preserve the
  complete Session conversation locally. If the provider reports a context-length error, retry only
  once with the most recent half of the transcript and preserve the conversation history unchanged.
- A missing provider, key, model, or runtime is a configuration failure, not a successful transcription.

## Repository layout

- `extension/`: unpacked Chrome/Edge Manifest V3 extension.
- `server/`: localhost FastAPI companion service and ASR/LLM adapters.
- `scripts/`: reproducible bootstrap and launch commands.
- `docs/ENVIRONMENT.md`: actual workstation setup journal and verification status.
- `data/`: generated SQLite database and Session archives; ignored by Git.

## Required checks

After Python changes:

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m compileall -q server tests
```

After extension changes:

```bash
.venv/bin/python scripts/validate_extension.py
```

For a lightweight server smoke test, start it with `scripts/start-server.sh`, call `/health`, then stop it.
Use `scripts/start-server-local-asr.sh` only when the task explicitly needs local model preload and GPU
warm-up; the normal start script must remain safe from accidental model preload.
Do not claim local ASR is working until a real audio sample produces non-empty text.

## Environment changes

Whenever an Agent installs, upgrades, or removes a dependency, append the exact command,
resulting version, and verification result to `docs/ENVIRONMENT.md`. Separate completed steps
from optional or unverified steps. Never record secret values.
