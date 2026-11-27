from __future__ import annotations

import logging
from typing import Any, Optional

from common.schemas import LanguageCode
from llm.openai_compatible import OpenAICompatibleClient
from .base import Translator

logger = logging.getLogger(__name__)

_LANGUAGE_NAMES: dict[str, str] = {"zh": "Chinese", "en": "English"}

_SYSTEM_PROMPT = (
    "You are a meeting interpreter. Translate the user message into {target}. "
    "Reply with the translation only: no quotes, no notes, no romanization. "
    "Keep names, numbers and technical terms unchanged."
)


class LLMTranslator(Translator):
    """Translator backed by an OpenAI-compatible chat API."""

    def __init__(
        self,
        *,
        llm_config: Optional[dict[str, Any]] = None,
        max_tokens: int = 512,
    ) -> None:
        self._client = OpenAICompatibleClient.from_config(llm_config)
        self._max_tokens = max_tokens

    @property
    def available(self) -> bool:
        return self._client is not None

    def translate(self, text: str, *, source_language: str, target_language: LanguageCode) -> str:
        if self._client is None:
            raise RuntimeError("No LLM API key configured; set llm.api_key in the server config.yaml.")
        content = (text or "").strip()
        if not content:
            return ""
        target_name = _LANGUAGE_NAMES.get(target_language, target_language)
        result = self._client.chat(
            system=_SYSTEM_PROMPT.format(target=target_name),
            user=content,
            max_tokens=self._max_tokens,
            temperature=0.0,
        )
        return result.strip()
