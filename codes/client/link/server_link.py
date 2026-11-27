"""WebSocket link from the client to the MeetingAssist server."""
from __future__ import annotations

import asyncio
import json
import logging
import urllib.request
from typing import Any, AsyncIterator, Optional

import numpy as np
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed

logger = logging.getLogger(__name__)

# Direct connections only: a LAN server must not be routed through a system proxy.
_NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class ServerRejected(Exception):
    """The server refused the session (bad token, busy, not ready, ...)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _url_host(host: str) -> str:
    return f"[{host}]" if ":" in host and not host.startswith("[") else host  # bracket IPv6


def server_base(host: str, port: int, scheme: str) -> str:
    return f"{scheme}://{_url_host(host)}:{port}"


def fetch_server_health(host: str, port: int, timeout: float) -> dict[str, Any]:
    """GET the server's /health; raises on any network failure."""
    url = f"{server_base(host, port, 'http')}/health"
    with _NO_PROXY_OPENER.open(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


class ServerLink:
    """Streams int16 PCM up to the server and yields its JSON events back."""

    def __init__(self, *, host: str, port: int, token: str, connect_timeout: float) -> None:
        self._host = host
        self._port = port
        self._token = token
        self._connect_timeout = connect_timeout
        self._ws: Optional[ClientConnection] = None
        self._first_event: Optional[dict[str, Any]] = None

    @property
    def address(self) -> str:
        return f"{self._host}:{self._port}"

    async def connect(self, *, sample_rate: int, source: str) -> None:
        """Open the socket, authenticate, and wait for the server to accept the session."""
        url = f"{server_base(self._host, self._port, 'ws')}/ws/stream"
        self._ws = await connect(url, open_timeout=self._connect_timeout, proxy=None, max_size=2**20)
        await self._ws.send(
            json.dumps({"type": "start", "token": self._token, "sample_rate": sample_rate, "source": source})
        )
        first = await self._recv_event(timeout=self._connect_timeout)
        if first is None:
            raise ServerRejected("closed", "Server closed the connection during setup.")
        if first.get("type") == "error":
            payload = first.get("payload") or {}
            await self.close()
            raise ServerRejected(str(payload.get("code", "rejected")), str(payload.get("message", "Rejected.")))
        self._first_event = first

    async def _recv_event(self, *, timeout: float) -> Optional[dict[str, Any]]:
        assert self._ws is not None
        try:
            raw = await asyncio.wait_for(self._ws.recv(), timeout=timeout)
        except ConnectionClosed:
            return None
        try:
            event = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return None
        return event if isinstance(event, dict) else None

    async def send_audio(self, samples: np.ndarray) -> None:
        if self._ws is None:
            return
        pcm = (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2")
        await self._ws.send(pcm.tobytes())

    async def stop(self) -> None:
        """Ask the server to finish; it replies with final results, then closes."""
        if self._ws is None:
            return
        try:
            await self._ws.send(json.dumps({"type": "stop"}))
        except ConnectionClosed:
            pass

    async def events(self) -> AsyncIterator[dict[str, Any]]:
        if self._first_event is not None:
            yield self._first_event
            self._first_event = None
        if self._ws is None:
            return
        try:
            async for message in self._ws:
                if isinstance(message, bytes):
                    continue
                try:
                    event = json.loads(message)
                except json.JSONDecodeError:
                    continue
                if isinstance(event, dict) and "type" in event:
                    yield event
        except ConnectionClosed:
            return

    async def close(self) -> None:
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
