from __future__ import annotations

import json
import re
import shutil
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_name(value: str, fallback: str = "study-session") -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", "_", value).strip(" ._")
    return (cleaned[:80] or fallback).strip()


TIMELINE_RESET_THRESHOLD_MS = 5_000


class SessionStore:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.sessions_dir = self.data_dir / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "companion.sqlite3"
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(self.db_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._initialize()

    def _initialize(self) -> None:
        with self._lock, self._connection:
            self._connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA foreign_keys=ON;
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    language TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    ended_at TEXT,
                    summary TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS transcript_segments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    start_ms INTEGER NOT NULL,
                    end_ms INTEGER NOT NULL,
                    raw_text TEXT NOT NULL,
                    final_text TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    language TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS transcript_session_time
                    ON transcript_segments(session_id, start_ms);
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    include_transcript INTEGER NOT NULL DEFAULT 0,
                    transcript_scope TEXT NOT NULL DEFAULT 'none',
                    created_at TEXT NOT NULL
                );
                """
            )
            message_columns = {
                row["name"] for row in self._connection.execute("PRAGMA table_info(messages)").fetchall()
            }
            if "include_transcript" not in message_columns:
                self._connection.execute(
                    "ALTER TABLE messages ADD COLUMN include_transcript INTEGER NOT NULL DEFAULT 0"
                )
            if "transcript_scope" not in message_columns:
                self._connection.execute(
                    "ALTER TABLE messages ADD COLUMN transcript_scope TEXT NOT NULL DEFAULT 'legacy'"
                )

    def create_session(self, title: str, url: str, provider: str, language: str) -> dict[str, Any]:
        session_id = uuid.uuid4().hex
        now = utc_now()
        with self._lock, self._connection:
            self._connection.execute(
                """INSERT INTO sessions
                (id, title, url, provider, language, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (session_id, title, url, provider, language, now, now),
            )
        folder = self.session_folder(session_id, title)
        folder.mkdir(parents=True, exist_ok=True)
        self._write_session_metadata(session_id)
        return self.get_session(session_id)

    def get_session(self, session_id: str, include_content: bool = False) -> dict[str, Any]:
        with self._lock:
            row = self._connection.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if row is None:
                raise KeyError(session_id)
            result = dict(row)
            if include_content:
                result["segments"] = self.get_segments(session_id)
                result["messages"] = self.get_messages(session_id)
            return result

    def begin_capture(self, session_id: str) -> dict[str, Any]:
        """Mark an existing Session active again without replacing any archived content."""
        self.get_session(session_id)
        now = utc_now()
        with self._lock, self._connection:
            self._connection.execute(
                "UPDATE sessions SET ended_at = NULL, updated_at = ? WHERE id = ?",
                (now, session_id),
            )
        self._write_session_metadata(session_id)
        return self.get_session(session_id)

    def capture_offset_ms(self, session_id: str) -> int:
        """Return the end of the archived timeline so a resumed capture can append after it."""
        segments = self.get_segments(session_id)
        return max((int(segment["end_ms"]) for segment in segments), default=0)

    def list_sessions(self, limit: int = 50) -> list[dict[str, Any]]:
        bounded_limit = max(1, min(limit, 200))
        with self._lock:
            rows = self._connection.execute(
                """SELECT id, title, url, provider, language, created_at, updated_at, ended_at,
                          (SELECT COUNT(*) FROM transcript_segments t WHERE t.session_id = sessions.id)
                              AS segment_count,
                          (SELECT COUNT(*) FROM messages m WHERE m.session_id = sessions.id)
                              AS message_count
                   FROM sessions ORDER BY created_at DESC LIMIT ?""",
                (bounded_limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def session_folder(self, session_id: str, title: str | None = None) -> Path:
        existing = sorted(self.sessions_dir.glob(f"*_{session_id[:8]}"))
        if existing:
            return existing[0]
        if title is None:
            title = self.get_session(session_id)["title"]
        return self.sessions_dir / f"{safe_name(title)}_{session_id[:8]}"

    def rename_session(self, session_id: str, title: str) -> dict[str, Any]:
        title = title.strip()
        if not title:
            raise ValueError("Session 名称不能为空。")
        if len(title) > 500:
            raise ValueError("Session 名称不能超过 500 个字符。")
        self.get_session(session_id)
        now = utc_now()
        with self._lock, self._connection:
            self._connection.execute(
                "UPDATE sessions SET title = ?, updated_at = ? WHERE id = ?",
                (title, now, session_id),
            )
        self._write_session_metadata(session_id)
        return self.get_session(session_id, include_content=True)

    def delete_session(self, session_id: str) -> None:
        self.get_session(session_id)
        folder = self.session_folder(session_id)
        trash_root = self.data_dir / ".trash"
        moved_to: Path | None = None
        if folder.exists():
            resolved_folder = folder.resolve()
            if resolved_folder.parent != self.sessions_dir.resolve():
                raise RuntimeError("拒绝删除 Session 数据目录之外的路径。")
            trash_root.mkdir(parents=True, exist_ok=True)
            moved_to = trash_root / f"{folder.name}_{uuid.uuid4().hex[:8]}"
            folder.rename(moved_to)
        try:
            with self._lock, self._connection:
                cursor = self._connection.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
                if cursor.rowcount != 1:
                    raise KeyError(session_id)
        except Exception:
            if moved_to and moved_to.exists():
                moved_to.rename(folder)
            raise
        if moved_to and moved_to.exists():
            shutil.rmtree(moved_to)

    def add_segment(
        self,
        session_id: str,
        start_ms: int,
        end_ms: int,
        text: str,
        provider: str,
        language: str,
    ) -> dict[str, Any]:
        text = text.strip()
        if not text:
            raise ValueError("Transcript segment cannot be empty")
        now = utc_now()
        with self._lock, self._connection:
            cursor = self._connection.execute(
                """INSERT INTO transcript_segments
                (session_id, start_ms, end_ms, raw_text, final_text, provider, language, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (session_id, start_ms, max(start_ms, end_ms), text, text, provider, language, now),
            )
            self._connection.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?", (now, session_id)
            )
            segment_id = cursor.lastrowid
        segment = {
            "id": segment_id,
            "start_ms": start_ms,
            "end_ms": max(start_ms, end_ms),
            "text": text,
            "raw_text": text,
            "provider": provider,
            "language": language,
            "is_final": True,
        }
        folder = self.session_folder(session_id)
        with (folder / "transcript.raw.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(segment, ensure_ascii=False) + "\n")
        return segment

    def get_segments(self, session_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                """SELECT id, start_ms, end_ms, raw_text, final_text, provider, language, created_at
                FROM transcript_segments WHERE session_id = ? ORDER BY id""",
                (session_id,),
            ).fetchall()
        # Keep one display-field contract for both live WebSocket events and restored Sessions.
        # Live events already expose `text`; persisted rows use `final_text` internally.
        # Older builds restarted provider timestamps from zero on every resumed capture. Preserve
        # those raw values for auditability, but repair obvious backwards jumps in the public
        # display/export timeline. New absolute timestamps naturally rejoin without another offset.
        segments: list[dict[str, Any]] = []
        timeline_offset = 0
        previous_start = 0
        previous_end = 0
        for index, row in enumerate(rows):
            stored_start = int(row["start_ms"])
            stored_end = int(row["end_ms"])
            if index:
                if timeline_offset and stored_start + TIMELINE_RESET_THRESHOLD_MS >= previous_start:
                    timeline_offset = 0
                candidate_start = stored_start + timeline_offset
                if candidate_start + TIMELINE_RESET_THRESHOLD_MS < previous_start:
                    timeline_offset = previous_end
            start_ms = stored_start + timeline_offset
            end_ms = max(start_ms, stored_end + timeline_offset)
            segment = {
                **dict(row),
                "text": row["final_text"],
                "start_ms": start_ms,
                "end_ms": end_ms,
            }
            if timeline_offset:
                segment.update(
                    {
                        "stored_start_ms": stored_start,
                        "stored_end_ms": stored_end,
                        "timeline_repaired": True,
                    }
                )
            segments.append(segment)
            previous_start = start_ms
            previous_end = max(previous_end, end_ms)
        return segments

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        *,
        include_transcript: bool = False,
        transcript_scope: str = "none",
    ) -> dict[str, Any]:
        created_at = utc_now()
        with self._lock, self._connection:
            cursor = self._connection.execute(
                """INSERT INTO messages
                (session_id, role, content, include_transcript, transcript_scope, created_at)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    session_id,
                    role,
                    content,
                    int(include_transcript),
                    transcript_scope,
                    created_at,
                ),
            )
            self._connection.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?", (created_at, session_id)
            )
        return {
            "id": cursor.lastrowid,
            "role": role,
            "content": content,
            "include_transcript": include_transcript,
            "transcript_scope": transcript_scope,
            "created_at": created_at,
        }

    def get_messages(self, session_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                """SELECT id, role, content, include_transcript, transcript_scope, created_at
                FROM messages WHERE session_id = ? ORDER BY id""",
                (session_id,),
            ).fetchall()
        return [
            {**dict(row), "include_transcript": bool(row["include_transcript"])} for row in rows
        ]

    def set_summary(self, session_id: str, summary: str) -> None:
        now = utc_now()
        with self._lock, self._connection:
            self._connection.execute(
                "UPDATE sessions SET summary = ?, updated_at = ? WHERE id = ?",
                (summary, now, session_id),
            )
        (self.session_folder(session_id) / "summary.md").write_text(summary, encoding="utf-8")

    def end_session(self, session_id: str) -> None:
        now = utc_now()
        with self._lock, self._connection:
            self._connection.execute(
                "UPDATE sessions SET ended_at = COALESCE(ended_at, ?), updated_at = ? WHERE id = ?",
                (now, now, session_id),
            )
        self.write_materialized_files(session_id)

    def _write_session_metadata(self, session_id: str) -> None:
        session = self.get_session(session_id)
        folder = self.session_folder(session_id, session["title"])
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "session.json").write_text(
            json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def write_materialized_files(self, session_id: str) -> None:
        self._write_session_metadata(session_id)
        folder = self.session_folder(session_id)
        (folder / "transcript.final.md").write_text(self.export(session_id, "md")[0], encoding="utf-8")
        messages = self.get_messages(session_id)
        (folder / "conversation.json").write_text(
            json.dumps(messages, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def export(self, session_id: str, output_format: str) -> tuple[str, str, str]:
        session = self.get_session(session_id)
        segments = self.get_segments(session_id)
        messages = self.get_messages(session_id)
        base = safe_name(session["title"])

        if output_format == "json":
            exported_session = {key: value for key, value in session.items() if key != "summary"}
            content = json.dumps(
                {**exported_session, "segments": segments, "messages": messages},
                ensure_ascii=False,
                indent=2,
            )
            return content, f"{base}.json", "application/json; charset=utf-8"
        if output_format == "txt":
            content = "\n".join(f"[{format_clock(s['start_ms'])}] {s['final_text']}" for s in segments)
            return content, f"{base}.txt", "text/plain; charset=utf-8"
        if output_format == "srt":
            blocks = [
                f"{index}\n{format_srt(s['start_ms'])} --> {format_srt(s['end_ms'])}\n{s['final_text']}"
                for index, s in enumerate(segments, 1)
            ]
            return "\n\n".join(blocks), f"{base}.srt", "application/x-subrip; charset=utf-8"
        if output_format == "vtt":
            blocks = [
                f"{format_vtt(s['start_ms'])} --> {format_vtt(s['end_ms'])}\n{s['final_text']}"
                for s in segments
            ]
            return "WEBVTT\n\n" + "\n\n".join(blocks), f"{base}.vtt", "text/vtt; charset=utf-8"
        if output_format != "md":
            raise ValueError(f"Unsupported export format: {output_format}")

        lines = [
            f"# {session['title']}",
            "",
            f"- 来源：{session['url']}",
            f"- 开始时间：{session['created_at']}",
            f"- 转写引擎：{session['provider']}",
            "",
            "## 逐字稿",
            "",
        ]
        lines.extend(f"**[{format_clock(s['start_ms'])}]** {s['final_text']}" for s in segments)
        if messages:
            lines.extend(["", "## 学习问答", ""])
            for message in messages:
                label = "我" if message["role"] == "user" else "学习助手"
                lines.extend([f"### {label}", "", message["content"], ""])
        return "\n".join(lines), f"{base}.md", "text/markdown; charset=utf-8"


def format_clock(milliseconds: int) -> str:
    total_seconds = max(0, milliseconds // 1000)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"


def format_srt(milliseconds: int) -> str:
    hours, remainder = divmod(max(0, milliseconds), 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def format_vtt(milliseconds: int) -> str:
    return format_srt(milliseconds).replace(",", ".")
