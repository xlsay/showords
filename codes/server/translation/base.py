from __future__ import annotations

from abc import ABC, abstractmethod

from common.schemas import LanguageCode


class Translator(ABC):
    """Translates one utterance between Chinese and English."""

    @abstractmethod
    def translate(self, text: str, *, source_language: str, target_language: LanguageCode) -> str:
        ...
