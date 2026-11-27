from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
import logging
import time
from typing import Any

from common.config import get_config, section

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class OpenAICompatibleConfig:
    api_key: str
    base_url: str
    model: str
    timeout_seconds: float = 45.0


class OpenAICompatibleClient:
    """Non-streaming stdlib client for OpenAI-compatible chat-completions APIs."""

    def __init__(self, config: OpenAICompatibleConfig) -> None:
        self._cfg = config

    @classmethod
    def from_config(cls, llm_cfg: dict[str, Any] | None = None) -> "OpenAICompatibleClient | None":
        """Build a client from the llm section of config.yaml, or None without a key."""
        cfg = llm_cfg if llm_cfg is not None else section(get_config(), "llm")
        api_key = str(cfg.get("api_key") or "").strip()
        if not api_key:
            return None

        base_url = str(cfg.get("base_url") or "").strip() or "https://api.openai.com/v1"
        model = str(cfg.get("model") or "").strip() or "gpt-4o-mini"
        return cls(
            OpenAICompatibleConfig(
                api_key=api_key,
                base_url=base_url.rstrip("/"),
                model=model,
                timeout_seconds=float(cfg.get("timeout_seconds", 45)),
            )
        )

    @property
    def model(self) -> str:
        return self._cfg.model

    def chat(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int,
        temperature: float = 0.2,
    ) -> str:
        base_url = self._cfg.base_url.rstrip("/")
        if base_url.endswith("/v1"):
            url = f"{base_url}/chat/completions"
        else:
            url = f"{base_url}/v1/chat/completions"
        body: dict[str, Any] = {
            "model": self._cfg.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._cfg.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        start = time.time()
        _LOGGER.debug("LLM request start model=%s url=%s", self._cfg.model, url)
        try:
            with urllib.request.urlopen(req, timeout=self._cfg.timeout_seconds) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            _LOGGER.warning(
                "LLM HTTP error model=%s url=%s code=%s detail=%s",
                self._cfg.model,
                url,
                exc.code,
                detail,
            )
            raise RuntimeError(f"LLM HTTP {exc.code}: {detail}") from exc
        finally:
            duration = time.time() - start
            _LOGGER.debug("LLM request finished model=%s duration=%.3fs", self._cfg.model, duration)

        data = json.loads(raw)
        choice = data.get("choices", [{}])[0]
        message = choice.get("message", {}) if isinstance(choice, dict) else {}
        content = ""
        # Primary: standard OpenAI-style chat message content
        if isinstance(message, dict):
            content = message.get("content") or message.get("reasoning") or message.get("text") or ""
        # Fallbacks for other provider shapes
        if not content:
            content = choice.get("text") if isinstance(choice, dict) else ""
        content = (content or "").strip()
        if not content:
            _LOGGER.warning(
                "LLM returned empty content for model=%s; raw_response=%s",
                self._cfg.model,
                raw if len(raw) < 4000 else raw[:4000] + "...",
            )
        return content
