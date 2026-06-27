"""Tiny JSON-backed settings store."""
from __future__ import annotations

import json
import logging
import os
import re
import threading
from typing import Any

from . import paths

_log = logging.getLogger("decky-epic.settings")

# Languages we support (Steam-style codes, matching the Settings dropdown).
_SUPPORTED_LANGS = {
    "english", "tchinese", "schinese", "japanese", "koreana", "french",
    "german", "spanish", "italian", "portuguese", "russian", "thai",
}
# Odd Steam UI codes -> our supported set.
_STEAM_LANG_ALIAS = {"brazilian": "portuguese", "latam": "spanish"}
# System locale prefix -> our code.
_LOCALE_LANG = {
    "zh_tw": "tchinese", "zh_hk": "tchinese", "zh_cn": "schinese", "zh": "schinese",
    "ja": "japanese", "ko": "koreana", "fr": "french", "de": "german",
    "es": "spanish", "it": "italian", "pt": "portuguese", "ru": "russian",
    "th": "thai", "en": "english",
}


def _detect_language() -> str:
    """Default the game-info language to what SteamOS is already set to: the
    Steam client UI language (its codes match ours), falling back to the system
    locale, then English."""
    for p in ("~/.steam/registry.vdf", "~/.local/share/Steam/registry.vdf",
              "~/.steam/steam/registry.vdf"):
        fp = os.path.expanduser(p)
        if not os.path.isfile(fp):
            continue
        try:
            with open(fp, "r", errors="ignore") as f:
                m = re.search(r'"language"\s*"([^"]+)"', f.read())
            if m:
                code = _STEAM_LANG_ALIAS.get(m.group(1).strip().lower(), m.group(1).strip().lower())
                if code in _SUPPORTED_LANGS:
                    return code
        except Exception:
            pass
        break
    loc = (os.environ.get("LANG") or os.environ.get("LC_ALL") or "").split(".")[0].lower()
    return _LOCALE_LANG.get(loc) or _LOCALE_LANG.get(loc.split("_")[0]) or "english"


DEFAULTS: dict[str, Any] = {
    "install_base_path": str(paths.DEFAULT_INSTALL_DIR),
    "preferred_proton": "",
    "max_workers": 0,
    "reviews_cache_ttl_days": 14,
    # Game title/synopsis language (Steam-style code). Defaults to the SteamOS /
    # Steam-client language; the user can override it in Settings.
    "preferred_language": _detect_language(),
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

    # --- Steam shortcut id map (app_name -> non-Steam shortcut appid) --------
    # Persisted so Game-Mode launches reuse one shortcut (and thus one Proton
    # prefix) instead of creating a new shortcut — and a fresh save folder —
    # every launch.
    def get_shortcut_id(self, app_name: str):
        with self._lock:
            return (self._data.get("steam_shortcuts") or {}).get(app_name)

    def set_shortcut_id(self, app_name: str, appid: int) -> None:
        with self._lock:
            m = dict(self._data.get("steam_shortcuts") or {})
            m[app_name] = int(appid)
            self._data["steam_shortcuts"] = m
            self._save()

    def remove_shortcut_id(self, app_name: str) -> None:
        with self._lock:
            m = dict(self._data.get("steam_shortcuts") or {})
            if app_name in m:
                del m[app_name]
                self._data["steam_shortcuts"] = m
                self._save()
