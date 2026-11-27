from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Iterable

import yaml

logger = logging.getLogger(__name__)

APP_DIR = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = APP_DIR / "config.yaml"

# Environment overrides applied on top of config.yaml by the desktop app.
ENV_OVERRIDES: dict[str, tuple[str, ...]] = {
    "MEETINGASSIST_SERVER_HOST": ("server", "host"),
    "MEETINGASSIST_SERVER_PORT": ("server", "port"),
    "MEETINGASSIST_SERVER_TOKEN": ("server", "token"),
    "MEETINGASSIST_BRIDGE_PORT": ("bridge", "port"),
    "MEETINGASSIST_LOG_LEVEL": ("logging", "level"),
}

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
    if isinstance(current, int) and not isinstance(current, bool):
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


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    """Read config.yaml and apply environment overrides."""
    with open(path, "r", encoding="utf-8") as handle:
        cfg = yaml.safe_load(handle) or {}
    for env_name, key_path in ENV_OVERRIDES.items():
        raw = os.environ.get(env_name)
        if raw is not None and raw.strip():
            _set_path(cfg, key_path, _coerce_like(raw.strip(), _get_path(cfg, key_path)))
    return cfg


def get_config() -> dict[str, Any]:
    """Return the process-wide config, loading it on first use."""
    global _cached_config
    if _cached_config is None:
        _cached_config = load_config()
    return _cached_config


def section(cfg: dict[str, Any], *path: str) -> dict[str, Any]:
    node = _get_path(cfg, path)
    return node if isinstance(node, dict) else {}
