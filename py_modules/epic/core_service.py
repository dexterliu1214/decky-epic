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
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Optional

from . import paths

_log = logging.getLogger("decky-epic.core")

# Persisted library snapshot so opening the library is instant instead of a
# ~10s network round-trip every time. The "installed" flag is re-overlaid live
# from the local installed list, so only purchases/removals need a refresh.
LIBRARY_CACHE_FILE = paths.CACHE_DIR / "library.json"

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


def _hero_url(metadata: dict) -> Optional[str]:
    """Pick a wide/landscape image from Epic keyImages for the Steam Hero
    (the big background on a game's library page)."""
    images = (metadata or {}).get("keyImages") or []
    by_type = {img.get("type"): img.get("url") for img in images if img.get("url")}
    for t in ("DieselGameBoxWide", "DieselStoreFrontWide", "OfferImageWide",
              "TakeoverWide", "DieselGameBox"):
        if by_type.get(t):
            return by_type[t]
    return None


def _download_b64(url: Optional[str]) -> Optional[dict]:
    """Fetch an image URL and return {b64, type} (jpg/png), or None on failure."""
    if not url:
        return None
    try:
        import base64
        import requests
        r = requests.get(url, timeout=20)
        r.raise_for_status()
    except Exception:
        return None
    ctype = (r.headers.get("Content-Type") or "").lower()
    img_type = "png" if ("png" in ctype or url.lower().endswith(".png")) else "jpg"
    return {"b64": base64.b64encode(r.content).decode("ascii"), "type": img_type}


def _supports_cloud_saves(metadata: dict) -> bool:
    ca = (metadata or {}).get("customAttributes") or {}
    return bool(ca.get("CloudSaveFolder", {}).get("value"))


class EpicCore:
    def __init__(self) -> None:
        paths.apply_legendary_env()
        # Imported lazily, AFTER the config env var is set, and after vendored
        # deps are on sys.path (Decky adds py_modules automatically).
        from legendary.core import LegendaryCore
        from .legendary_lock import apply_installed_json_locking
        apply_installed_json_locking()  # cross-process-safe installed.json writes

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

    def _fetch_library_blocking(self) -> list[dict]:
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

    def _overlay_installed_blocking(self, games: list[dict]) -> list[dict]:
        try:
            installed = {ig.app_name for ig in self._core.get_installed_list()}
            for g in games:
                g["installed"] = g["app_name"] in installed
        except Exception as e:
            _log.warning("installed overlay failed: %r", e)
        return games

    @staticmethod
    def _read_library_cache() -> Optional[list[dict]]:
        try:
            with open(LIBRARY_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f).get("games")
        except Exception:
            return None

    @staticmethod
    def _write_library_cache(games: list[dict]) -> None:
        try:
            tmp = LIBRARY_CACHE_FILE.with_suffix(".json.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"ts": time.time(), "games": games}, f)
            tmp.replace(LIBRARY_CACHE_FILE)
        except Exception as e:
            _log.warning("could not write library cache: %r", e)

    async def library(self, force_refresh: bool = False) -> list[dict]:
        if not force_refresh:
            cached = self._read_library_cache()
            if cached:
                # Cheap local refresh of just the installed flags.
                return await self.run(self._overlay_installed_blocking, cached)
        games = await self.run(self._fetch_library_blocking)
        self._write_library_cache(games)
        return games

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

    async def steam_launch_info(self, app_name: str) -> dict:
        """Resolve what the frontend needs to create a non-Steam shortcut for
        this game (so it shows in Game Mode via gamescope). The frontend handles
        AddShortcut / compat tool / RunGame."""
        def _info() -> dict:
            import os
            ig = self._core.get_installed_game(app_name)
            if not ig:
                return {"ok": False, "error": "Game is not installed."}
            exe = os.path.join(ig.install_path, ig.executable)
            cover = None
            try:
                g = self._core.get_game(app_name)
                cover = _cover_url(getattr(g, "metadata", {}) or {})
            except Exception as e:
                _log.warning("cover lookup failed for %s: %r", app_name, e)
            # Host-side cloud-save wrapper: pulls before launch, pushes after
            # exit, resolving saves against Steam's actual Proton prefix.
            wrapper = paths.PLUGIN_DIR / "py_modules" / "epic" / "steam_save_wrapper.sh"
            launch_options = f'bash "{wrapper}" {app_name} %command%'
            return {
                "ok": True,
                "app_name": app_name,
                "name": ig.title,          # display name only; no ".exe"
                "exe": exe,
                "start_dir": ig.install_path,
                "cover": cover,
                "launch_options": launch_options,
            }

        return await self.run(_info)

    async def artwork_b64(self, app_name: str) -> dict:
        """Download the game's portrait cover and wide hero art, base64-encoded,
        so the frontend can set both Steam shortcut artworks (no CORS): the
        portrait capsule and the big library-page background (Hero)."""
        def _fetch() -> dict:
            try:
                g = self._core.get_game(app_name)
                md = getattr(g, "metadata", {}) or {}
            except Exception as e:
                return {"ok": False, "error": f"{e}"}
            cover = _download_b64(_cover_url(md))
            hero = _download_b64(_hero_url(md))
            if not cover and not hero:
                return {"ok": False, "error": "No artwork available."}
            return {"ok": True, "cover": cover, "hero": hero}

        return await self.run(_fetch)


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
