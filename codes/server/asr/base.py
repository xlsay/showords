from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np

from common.schemas import DetectedLanguage


@dataclass
class ASRSegment:
    start_time: float
    end_time: float
    text: str
    language: DetectedLanguage
    confidence: float


class ASRAdapter(ABC):
    """ASR backend that always auto-detects the spoken language."""

    @abstractmethod
    def transcribe(
        self,
        samples: np.ndarray,
        sample_rate: int,
        *,
        offset_seconds: float = 0.0,
    ) -> list[ASRSegment]:
        ...
