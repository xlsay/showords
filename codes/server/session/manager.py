from __future__ import annotations

import asyncio
import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional

from asr.base import ASRAdapter
from audio.source import AudioChunk, AudioSource
from audio.vad import PreVadSegmenter
from common.schemas import (
    AudioSourceName,
    ErrorPayload,
    LanguageCode,
    SessionStatePayload,
    TranslationPayload,
    Utterance,
    UtterancePayload,
)
from translation.base import Translator

logger = logging.getLogger(__name__)


@dataclass
class SessionConfig:
    source_name: AudioSourceName
    sample_rate: int
    vad_enabled: bool
    vad_threshold: float
    vad_energy_rms_threshold: float
    vad_pre_speech_pad_ms: int
    vad_post_speech_pad_ms: int
    vad_trailing_silence_seconds: float
    vad_max_segment_seconds: float
    min_confidence: float
    asr_workers: int
    translation_enabled: bool
    translation_pairs: dict[str, str]
    translation_workers: int
    stop_drain_seconds: float


@dataclass
class SessionEvent:
    type: str
    payload: dict = field(default_factory=dict)


class SessionManager:
    """Turns captured audio into utterances with translations, one event per step."""

    def __init__(
        self,
        *,
        audio_source: AudioSource,
        asr: ASRAdapter,
        translator: Translator,
        config: SessionConfig,
    ) -> None:
        self._source = audio_source
        self._asr = asr
        self._translator = translator
        self._cfg = config
        self._segmenter = PreVadSegmenter(
            sample_rate=config.sample_rate,
            enabled=config.vad_enabled,
            detector_threshold=config.vad_threshold,
            detector_energy_rms_threshold=config.vad_energy_rms_threshold,
            pre_speech_pad_ms=config.vad_pre_speech_pad_ms,
            post_speech_pad_ms=config.vad_post_speech_pad_ms,
            trailing_silence_seconds=config.vad_trailing_silence_seconds,
            max_segment_seconds=config.vad_max_segment_seconds,
        )
        self._events: asyncio.Queue[Optional[SessionEvent]] = asyncio.Queue(maxsize=256)
        self._asr_pool = ThreadPoolExecutor(max_workers=max(1, config.asr_workers))
        self._translate_pool = ThreadPoolExecutor(max_workers=max(1, config.translation_workers))
        self._translate_tasks: set[asyncio.Task] = set()
        self._utterances: list[Utterance] = []
        self._started_at = time.monotonic()
        self._run_task: Optional[asyncio.Task] = None
        self._last_translation_error: Optional[str] = None

    @property
    def utterances(self) -> list[Utterance]:
        return list(self._utterances)

    async def start(self) -> None:
        self._started_at = time.monotonic()
        await self._emit("session_state", self._state_payload("starting"))
        self._run_task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """Finish queued audio and pending translations within the drain budget, then end."""
        await self._source.aclose()
        deadline = time.monotonic() + max(0.0, self._cfg.stop_drain_seconds)
        if self._run_task is not None:
            try:
                await asyncio.wait_for(self._run_task, timeout=max(0.1, deadline - time.monotonic()))
            except (asyncio.TimeoutError, asyncio.CancelledError):
                logger.warning("stop drain timed out; dropping remaining audio")
        if self._translate_tasks:
            _, pending = await asyncio.wait(
                set(self._translate_tasks), timeout=max(0.1, deadline - time.monotonic())
            )
            for task in pending:
                task.cancel()
        self._asr_pool.shutdown(wait=False, cancel_futures=True)
        self._translate_pool.shutdown(wait=False, cancel_futures=True)
        await self._emit("session_state", self._state_payload("ended"))
        await self._events.put(None)

    async def events(self) -> AsyncIterator[SessionEvent]:
        while True:
            item = await self._events.get()
            if item is None:
                return
            yield item

    async def _run(self) -> None:
        try:
            await self._emit("session_state", self._state_payload("running"))
            async for chunk in self._source.stream():
                for segment in self._segmenter.push(chunk):
                    await self._handle_segment(segment)
            for segment in self._segmenter.finish():
                await self._handle_segment(segment)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("session loop failed")
            await self._emit("error", ErrorPayload(code="processing_failed", message=str(exc)))

    async def _handle_segment(self, segment: AudioChunk) -> None:
        loop = asyncio.get_running_loop()
        try:
            asr_segments = await loop.run_in_executor(
                self._asr_pool,
                lambda: self._asr.transcribe(
                    segment.samples,
                    segment.sample_rate,
                    offset_seconds=segment.start_time,
                ),
            )
        except Exception as exc:
            logger.warning("transcription failed: %s", exc)
            await self._emit("error", ErrorPayload(code="asr_failed", message=str(exc)))
            return

        kept = [s for s in asr_segments if s.confidence >= self._cfg.min_confidence]
        if not kept:
            return

        text = self._join_text(kept)
        if not text:
            return

        language = next((s.language for s in kept if s.language != "unknown"), "unknown")
        utterance = Utterance(
            id=uuid.uuid4().hex,
            index=len(self._utterances),
            start_time=kept[0].start_time,
            end_time=kept[-1].end_time,
            language=language,
            text=text,
            target_language=self._target_language(language),
        )
        self._utterances.append(utterance)
        await self._emit(
            "utterance",
            UtterancePayload(
                id=utterance.id,
                index=utterance.index,
                start_time=utterance.start_time,
                end_time=utterance.end_time,
                language=utterance.language,
                text=utterance.text,
                target_language=utterance.target_language,
            ),
        )

        if utterance.target_language is not None:
            task = asyncio.create_task(self._translate(utterance))
            self._translate_tasks.add(task)
            task.add_done_callback(self._translate_tasks.discard)

    async def _translate(self, utterance: Utterance) -> None:
        target = utterance.target_language
        if target is None:
            return
        loop = asyncio.get_running_loop()
        try:
            translation = await loop.run_in_executor(
                self._translate_pool,
                lambda: self._translator.translate(
                    utterance.text,
                    source_language=utterance.language,
                    target_language=target,
                ),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            message = str(exc)
            # Report a repeated translation failure once, not per utterance.
            if message != self._last_translation_error:
                self._last_translation_error = message
                await self._emit("error", ErrorPayload(code="translation_failed", message=message))
            return

        self._last_translation_error = None
        if not translation:
            return
        utterance.translation = translation
        await self._emit(
            "translation",
            TranslationPayload(id=utterance.id, target_language=target, translation=translation),
        )

    def _target_language(self, language: str) -> Optional[LanguageCode]:
        if not self._cfg.translation_enabled:
            return None
        target = self._cfg.translation_pairs.get(language)
        return target if target in ("zh", "en") else None  # type: ignore[return-value]

    @staticmethod
    def _join_text(segments: list) -> str:
        parts = [s.text.strip() for s in segments if s.text.strip()]
        if not parts:
            return ""
        # Chinese needs no separator between pieces; Latin scripts do.
        joiner = "" if all(_is_cjk(p[-1]) for p in parts[:-1]) else " "
        return joiner.join(parts).strip()

    def _state_payload(self, state: str) -> SessionStatePayload:
        return SessionStatePayload(
            state=state,  # type: ignore[arg-type]
            source=self._cfg.source_name,
            elapsed_seconds=max(0.0, time.monotonic() - self._started_at),
            utterance_count=len(self._utterances),
        )

    async def _emit(self, event_type: str, payload) -> None:
        event = SessionEvent(type=event_type, payload=payload.model_dump(mode="json"))
        try:
            self._events.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning("event queue full, dropping %s", event_type)


_CJK_PUNCTUATION = "\u3002\uff0c\uff01\uff1f\u3001\uff1b\uff1a\u201d\u2019\uff09\u300b"


def _is_cjk(char: str) -> bool:
    return "\u4e00" <= char <= "\u9fff" or char in _CJK_PUNCTUATION
