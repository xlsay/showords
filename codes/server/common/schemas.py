from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel

LanguageCode = Literal["zh", "en"]
DetectedLanguage = Literal["zh", "en", "unknown"]
SessionState = Literal["starting", "running", "ended"]
AudioSourceName = Literal["microphone", "system"]


class Utterance(BaseModel):
    id: str
    index: int
    start_time: float
    end_time: float
    language: DetectedLanguage
    text: str
    target_language: Optional[LanguageCode] = None
    translation: Optional[str] = None


class UtterancePayload(BaseModel):
    id: str
    index: int
    start_time: float
    end_time: float
    language: DetectedLanguage
    text: str
    target_language: Optional[LanguageCode] = None


class TranslationPayload(BaseModel):
    id: str
    target_language: LanguageCode
    translation: str


class SessionStatePayload(BaseModel):
    state: SessionState
    source: AudioSourceName
    elapsed_seconds: float
    utterance_count: int


class ErrorPayload(BaseModel):
    code: str
    message: str
