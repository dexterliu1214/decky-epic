"""Async wrapper around legendary's synchronous ``LegendaryCore``.

legendary is a blocking, single-threaded engine and not safe for concurrent use,
so every call is funnelled through one worker thread guarded by an asyncio lock.
The Decky main loop stays responsive while legendary does network / disk work.
"""
from __future__ import annotations

import asyncio
import functools
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Optional

from . import paths

_log = logging.getLogger("decky-epic.core")

EPIC_LOGIN_URL = "https://legendary.gl/epiclogin"


def _cover_url(metadata: dict) -> Optional[str]:
    """Pick a Steam-like tall box-art URL from Epic keyImages."""
    images = (metadata or {}).get("keyImages") or []
    by_type = {img.get("type"): img.get("url") for img in images if img.get("url")}
    for t in ("DieselGameBoxTall", "DieselStoreFrontTall", "OfferImageTall",
              "DieselGameBox", "OfferImageWide", "Thumbnail"):
        if by_type.get(t):
            return by_type[t]
    # fall back to the first available image
    return next(iter(by_type.values()), None)


def _supports_cloud_saves(metadata: dict) -> bool:
    ca = (metadata or {}).get("customAttributes") or {}
    return bool(ca.get("CloudSaveFolder", {}).get("value"))


class EpicCore:
    def __init__(self) -> None:
        paths.apply_legendary_env()
        # Imported lazily, AFTER the config env var is set, and after vendored
        # deps are on sys.path (Decky adds py_modules automatically).
        from legendary.core import LegendaryCore

        self._core = LegendaryCore()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="legendary")
        self._lock = asyncio.Lock()

    @property
    def core(self):  # exposed for download/launch/saves services
        return self._core

    @property
    def executor(self) -> ThreadPoolExecutor:
        return self._executor

    @property
    def lock(self) -> asyncio.Lock:
        return self._lock

    async def run(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        loop = asyncio.get_running_loop()
        async with self._lock:
            return await loop.run_in_executor(
                self._executor, functools.partial(fn, *args, **kwargs)
            )

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    # -- auth ----------------------------------------------------------------
    @staticmethod
    def login_url() -> str:
        return EPIC_LOGIN_URL

    def _display_name(self) -> Optional[str]:
        ud = self._core.lgd.userdata
        return ud.get("displayName") if ud else None

    async def auth_status(self) -> dict:
        def _status() -> dict:
            if not self._core.lgd.userdata:
                return {"logged_in": False, "user": None}
            ok = False
            try:
                ok = self._core.login()
            except Exception as e:  # offline / expired
                _log.warning("login refresh failed: %r", e)
            return {"logged_in": bool(ok), "user": self._display_name()}

        return await self.run(_status)

    async def finish_auth(self, pasted: str) -> dict:
        def _do() -> dict:
            code = _extract_auth_code(pasted)
            if not code:
                return {"ok": False, "error": "No authorization code found in input."}
            try:
                ok = self._core.auth_code(code)
            except Exception as e:
                return {"ok": False, "error": f"{e}"}
            if ok:
                try:
                    self._core.login()
                except Exception as e:
                    _log.warning("post-auth login failed: %r", e)
            return {"ok": bool(ok), "user": self._display_name()}

        return await self.run(_do)

    async def logout(self) -> dict:
        def _do() -> dict:
            self._core.lgd.invalidate_userdata()
            return {"ok": True}

        return await self.run(_do)

    # -- library -------------------------------------------------------------
    def _game_summary(self, game) -> dict:
        md = getattr(game, "metadata", {}) or {}
        return {
            "app_name": game.app_name,
            "title": game.app_title,
            "cover": _cover_url(md),
            "cloud_saves": _supports_cloud_saves(md),
            "categories": [c.get("path") for c in (md.get("categories") or [])],
        }

    async def library(self, force_refresh: bool = False) -> list[dict]:
        def _list() -> list[dict]:
            try:
                self._core.login()
            except Exception as e:
                _log.warning("login during library fetch failed: %r", e)
            games = self._core.get_game_list(update_assets=True)
            installed = {ig.app_name for ig in self._core.get_installed_list()}
            out = []
            for g in games:
                s = self._game_summary(g)
                s["installed"] = g.app_name in installed
                out.append(s)
            return out

        return await self.run(_list)

    async def installed(self) -> list[dict]:
        def _list() -> list[dict]:
            out = []
            for ig in self._core.get_installed_list():
                out.append({
                    "app_name": ig.app_name,
                    "title": ig.title,
                    "version": ig.version,
                    "install_path": ig.install_path,
                    "install_size": ig.install_size,
                })
            return out

        return await self.run(_list)


def _extract_auth_code(pasted: str) -> str:
    """Accept either the raw authorization code or the JSON blob Epic shows
    (``{"authorizationCode":"...", ...}``) and return the code."""
    text = (pasted or "").strip()
    if not text:
        return ""
    if text.startswith("{"):
        try:
            data = json.loads(text)
            return str(data.get("authorizationCode") or data.get("code") or "").strip()
        except Exception:
            return ""
    return text
