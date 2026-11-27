"""Audio capture sources yielding fixed-duration mono float32 chunks."""
from __future__ import annotations

import asyncio
import logging
import queue
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator, Optional

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class AudioChunk:
    """A fixed-duration slice of mono float32 PCM."""

    samples: np.ndarray  # shape (N,), dtype float32, range ~[-1, 1]
    sample_rate: int
    start_time: float  # seconds since session start


class AudioSource(ABC):
    """Abstract audio source. Implementations stream ``AudioChunk``s."""

    @property
    @abstractmethod
    def sample_rate(self) -> int:
        ...

    @abstractmethod
    async def stream(self) -> AsyncIterator[AudioChunk]:
        ...

    async def aclose(self) -> None:
        return None


def _resample_mono(samples: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    if samples.ndim > 1:
        samples = samples.mean(axis=1)
    if src_rate == dst_rate:
        return samples.astype(np.float32, copy=False)
    if len(samples) == 0:
        return np.zeros(0, dtype=np.float32)
    from math import gcd
    from scipy.signal import resample_poly
    g = gcd(src_rate, dst_rate)
    return resample_poly(samples, dst_rate // g, src_rate // g).astype(np.float32)


class MicrophoneSource(AudioSource):
    """Microphone capture via sounddevice."""

    def __init__(
        self,
        *,
        sample_rate: int = 16_000,
        chunk_seconds: float = 0.75,
        device: Optional[int | str] = None,
    ) -> None:
        self._sample_rate = sample_rate
        self._chunk_seconds = chunk_seconds
        self._device = device
        self._stop = threading.Event()
        # Shared queue reference so aclose() can inject a sentinel to unblock q.get().
        self._q: Optional[queue.Queue] = None

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    async def stream(self) -> AsyncIterator[AudioChunk]:
        try:
            import sounddevice as sd
        except Exception as exc:
            import sys
            hint = ""
            if sys.platform.startswith("linux"):
                hint = " On Linux install PortAudio first: sudo apt install portaudio19-dev libportaudio2"
            raise RuntimeError("sounddevice is required for microphone capture." + hint) from exc

        loop = asyncio.get_running_loop()
        q: queue.Queue[Optional[np.ndarray]] = queue.Queue(maxsize=32)
        self._q = q
        chunk_frames = int(self._sample_rate * self._chunk_seconds)

        def _callback(indata, frames, time_info, status):  # noqa: ARG001 - sounddevice API
            if status:
                logger.debug("audio status: %s", status)
            mono = indata.mean(axis=1).astype(np.float32, copy=False).copy()
            try:
                q.put_nowait(mono)
            except queue.Full:
                logger.warning("audio queue full, dropping chunk")

        stream = sd.InputStream(
            samplerate=self._sample_rate,
            channels=1,
            dtype="float32",
            blocksize=chunk_frames,
            device=self._device,
            callback=_callback,
        )
        stream.start()
        logger.info("mic capture started rate=%d device=%s", self._sample_rate, self._device)
        t0 = 0.0
        try:
            while not self._stop.is_set():
                mono = await loop.run_in_executor(None, q.get)
                if mono is None:  # sentinel from aclose()
                    break
                yield AudioChunk(samples=mono, sample_rate=self._sample_rate, start_time=t0)
                t0 += len(mono) / self._sample_rate
        finally:
            stream.stop()
            stream.close()
            self._q = None
            logger.info("mic capture stopped")

    async def aclose(self) -> None:
        self._stop.set()
        if self._q is not None:
            try:
                self._q.put_nowait(None)
            except queue.Full:
                pass
