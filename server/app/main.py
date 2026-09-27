from __future__ import annotations

import json
import time
from contextlib import asynccontextmanager
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from .asr_config import ASRConfigStore, QwenASRConfig, qwen_context_text
from .config import settings
from .llm import ChatLLM
from .llm_config import LLMConfigStore
from .models import ASRConfigUpdate, ChatRequest, LLMConfigUpdate, SessionCreate, SessionRename
from .providers import provider_status, streaming_provider
from .providers.local_funasr import LocalFunASRProvider
from .providers.qwen import QwenStreamingProvider
from .store import SessionStore


store = SessionStore(settings.data_dir)
llm_config = LLMConfigStore(settings)
llm = ChatLLM(llm_config)
asr_config = ASRConfigStore(settings)
active_session_ids: set[str] = set()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    if settings.funasr_preload and LocalFunASRProvider.available():
        async def discard_event(_event: dict) -> None:
            return None

        print("Preloading local FunASR model and warming GPU before accepting requests...", flush=True)
        provider = LocalFunASRProvider(settings, "auto", discard_event)
        await provider.start()
        print("Local FunASR preload complete.", flush=True)
    yield


app = FastAPI(title="Study Companion", version="0.3.10", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[],
    allow_origin_regex=r"^(chrome-extension://.*|http://localhost(:\d+)?|http://127\.0\.0\.1(:\d+)?)$",
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)


@app.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "version": app.version,
        "providers": provider_status(settings, asr_config.get()),
    }


@app.post("/api/sessions")
def create_session(payload: SessionCreate) -> dict:
    availability = provider_status(settings, asr_config.get()).get(payload.provider)
    if not availability or not availability["ready"]:
        reason = availability["reason"] if availability else "未知的转写方式。"
        raise HTTPException(status_code=400, detail=reason)
    return store.create_session(
        title=payload.title,
        url=payload.url,
        provider=payload.provider,
        language=payload.language,
    )


@app.get("/api/sessions")
def list_sessions(limit: int = 50) -> dict:
    return {"sessions": store.list_sessions(limit)}


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str) -> dict:
    try:
        return store.get_session(session_id, include_content=True)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Session 不存在。") from error


@app.patch("/api/sessions/{session_id}")
async def rename_session(session_id: str, payload: SessionRename) -> dict:
    if session_id in active_session_ids:
        raise HTTPException(status_code=409, detail="正在采集的 Session 不能重命名，请先结束采集。")
    try:
        return store.rename_session(session_id, payload.title)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Session 不存在。") from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str) -> dict:
    if session_id in active_session_ids:
        raise HTTPException(status_code=409, detail="正在采集的 Session 不能删除，请先结束采集。")
    try:
        store.delete_session(session_id)
        return {"ok": True}
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Session 不存在。") from error


@app.post("/api/sessions/{session_id}/chat")
async def chat(session_id: str, payload: ChatRequest) -> dict:
    try:
        store.get_session(session_id)
        result = await llm.answer(
            store,
            session_id,
            payload.question,
            include_transcript=payload.include_transcript,
        )
        scope = result["transcript_scope"]
        user_message = store.add_message(
            session_id,
            "user",
            payload.question,
            include_transcript=payload.include_transcript,
            transcript_scope=scope,
        )
        assistant_message = store.add_message(session_id, "assistant", result["answer"])
        return {
            "answer": result["answer"],
            "transcript_scope": scope,
            "user_message": user_message,
            "assistant_message": assistant_message,
        }
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Session 不存在。") from error
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.get("/api/llm/config")
def get_llm_config() -> dict:
    try:
        return llm_config.public()
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


def llm_candidate(payload: LLMConfigUpdate):
    try:
        return llm_config.candidate(
            provider=payload.provider,
            base_url=payload.base_url,
            model=payload.model,
            api_key=payload.api_key,
        )
    except (RuntimeError, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/llm/config/test")
async def test_llm_config(payload: LLMConfigUpdate) -> dict:
    candidate = llm_candidate(payload)
    try:
        await llm.test_config(candidate)
        return {"ok": True}
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.put("/api/llm/config")
async def save_llm_config(payload: LLMConfigUpdate) -> dict:
    candidate = llm_candidate(payload)
    try:
        await llm.test_config(candidate)
        return llm_config.save(candidate)
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.get("/api/asr/config")
def get_asr_config() -> dict:
    try:
        return asr_config.public()
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


def asr_candidate(payload: ASRConfigUpdate) -> QwenASRConfig:
    try:
        return asr_config.candidate(
            region=payload.region,
            model=payload.model,
            api_key=payload.api_key,
            terms=payload.terms,
            use_page_context=payload.use_page_context,
        )
    except (RuntimeError, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


async def verify_asr_config(config: QwenASRConfig) -> None:
    async def discard_event(_event: dict) -> None:
        return None

    provider = QwenStreamingProvider(config, "auto", discard_event)
    try:
        await provider.start()
    finally:
        await provider.finish()


@app.post("/api/asr/config/test")
async def test_asr_config(payload: ASRConfigUpdate) -> dict:
    candidate = asr_candidate(payload)
    try:
        await verify_asr_config(candidate)
        return {"ok": True}
    except Exception as error:
        raise HTTPException(status_code=503, detail=f"阿里云实时转写连接失败：{error}") from error


@app.put("/api/asr/config")
async def save_asr_config(payload: ASRConfigUpdate) -> dict:
    candidate = asr_candidate(payload)
    try:
        await verify_asr_config(candidate)
        return asr_config.save(candidate)
    except Exception as error:
        raise HTTPException(status_code=503, detail=f"验证失败，原配置未改变：{error}") from error


@app.get("/api/sessions/{session_id}/export")
def export_session(session_id: str, format: str = "md") -> Response:
    try:
        content, filename, media_type = store.export(session_id, format.lower())
        ascii_filename = f"study-session.{format.lower()}"
        return Response(
            content=content.encode("utf-8"),
            media_type=media_type,
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{ascii_filename}"; filename*=UTF-8\'\'{quote(filename)}'
                )
            },
        )
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Session 不存在。") from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.websocket("/ws/transcribe")
async def transcribe(websocket: WebSocket) -> None:
    await websocket.accept()
    provider = None
    session_id = None
    provider_name = ""
    language = "auto"
    page_title = ""
    current_qwen_config: QwenASRConfig | None = None
    confirmed_context: list[str] = []
    started_monotonic = time.monotonic()
    capture_offset_ms = 0

    async def on_provider_event(event: dict) -> None:
        nonlocal session_id
        if event.get("type") == "transcript.final" and session_id:
            start_ms = event.get("start_ms")
            end_ms = event.get("end_ms")
            elapsed_ms = int((time.monotonic() - started_monotonic) * 1000)
            if start_ms is None:
                start_ms = max(0, elapsed_ms - 1000)
            if end_ms is None:
                end_ms = elapsed_ms
            segment = store.add_segment(
                session_id=session_id,
                start_ms=capture_offset_ms + int(start_ms),
                end_ms=capture_offset_ms + int(end_ms),
                text=event["text"],
                provider=provider_name,
                language=language,
            )
            await websocket.send_json({"type": "transcript.final", "segment": segment})
            confirmed_context.append(event["text"])
            if len(confirmed_context) > 8:
                del confirmed_context[:-8]
            if provider is not None and current_qwen_config is not None:
                try:
                    await provider.update_context(
                        qwen_context_text(
                            current_qwen_config,
                            page_title=page_title,
                            recent_transcript=" ".join(confirmed_context),
                        )
                    )
                except Exception:
                    # Context refresh improves later recognition but must never discard a
                    # final segment or terminate an otherwise healthy audio stream.
                    pass
            return
        await websocket.send_json(event)

    try:
        first = await websocket.receive_text()
        start = json.loads(first)
        if start.get("type") != "start":
            raise ValueError("First WebSocket message must be a start message")
        session_id = start["session_id"]
        session = store.get_session(session_id)
        capture_offset_ms = store.capture_offset_ms(session_id)
        existing_segments = store.get_segments(session_id)
        confirmed_context.extend(segment["final_text"] for segment in existing_segments[-8:])
        store.begin_capture(session_id)
        active_session_ids.add(session_id)
        provider_name = start.get("provider") or session["provider"]
        language = start.get("language") or session["language"]
        page_title = str(start.get("page", {}).get("title") or session["title"])
        context_text = ""
        if provider_name == "qwen-cloud":
            current_qwen_config = asr_config.get()
            context_text = qwen_context_text(
                current_qwen_config,
                page_title=page_title,
                recent_transcript=" ".join(confirmed_context),
            )
        provider = streaming_provider(
            provider_name,
            settings,
            language,
            on_provider_event,
            qwen_config=current_qwen_config,
            context_text=context_text,
        )
        await provider.start()

        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break
            if message.get("bytes") is not None:
                await provider.feed(message["bytes"])
                continue
            if message.get("text"):
                control = json.loads(message["text"])
                if control.get("type") == "stop":
                    break
    except WebSocketDisconnect:
        pass
    except KeyError:
        await websocket.send_json({"type": "capture.error", "error": "Session 不存在或启动参数不完整。"})
    except Exception as error:
        try:
            await websocket.send_json({"type": "capture.error", "error": str(error)})
        except Exception:
            pass
    finally:
        if provider is not None:
            try:
                await provider.finish()
            except Exception:
                pass
        if session_id:
            active_session_ids.discard(session_id)
            try:
                store.end_session(session_id)
            except Exception:
                pass
        try:
            await websocket.close()
        except Exception:
            pass
