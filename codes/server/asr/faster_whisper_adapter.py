from __future__ import annotations

import logging
import math
from typing import Optional, Sequence

import numpy as np

from common.schemas import DetectedLanguage
from .base import ASRAdapter, ASRSegment

logger = logging.getLogger(__name__)

_SUPPORTED: tuple[DetectedLanguage, ...] = ("zh", "en")


def _normalize_language(code: Optional[str]) -> DetectedLanguage:
    if not code:
        return "unknown"
    code = code.lower()
    return code if code in _SUPPORTED else "unknown"  # type: ignore[return-value]


class FasterWhisperAdapter(ASRAdapter):
    """ASR via faster-whisper with per-utterance language detection."""

    def __init__(
        self,
        *,
        model_size: str = "medium",
        device: str = "cpu",
        compute_type: str = "int8",
        beam_size: int = 1,
        cpu_threads: int = 0,
        num_workers: int = 1,
        download_root: Optional[str] = None,
        vad_threshold: float = 0.3,
        vad_min_speech_ms: int = 100,
        vad_min_silence_ms: int = 300,
        vad_speech_pad_ms: int = 400,
        languages: Sequence[str] = ("zh", "en"),
    ) -> None:
        self._languages = tuple(code.lower() for code in languages)
        self._model_size = model_size
        self._device = device
        self._compute_type = compute_type
        self._beam_size = max(1, beam_size)
        self._cpu_threads = max(0, cpu_threads)
        self._num_workers = max(1, num_workers)
        self._download_root = download_root
        self._vad_threshold = vad_threshold
        self._vad_min_speech_ms = max(0, vad_min_speech_ms)
        self._vad_min_silence_ms = max(0, vad_min_silence_ms)
        self._vad_speech_pad_ms = max(0, vad_speech_pad_ms)
        self._model = None  # lazy
        self._oom_fallback_activated = False

    @property
    def model_size(self) -> str:
        return self._model_size

    @property
    def device(self) -> str:
        return self._device

    @property
    def compute_type(self) -> str:
        return self._compute_type

    def _compute_type_fallback_chain(self) -> list[str]:
        preferred = (self._compute_type or "").strip().lower() or "int8"
        if (self._device or "cpu").strip().lower() == "cpu":
            # float16 on CPU is often unsupported or slow.
            order = [preferred, "int8", "float32"]
        else:
            order = [preferred, "float16", "int8", "float32"]
        chain: list[str] = []
        for item in order:
            if item not in chain:
                chain.append(item)
        return chain

    def ensure_loaded(self) -> None:
        """Load the model up front so the first utterance does not pay for it."""
        self._ensure_model()

    def _ensure_model(self):
        if self._model is not None:
            return self._model

        from faster_whisper import WhisperModel

        last_exc: Exception | None = None
        for idx, compute_type in enumerate(self._compute_type_fallback_chain()):
            if idx > 0:
                logger.warning("retrying model load with fallback compute=%s", compute_type)
            else:
                logger.info(
                    "loading faster-whisper size=%s device=%s compute=%s",
                    self._model_size,
                    self._device,
                    compute_type,
                )
            try:
                self._model = WhisperModel(
                    self._model_size,
                    device=self._device,
                    compute_type=compute_type,
                    cpu_threads=self._cpu_threads,
                    num_workers=self._num_workers,
                    download_root=self._download_root,
                )
                self._compute_type = compute_type
                break
            except Exception as exc:
                last_exc = exc
                msg = str(exc).lower()
                # Keep trying only for a compute-type incompatibility.
                if not any(k in msg for k in ("compute type", "float16", "not support", "unsupported")):
                    raise
        if self._model is None and last_exc is not None:
            raise last_exc
        return self._model

    def _maybe_activate_oom_fallback(self, exc: Exception) -> bool:
        """Switch CUDA Whisper to CPU/int8 once after a CUDA out-of-memory error."""
        if self._oom_fallback_activated or self._device.lower() != "cuda":
            return False
        if "out of memory" not in str(exc).lower():
            return False
        logger.warning("CUDA out of memory; falling back to CPU/int8")
        self._oom_fallback_activated = True
        self._device = "cpu"
        self._compute_type = "int8"
        self._model = None
        return True

    def _restrict_language(self, info) -> Optional[str]:
        """Most probable allowed language, or None when no restriction applies."""
        if not self._languages or info.language in self._languages:
            return info.language if self._languages else None
        probs = dict(getattr(info, "all_language_probs", None) or [])
        candidates = [(probs.get(code, 0.0), code) for code in self._languages]
        best_prob, best = max(candidates)
        return best if best_prob > 0.0 else None

    def transcribe(
        self,
        samples: np.ndarray,
        sample_rate: int,
        *,
        offset_seconds: float = 0.0,
    ) -> list[ASRSegment]:
        if samples.size == 0:
            return []
        if sample_rate != 16_000:
            raise ValueError(f"FasterWhisperAdapter expects 16 kHz input, got {sample_rate}")
        if samples.dtype != np.float32:
            samples = samples.astype(np.float32)

        kwargs = dict(
            language=None,  # auto-detect per utterance
            vad_filter=True,
            vad_parameters=dict(
                threshold=self._vad_threshold,
                min_speech_duration_ms=self._vad_min_speech_ms,
                min_silence_duration_ms=self._vad_min_silence_ms,
                speech_pad_ms=self._vad_speech_pad_ms,
            ),
            temperature=0.0,
            condition_on_previous_text=False,
            no_repeat_ngram_size=3,
            word_timestamps=False,
            beam_size=self._beam_size,
            best_of=1,
            compression_ratio_threshold=2.4,
            no_speech_threshold=0.4,
        )

        model = self._ensure_model()
        try:
            segments_iter, info = model.transcribe(samples, **kwargs)
        except Exception as exc:
            if not self._maybe_activate_oom_fallback(exc):
                raise
            model = self._ensure_model()
            segments_iter, info = model.transcribe(samples, **kwargs)

        chosen = self._restrict_language(info)
        if chosen is not None and chosen != info.language:
            # Decoding is lazy, so the discarded first pass cost only language detection.
            logger.info("language %s outside %s; decoding as %s", info.language, self._languages, chosen)
            segments_iter, _ = model.transcribe(samples, **{**kwargs, "language": chosen})
        language = _normalize_language(chosen or info.language)
        out: list[ASRSegment] = []
        for seg in segments_iter:
            text = (seg.text or "").strip()
            if not text:
                continue
            avg_logprob = getattr(seg, "avg_logprob", None)
            logprob = float(avg_logprob) if avg_logprob is not None else -0.7
            # Re-center and steepen the sigmoid: raw avg_logprob skews negative.
            confidence = 1.0 / (1.0 + math.exp(-3.5 * (logprob + 0.7)))
            out.append(
                ASRSegment(
                    start_time=offset_seconds + float(seg.start),
                    end_time=offset_seconds + float(seg.end),
                    text=text,
                    language=language,
                    confidence=max(0.0, min(1.0, confidence)),
                )
            )
        return out
