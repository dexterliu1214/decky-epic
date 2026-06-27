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


def _wide_url(metadata: dict) -> Optional[str]:
    """Pick a wide/landscape image from Epic keyImages — used for both the Steam
    Hero (big library-page background) and the Header (small landscape capsule).
    Falls back to the square box art when a title has no true wide image."""
    images = (metadata or {}).get("keyImages") or []
    by_type = {img.get("type"): img.get("url") for img in images if img.get("url")}
    for t in ("DieselGameBoxWide", "DieselStoreFrontWide", "OfferImageWide",
              "TakeoverWide", "DieselGameBox"):
        if by_type.get(t):
            return by_type[t]
    return None


def _logo_url(metadata: dict) -> Optional[str]:
    """Pick the transparent game-logo image (shown over the Hero), if any.
    Only ~5% of Epic titles ship one, so there's no fallback — leave the Steam
    Logo slot empty rather than stuffing it with non-transparent box art."""
    images = (metadata or {}).get("keyImages") or []
    by_type = {img.get("type"): img.get("url") for img in images if img.get("url")}
    for t in ("DieselGameBoxLogo", "OfferImageLogo"):
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


def _is_game(summary: dict) -> bool:
    """True for actual games. Epic libraries also carry Unreal Engine assets,
    plugins, add-ons, and software — those lack the "games" category path."""
    return "games" in (summary.get("categories") or [])


# Map our settings' Steam-style language codes to Epic catalog locale codes, so
# game titles and descriptions come back localized straight from Epic.
_EPIC_LOCALE = {
    "english": "en",
    "tchinese": "zh-Hant",
    "schinese": "zh-Hans",
    "japanese": "ja",
    "koreana": "ko",
    "french": "fr",
    "german": "de",
    "spanish": "es-ES",
    "italian": "it",
    "portuguese": "pt-BR",
    "russian": "ru",
    "thai": "th",
}


def epic_locale(steam_lang: str) -> str:
    return _EPIC_LOCALE.get(steam_lang or "english", "en")


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
        self._locale = "en"  # Epic catalog locale for titles/descriptions

    def set_locale(self, steam_lang: str) -> None:
        """Point legendary's Epic catalog queries at the user's language so the
        library's titles and descriptions come back localized."""
        loc = epic_locale(steam_lang)
        self._locale = loc
        # Epic wants language and country separately (e.g. zh-Hant / US).
        self._core.language_code = loc
        self._core.egs.language_code = loc

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

    def _fetch_library_blocking(self, force_meta: bool = False) -> list[dict]:
        try:
            self._core.login()
        except Exception as e:
            _log.warning("login during library fetch failed: %r", e)
        # force_meta re-pulls every game's catalog metadata so titles and
        # descriptions come back in the current locale (16-way parallel inside
        # legendary, ~15s for the whole library).
        games = self._core.get_game_and_dlc_list(update_assets=True, force_refresh=force_meta)[0]
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
    def _read_library_cache() -> Optional[dict]:
        try:
            with open(LIBRARY_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def _write_library_cache(self, games: list[dict]) -> None:
        try:
            tmp = LIBRARY_CACHE_FILE.with_suffix(".json.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"ts": time.time(), "locale": self._locale, "games": games}, f)
            tmp.replace(LIBRARY_CACHE_FILE)
        except Exception as e:
            _log.warning("could not write library cache: %r", e)

    async def library(self, force_refresh: bool = False) -> list[dict]:
        if not force_refresh:
            cached = self._read_library_cache()
            if cached:
                games = await self.run(self._overlay_installed_blocking, cached.get("games") or [])
                return [g for g in games if _is_game(g)]
        games = await self.run(self._fetch_library_blocking, False)
        self._write_library_cache(games)
        return [g for g in games if _is_game(g)]

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

    async def update_status(self, app_name: str) -> dict:
        """Whether an installed game has a newer build on Epic. Refreshes the
        asset list (light) and compares build versions via legendary."""
        def _u() -> dict:
            ig = self._core.get_installed_game(app_name)
            if not ig:
                return {"installed": False, "update_available": False}
            try:
                latest = self._core.is_latest(app_name)
                return {"installed": True, "update_available": not latest, "version": ig.version}
            except Exception as e:
                _log.warning("update check failed for %s: %r", app_name, e)
                return {"installed": True, "update_available": False, "error": f"{e}"}

        return await self.run(_u)

    async def description(self, app_name: str) -> dict:
        """Localized title + synopsis from Epic's catalog. Does ONE lightweight
        catalog query at the configured locale (no achievements/manifests, which
        is what makes a full library re-fetch rate-limit), falling back to the
        cached (English) metadata if the query fails."""
        def _d() -> dict:
            try:
                g = self._core.get_game(app_name)
                md = getattr(g, "metadata", {}) or {}
            except Exception:
                return {"title": app_name, "description": ""}
            title = md.get("title") or app_name
            desc = md.get("description") or ""
            ns, cid = md.get("namespace"), md.get("id")
            if ns and cid and self._locale != "en":
                try:
                    info = self._core.egs.get_game_info(ns, cid, timeout=10.0)
                    if info:
                        title = info.get("title") or title
                        desc = info.get("description") or desc
                except Exception as e:
                    _log.warning("localized catalog fetch failed for %s: %r", app_name, e)
            return {"title": title, "description": desc}

        return await self.run(_d)

    async def artwork_b64(self, app_name: str) -> dict:
        """Download the game's Epic art, base64-encoded, so the frontend can set
        every Steam shortcut artwork (no CORS): portrait Capsule, wide Hero
        background, landscape Header, and the transparent Logo when one exists.
        Hero and Header share the same wide image (downloaded once)."""
        def _fetch() -> dict:
            try:
                g = self._core.get_game(app_name)
                md = getattr(g, "metadata", {}) or {}
            except Exception as e:
                return {"ok": False, "error": f"{e}"}
            cover = _download_b64(_cover_url(md))
            wide = _download_b64(_wide_url(md))   # Hero + Header
            logo = _download_b64(_logo_url(md))
            if not any((cover, wide, logo)):
                return {"ok": False, "error": "No artwork available."}
            return {"ok": True, "cover": cover, "hero": wide, "header": wide, "logo": logo}

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
