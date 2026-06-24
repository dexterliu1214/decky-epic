"""Tiny JSON-backed settings store."""
from __future__ import annotations

import json
import logging
import threading
from typing import Any

from . import paths

_log = logging.getLogger("decky-epic.settings")

DEFAULTS: dict[str, Any] = {
    "rawg_api_key": "",
    "install_base_path": str(paths.DEFAULT_INSTALL_DIR),
    "preferred_proton": "",
    "max_workers": 0,
    "metacritic_cache_ttl_days": 14,
}


class SettingsStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data = dict(DEFAULTS)
        self._load()

    def _load(self) -> None:
        try:
            if paths.SETTINGS_FILE.exists():
                with open(paths.SETTINGS_FILE, "r", encoding="utf-8") as f:
                    self._data.update(json.load(f))
        except Exception as e:
            _log.warning("failed to load settings: %r", e)

    def _save(self) -> None:
        try:
            paths.SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(paths.SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2)
        except Exception as e:
            _log.warning("failed to save settings: %r", e)

    def all(self) -> dict:
        with self._lock:
            return dict(self._data)

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._data.get(key, default)

    def update(self, patch: dict) -> dict:
        with self._lock:
            self._data.update({k: v for k, v in patch.items() if k in DEFAULTS})
            self._save()
            return dict(self._data)
