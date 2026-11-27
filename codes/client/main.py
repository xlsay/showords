from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from audio.capture import AudioSource, MicrophoneSource
from audio.devices import enumerate_audio_devices
from audio.loopback import SystemAudioLoopbackSource
from common.config import get_config, section
from link.server_link import ServerLink, ServerRejected, fetch_server_health

CONFIG = get_config()

logging.basicConfig(
    level=str(section(CONFIG, "logging").get("level", "INFO")).upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("meetingAssist.client")

SESSION_LOCK = asyncio.Lock()
_SOURCES = ("microphone", "system")


def _server_settings() -> tuple[str, int, str, float, float]:
    server = section(CONFIG, "server")
    return (
        str(server.get("host") or "127.0.0.1"),
        int(server.get("port", 8765)),
        str(server.get("token") or ""),
        float(server.get("connect_timeout_seconds", 5.0)),
        float(server.get("stop_timeout_seconds", 70.0)),
    )


app = FastAPI(title="MeetingAssist client")


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "ready": True}


@app.get("/audio/devices")
async def audio_devices() -> dict[str, Any]:
    return await asyncio.get_running_loop().run_in_executor(None, enumerate_audio_devices)


@app.get("/config")
async def read_config() -> dict[str, Any]:
    host, port, token, timeout, _ = _server_settings()
    info: dict[str, Any] = {
        "server_host": host,
        "server_port": port,
        "token_set": bool(token),
        "default_source": str(section(CONFIG, "audio").get("source") or "microphone"),
    }
    try:
        health_body = await asyncio.get_running_loop().run_in_executor(
            None, fetch_server_health, host, port, timeout
        )
        info["server"] = {"reachable": True, **health_body}
    except Exception as exc:
        info["server"] = {"reachable": False, "error": str(exc)}
    return info


def _build_audio_source(source_name: str, mic_device: Optional[str], loopback_device: Optional[str]) -> AudioSource:
    audio = section(CONFIG, "audio")
    sample_rate = int(audio.get("sample_rate", 16000))
    chunk_seconds = float(audio.get("chunk_seconds", 0.25))
    if source_name == "system":
        speaker = loopback_device or str(audio.get("loopback_device") or "") or None
        return SystemAudioLoopbackSource(sample_rate=sample_rate, chunk_seconds=chunk_seconds, speaker_name=speaker)
    device: Optional[int | str] = mic_device or str(audio.get("microphone_device") or "") or None
    if isinstance(device, str) and device.isdigit():
        device = int(device)
    return MicrophoneSource(sample_rate=sample_rate, chunk_seconds=chunk_seconds, device=device)


async def _send_ui(ws: WebSocket, event_type: str, payload: dict[str, Any]) -> bool:
    try:
        await ws.send_text(json.dumps({"type": event_type, "payload": payload}))
        return True
    except Exception:
        return False


async def _close_ui(ws: WebSocket) -> None:
    try:
        await ws.close()
    except RuntimeError:
        pass


@app.websocket("/ws/session")
async def session_socket(ws: WebSocket) -> None:
    await ws.accept()
    if SESSION_LOCK.locked():
        await _send_ui(ws, "error", {"code": "session_busy", "message": "A session is already running."})
        await _close_ui(ws)
        return

    source_name = ws.query_params.get("source") or str(section(CONFIG, "audio").get("source") or "microphone")
    if source_name not in _SOURCES:
        source_name = "microphone"
    host, port, token, connect_timeout, stop_timeout = _server_settings()
    sample_rate = int(section(CONFIG, "audio").get("sample_rate", 16000))

    async with SESSION_LOCK:
        link = ServerLink(host=host, port=port, token=token, connect_timeout=connect_timeout)
        try:
            await link.connect(sample_rate=sample_rate, source=source_name)
        except ServerRejected as exc:
            await _send_ui(ws, "error", {"code": exc.code, "message": str(exc)})
            await _close_ui(ws)
            return
        except Exception as exc:
            logger.warning("cannot reach server %s: %s", link.address, exc)
            await _send_ui(
                ws, "error", {"code": "server_unreachable", "message": f"Cannot reach server at {link.address}: {exc}"}
            )
            await _close_ui(ws)
            return

        try:
            capture = _build_audio_source(
                source_name, ws.query_params.get("mic_device"), ws.query_params.get("loopback_device")
            )
        except Exception as exc:
            await _send_ui(ws, "error", {"code": "audio_unavailable", "message": str(exc)})
            await link.stop()
            await link.close()
            await _close_ui(ws)
            return

        logger.info("session started server=%s source=%s", link.address, source_name)
        stop_requested = asyncio.Event()

        async def relay_server_events() -> None:
            async for event in link.events():
                await _send_ui(ws, str(event.get("type")), event.get("payload") or {})

        async def pump_audio() -> None:
            try:
                async for chunk in capture.stream():
                    await link.send_audio(chunk.samples)
            except Exception as exc:
                logger.warning("capture failed: %s", exc)
                await _send_ui(ws, "error", {"code": "capture_failed", "message": str(exc)})
            finally:
                stop_requested.set()
                await link.stop()

        async def watch_ui() -> None:
            try:
                while True:
                    message = json.loads(await ws.receive_text())
                    if isinstance(message, dict) and message.get("type") == "stop":
                        break
            except (WebSocketDisconnect, json.JSONDecodeError, RuntimeError):
                pass
            stop_requested.set()

        relay = asyncio.create_task(relay_server_events())
        audio_task = asyncio.create_task(pump_audio())
        ui_task = asyncio.create_task(watch_ui())
        stop_wait = asyncio.create_task(stop_requested.wait())

        try:
            # Run until the user stops, capture ends, or the server drops the link.
            await asyncio.wait({stop_wait, relay}, return_when=asyncio.FIRST_COMPLETED)
            await capture.aclose()
            try:
                await asyncio.wait_for(audio_task, timeout=5)
            except asyncio.TimeoutError:
                audio_task.cancel()
                await link.stop()
            # The server sends final results, then closes; relay ends with it.
            try:
                await asyncio.wait_for(relay, timeout=stop_timeout)
            except asyncio.TimeoutError:
                logger.warning("server did not finish within %.0fs", stop_timeout)
                relay.cancel()
        finally:
            for task in (ui_task, stop_wait):
                task.cancel()
            await link.close()
            await _close_ui(ws)
            logger.info("session ended server=%s", link.address)


def run() -> None:
    """Serve the local bridge for the desktop UI."""
    bridge = section(CONFIG, "bridge")
    uvicorn.run(
        app,
        host=str(bridge.get("host", "127.0.0.1")),
        port=int(bridge.get("port", 8766)),
        log_level=str(section(CONFIG, "logging").get("level", "info")).lower(),
    )


if __name__ == "__main__":
    run()
