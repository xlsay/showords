"""Audio received over the network, re-chunked into fixed analysis windows."""
from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator, Optional

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class AudioChunk:
    """A slice of mono float32 PCM."""

    samples: np.ndarray  # shape (N,), dtype float32, range ~[-1, 1]
    sample_rate: int
    start_time: float  # seconds since session start


class AudioSource(ABC):
    @property
    @abstractmethod
    def sample_rate(self) -> int:
        ...

    @abstractmethod
    async def stream(self) -> AsyncIterator[AudioChunk]:
        ...

    async def aclose(self) -> None:
        return None


class PushAudioSource(AudioSource):
    """Accepts int16 PCM frames from a client and yields fixed-size chunks."""

    def __init__(self, *, sample_rate: int, chunk_seconds: float, max_queued_seconds: float) -> None:
        self._sample_rate = sample_rate
        self._chunk_frames = max(1, int(sample_rate * chunk_seconds))
        self._max_queued = max(self._chunk_frames, int(sample_rate * max_queued_seconds))
        self._queue: asyncio.Queue[Optional[np.ndarray]] = asyncio.Queue()
        self._queued = 0
        self._closed = False
        self.dropped_frames = 0

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    def push_pcm16(self, data: bytes) -> bool:
        """Queue one frame; returns False when the frame was dropped."""
        if self._closed or not data:
            return False
        usable = len(data) - (len(data) % 2)  # int16 needs an even byte count
        samples = np.frombuffer(data[:usable], dtype="<i2").astype(np.float32) / 32768.0
        if self._queued + samples.size > self._max_queued:
            self.dropped_frames += 1
            return False
        self._queued += samples.size
        self._queue.put_nowait(samples)
        return True

    async def stream(self) -> AsyncIterator[AudioChunk]:
        buffer = np.zeros(0, dtype=np.float32)
        t0 = 0.0
        while True:
            item = await self._queue.get()
            if item is None:
                break
            self._queued -= item.size
            buffer = np.concatenate([buffer, item])
            while buffer.size >= self._chunk_frames:
                chunk, buffer = buffer[: self._chunk_frames], buffer[self._chunk_frames :]
                yield AudioChunk(samples=chunk, sample_rate=self._sample_rate, start_time=t0)
                t0 += chunk.size / self._sample_rate
        if buffer.size:
            yield AudioChunk(samples=buffer, sample_rate=self._sample_rate, start_time=t0)

    async def aclose(self) -> None:
        """End the stream after every frame already queued has been yielded."""
        if not self._closed:
            self._closed = True
            self._queue.put_nowait(None)
