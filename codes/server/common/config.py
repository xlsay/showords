from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Iterable

import yaml

logger = logging.getLogger(__name__)

APP_DIR = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = APP_DIR / "config.yaml"

# Environment overrides applied on top of config.yaml for deployment.
ENV_OVERRIDES: dict[str, tuple[str, ...]] = {
    "MEETINGASSIST_HOST": ("server", "host"),
    "MEETINGASSIST_PORT": ("server", "port"),
    "MEETINGASSIST_TOKEN": ("server", "token"),
    "MEETINGASSIST_LOG_LEVEL": ("logging", "level"),
    "MEETINGASSIST_WHISPER_SIZE": ("whisper", "model_size"),
    "MEETINGASSIST_WHISPER_DEVICE": ("whisper", "device"),
    "MEETINGASSIST_WHISPER_COMPUTE_TYPE": ("whisper", "compute_type"),
    "MEETINGASSIST_LLM_API_KEY": ("llm", "api_key"),
    "MEETINGASSIST_LLM_BASE_URL": ("llm", "base_url"),
    "MEETINGASSIST_LLM_MODEL": ("llm", "model"),
    "MEETINGASSIST_LLM_TIMEOUT_SECONDS": ("llm", "timeout_seconds"),
}

_AUTO_VALUES = {"", "auto", "none", "default"}

_cached_config: dict[str, Any] | None = None


def _get_path(cfg: dict[str, Any], path: Iterable[str]) -> Any:
    node: Any = cfg
    for part in path:
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _set_path(cfg: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    node = cfg
    for part in path[:-1]:
        node = node.setdefault(part, {})
    node[path[-1]] = value


def _coerce_like(value: str, current: Any) -> Any:
    if isinstance(current, bool):
        return as_bool(value, current)
    if isinstance(current, int):
        try:
            return int(value)
        except ValueError:
            return current
    if isinstance(current, float):
        try:
            return float(value)
        except ValueError:
            return current
    return value


def _apply_env_overrides(cfg: dict[str, Any]) -> None:
    for env_name, path in ENV_OVERRIDES.items():
        raw = os.environ.get(env_name)
        if raw is None or not raw.strip():
            continue
        _set_path(cfg, path, _coerce_like(raw.strip(), _get_path(cfg, path)))


def _resolve_paths(cfg: dict[str, Any]) -> None:
    for key, value in (cfg.get("weights") or {}).items():
        path = Path(str(value)).expanduser()
        cfg["weights"][key] = str(path if path.is_absolute() else APP_DIR / path)


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    """Read config.yaml, apply environment overrides, resolve weight paths."""
    with open(path, "r", encoding="utf-8") as handle:
        cfg = yaml.safe_load(handle) or {}
    _apply_env_overrides(cfg)
    _resolve_paths(cfg)
    return cfg


def get_config() -> dict[str, Any]:
    """Return the process-wide config, loading it on first use."""
    global _cached_config
    if _cached_config is None:
        _cached_config = load_config()
    return _cached_config


def as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    logger.warning("invalid boolean %r, using %s", value, default)
    return default


def is_auto(value: Any) -> bool:
    return value is None or str(value).strip().lower() in _AUTO_VALUES


def pick(value: Any, fallback: Any) -> Any:
    """Return `fallback` when `value` is unset or `auto`."""
    return fallback if is_auto(value) else value


def section(cfg: dict[str, Any], *path: str) -> dict[str, Any]:
    node = _get_path(cfg, path)
    return node if isinstance(node, dict) else {}


def resolve_device(cfg: dict[str, Any], value: Any, hardware_default: str) -> str:
    """Resolve a device: explicit value, else global device, else hardware default."""
    if not is_auto(value):
        return str(value)
    return str(pick(cfg.get("device"), hardware_default))
