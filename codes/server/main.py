from __future__ import annotations

import asyncio
import hmac
import json
import logging
from contextlib import asynccontextmanager
from typing import Any, Optional

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from asr.faster_whisper_adapter import FasterWhisperAdapter
from audio.source import PushAudioSource
from common.config import as_bool, get_config, pick, resolve_device, section
from common.hardware import HardwareProfile, detect_hardware_profile
from session.manager import SessionConfig, SessionManager
from translation.llm import LLMTranslator

CONFIG = get_config()

logging.basicConfig(
    level=str(section(CONFIG, "logging").get("level", "INFO")).upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("meetingAssist.server")

HARDWARE: HardwareProfile = detect_hardware_profile()
ASR: Optional[FasterWhisperAdapter] = None
TRANSLATOR: Optional[LLMTranslator] = None
MODEL_READY = False
MODEL_ERROR: Optional[str] = None
SESSION_LOCK = asyncio.Lock()

_SOURCES = ("microphone", "system")
_POLICY_VIOLATION = 1008


def _whisper_settings() -> dict[str, Any]:
    whisper = section(CONFIG, "whisper")
    device = resolve_device(CONFIG, whisper.get("device"), HARDWARE.whisper_device)
    compute_type = pick(whisper.get("compute_type"), HARDWARE.whisper_compute_type)
    if device == "cpu" and str(compute_type).lower() == "float16":
        compute_type = "int8"
    return {
        "model_size": str(pick(whisper.get("model_size"), HARDWARE.whisper_model_size)),
        "device": device,
        "compute_type": str(compute_type),
        "beam_size": int(whisper.get("beam_size", 1)),
        "cpu_threads": int(whisper.get("cpu_threads", 0)),
        "num_workers": int(whisper.get("num_workers", 1)),
        "download_root": str(section(CONFIG, "weights").get("whisper_dir") or "") or None,
        "vad_threshold": float(whisper.get("vad_threshold", 0.3)),
        "vad_min_speech_ms": int(whisper.get("vad_min_speech_ms", 100)),
        "vad_min_silence_ms": int(whisper.get("vad_min_silence_ms", 300)),
        "vad_speech_pad_ms": int(whisper.get("vad_speech_pad_ms", 400)),
        "languages": [str(code) for code in (whisper.get("languages") or ["zh", "en"])],
    }


def _token() -> str:
    return str(section(CONFIG, "server").get("token") or "")


def _token_ok(given: Any) -> bool:
    expected = _token()
    if not expected:
        return True
    return isinstance(given, str) and hmac.compare_digest(given.encode(), expected.encode())


async def _load_model() -> None:
    global MODEL_READY, MODEL_ERROR
    try:
        await asyncio.get_running_loop().run_in_executor(None, ASR.ensure_loaded)
        MODEL_READY = True
        logger.info("speech model ready")
    except Exception as exc:
        MODEL_ERROR = str(exc)
        logger.exception("speech model failed to load")


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001 - FastAPI signature
    global ASR, TRANSLATOR
    settings = _whisper_settings()
    ASR = FasterWhisperAdapter(**settings)
    translation = section(CONFIG, "translation")
    TRANSLATOR = LLMTranslator(
        llm_config=section(CONFIG, "llm"),
        max_tokens=int(translation.get("max_tokens", 512)),
    )
    server = section(CONFIG, "server")
    logger.info(
        "MeetingAssist server starting on %s:%s hardware=%s whisper=%s/%s/%s translation=%s auth=%s",
        server.get("host", "0.0.0.0"),
        server.get("port", 8765),
        HARDWARE.label,
        settings["model_size"],
        settings["device"],
        settings["compute_type"],
        "on" if TRANSLATOR.available else "off (no API key)",
        "token" if _token() else "none",
    )
    if not _token() and str(server.get("host", "")) not in ("127.0.0.1", "localhost", "::1"):
        logger.warning("server is reachable from the network without a token")
    loader = asyncio.create_task(_load_model())
    yield
    loader.cancel()
    logger.info("MeetingAssist server stopping")


app = FastAPI(title="MeetingAssist server", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, Any]:
    settings = _whisper_settings()
    return {
        "status": "error" if MODEL_ERROR else "ok",
        "ready": MODEL_READY,
        "error": MODEL_ERROR,
        "busy": SESSION_LOCK.locked(),
        "auth_required": bool(_token()),
        "whisper_size": settings["model_size"],
        "whisper_device": settings["device"],
        "whisper_compute_type": settings["compute_type"],
        "translation_enabled": bool(TRANSLATOR and TRANSLATOR.available),
    }


def _session_config(source_name: str) -> SessionConfig:
    audio = section(CONFIG, "audio")
    vad = section(CONFIG, "vad")
    whisper = section(CONFIG, "whisper")
    translation = section(CONFIG, "translation")
    pairs = {str(k): str(v) for k, v in (translation.get("pairs") or {}).items()}
    return SessionConfig(
        source_name=source_name,  # type: ignore[arg-type]
        sample_rate=int(audio.get("sample_rate", 16000)),
        vad_enabled=as_bool(vad.get("enabled"), True),
        vad_threshold=float(vad.get("threshold", 0.38)),
        vad_energy_rms_threshold=float(vad.get("energy_rms_threshold", 0.005)),
        vad_pre_speech_pad_ms=int(vad.get("pre_speech_pad_ms", 120)),
        vad_post_speech_pad_ms=int(vad.get("post_speech_pad_ms", 220)),
        vad_trailing_silence_seconds=float(vad.get("trailing_silence_seconds", 0.45)),
        vad_max_segment_seconds=float(vad.get("max_segment_seconds", 12.0)),
        min_confidence=float(whisper.get("min_confidence", 0.25)),
        asr_workers=int(whisper.get("workers", 1)),
        translation_enabled=as_bool(translation.get("enabled"), True) and bool(TRANSLATOR and TRANSLATOR.available),
        translation_pairs=pairs,
        translation_workers=int(translation.get("workers", 2)),
        stop_drain_seconds=float(section(CONFIG, "server").get("stop_drain_seconds", 60.0)),
    )


async def _send(ws: WebSocket, event_type: str, payload: dict[str, Any]) -> bool:
    try:
        await ws.send_text(json.dumps({"type": event_type, "payload": payload}))
        return True
    except Exception:
        return False


async def _reject(ws: WebSocket, code: str, message: str) -> None:
    logger.info("rejected connection code=%s", code)
    await _send(ws, "error", {"code": code, "message": message})
    try:
        await ws.close(code=_POLICY_VIOLATION)
    except RuntimeError:
        pass


@app.websocket("/ws/stream")
async def stream_socket(ws: WebSocket) -> None:
    await ws.accept()
    server = section(CONFIG, "server")
    audio = section(CONFIG, "audio")
    sample_rate = int(audio.get("sample_rate", 16000))

    # First message must be a JSON start with the token; audio before it is refused.
    try:
        raw = await asyncio.wait_for(ws.receive_text(), timeout=float(server.get("auth_timeout_seconds", 10)))
        hello = json.loads(raw)
    except (asyncio.TimeoutError, json.JSONDecodeError, KeyError, WebSocketDisconnect):
        await _reject(ws, "bad_handshake", "Expected a start message.")
        return
    if not isinstance(hello, dict) or hello.get("type") != "start":
        await _reject(ws, "bad_handshake", "Expected a start message.")
        return
    if not _token_ok(hello.get("token")):
        await _reject(ws, "unauthorized", "Invalid server token.")
        return
    if int(hello.get("sample_rate") or 0) != sample_rate:
        await _reject(ws, "sample_rate_mismatch", f"Server expects {sample_rate} Hz audio.")
        return
    if MODEL_ERROR:
        await _reject(ws, "model_failed", f"Speech model failed to load: {MODEL_ERROR}")
        return
    if not MODEL_READY or ASR is None or TRANSLATOR is None:
        await _reject(ws, "not_ready", "Server is still loading the speech model.")
        return
    if SESSION_LOCK.locked():
        await _reject(ws, "session_busy", "Another client is already using this server.")
        return

    source_name = hello.get("source") if hello.get("source") in _SOURCES else "microphone"
    peer = f"{ws.client.host}:{ws.client.port}" if ws.client else "unknown"

    async with SESSION_LOCK:
        pcm = PushAudioSource(
            sample_rate=sample_rate,
            chunk_seconds=float(audio.get("chunk_seconds", 0.75)),
            max_queued_seconds=float(server.get("max_queued_seconds", 30.0)),
        )
        manager = SessionManager(
            audio_source=pcm,
            asr=ASR,
            translator=TRANSLATOR,
            config=_session_config(source_name),
        )
        await manager.start()
        logger.info("session started peer=%s source=%s", peer, source_name)

        async def pump_events() -> None:
            connected = True
            async for event in manager.events():
                if connected:
                    connected = await _send(ws, event.type, event.payload)

        pump = asyncio.create_task(pump_events())
        warned_drop = False
        try:
            while True:
                message = await ws.receive()
                if message["type"] == "websocket.disconnect":
                    break
                data = message.get("bytes")
                if data is not None:
                    if not pcm.push_pcm16(data) and not warned_drop:
                        warned_drop = True
                        logger.warning("audio backlog full, dropping frames peer=%s", peer)
                    continue
                text = message.get("text")
                if text:
                    try:
                        if json.loads(text).get("type") == "stop":
                            break
                    except (json.JSONDecodeError, AttributeError):
                        continue
        except WebSocketDisconnect:
            pass
        finally:
            await manager.stop()
            try:
                await asyncio.wait_for(pump, timeout=5)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pump.cancel()
            try:
                await ws.close()
            except RuntimeError:
                pass
            logger.info(
                "session ended peer=%s utterances=%d dropped_frames=%d",
                peer,
                len(manager.utterances),
                pcm.dropped_frames,
            )


def run() -> None:
    """Serve on the configured host and port."""
    server = section(CONFIG, "server")
    uvicorn.run(
        app,
        host=str(server.get("host", "0.0.0.0")),
        port=int(server.get("port", 8765)),
        log_level=str(section(CONFIG, "logging").get("level", "info")).lower(),
    )


if __name__ == "__main__":
    run()
