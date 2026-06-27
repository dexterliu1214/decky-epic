from __future__ import annotations

import asyncio

import decky

# Decky adds this plugin's py_modules/ to sys.path, so both our `epic` package
# and the vendored `legendary` import normally.
from epic.core_service import EpicCore
from epic.download_service import DownloadService
from epic.launch_service import LaunchService
from epic.rawg import RawgService
from epic.steam_reviews import SteamReviewsService
from epic.saves_service import SavesService
from epic.settings_store import SettingsStore
from epic import proton


class Plugin:
    """decky-epic backend.

    Public ``async`` methods on this class are exposed to the frontend as RPC
    endpoints (called by name via @decky/api ``call``/``callable``). Keep these
    thin — the real work lives in the ``epic`` package under ``py_modules``.
    """

    core: EpicCore | None = None
    core_error: str | None = None
    settings: SettingsStore | None = None
    downloads: DownloadService | None = None
    rawg: RawgService | None = None
    steam_reviews: SteamReviewsService | None = None
    saves: SavesService | None = None
    launcher: LaunchService | None = None
    _loop: asyncio.AbstractEventLoop | None = None
    _pairing = None  # epic.pairing.PairingServer | None

    # --- lifecycle -----------------------------------------------------------
    async def _main(self) -> None:
        decky.logger.info("decky-epic: backend starting")
        self.settings = SettingsStore()
        try:
            self.core = EpicCore()
            self.core.set_locale(str(self.settings.get("preferred_language", "english")))
            self.core_error = None
            decky.logger.info("decky-epic: legendary core ready")
        except Exception as e:
            self.core = None
            self.core_error = f"{type(e).__name__}: {e}"
            decky.logger.exception("decky-epic: failed to init legendary core")

        loop = asyncio.get_running_loop()
        self._loop = loop
        self.rawg = RawgService(self.settings)
        self.steam_reviews = SteamReviewsService(self.settings)
        if self.core:
            self.downloads = DownloadService(self.core, loop, decky.emit)
            self.saves = SavesService(self.core, decky.emit)
            self.launcher = LaunchService(self.core, self.saves, decky.emit, self.settings.get)

    async def _unload(self) -> None:
        decky.logger.info("decky-epic: backend unloading")
        if self._pairing:
            self._pairing.stop()
        if self.downloads:
            self.downloads.shutdown()
        if self.rawg:
            self.rawg.shutdown()
        if self.steam_reviews:
            self.steam_reviews.shutdown()
        if self.core:
            self.core.close()

    async def _uninstall(self) -> None:
        decky.logger.info("decky-epic: uninstalled")

    # --- health --------------------------------------------------------------
    async def ping(self) -> str:
        return "pong"

    async def backend_status(self) -> dict:
        return {"ready": self.core is not None, "error": self.core_error}

    # --- auth ----------------------------------------------------------------
    async def auth_login_url(self) -> str:
        return EpicCore.login_url()

    async def auth_status(self) -> dict:
        if not self.core:
            return {"logged_in": False, "user": None, "error": self.core_error}
        return await self.core.auth_status()

    async def auth_finish(self, code: str) -> dict:
        if not self.core:
            return {"ok": False, "error": self.core_error or "backend not ready"}
        return await self.core.finish_auth(code)

    async def auth_logout(self) -> dict:
        if not self.core:
            return {"ok": False, "error": self.core_error or "backend not ready"}
        return await self.core.logout()

    # --- phone-assisted login (LAN pairing) ----------------------------------
    def _pair_submit(self, payload: str) -> dict:
        """Called from the pairing server's worker thread; marshals the code
        exchange onto the plugin event loop where legendary lives."""
        if not self.core or self._loop is None:
            return {"ok": False, "error": self.core_error or "backend not ready"}
        fut = asyncio.run_coroutine_threadsafe(self.core.finish_auth(payload), self._loop)
        return fut.result(timeout=90)

    async def auth_start_pairing(self) -> dict:
        """Start (or refresh) the LAN companion server and return the QR target."""
        if not self.core:
            return {"ok": False, "error": self.core_error or "backend not ready"}
        try:
            from epic.pairing import PairingServer
            if self._pairing is None:
                self._pairing = PairingServer(self._pair_submit, EpicCore.login_url())
            info = self._pairing.start()
            return {"ok": True, **info}
        except Exception as e:
            decky.logger.exception("decky-epic: failed to start pairing server")
            return {"ok": False, "error": f"{e}"}

    async def auth_stop_pairing(self) -> dict:
        if self._pairing:
            self._pairing.stop()
        return {"ok": True}

    # --- library -------------------------------------------------------------
    async def list_library(self, force_refresh: bool = False) -> list[dict]:
        if not self.core:
            return []
        return await self.core.library(force_refresh=force_refresh)

    async def list_installed(self) -> list[dict]:
        if not self.core:
            return []
        return await self.core.installed()

    async def steam_launch_info(self, app_name: str) -> dict:
        if not self.core:
            return {"ok": False, "error": self.core_error or "backend not ready"}
        return await self.core.steam_launch_info(app_name)

    async def artwork_b64(self, app_name: str) -> dict:
        if not self.core:
            return {"ok": False, "error": self.core_error or "backend not ready"}
        return await self.core.artwork_b64(app_name)

    # --- Steam shortcut id persistence (dedupe Game-Mode shortcuts) ----------
    async def get_shortcut_id(self, app_name: str) -> dict:
        appid = self.settings.get_shortcut_id(app_name) if self.settings else None
        return {"appid": appid}

    async def set_shortcut_id(self, app_name: str, appid: int) -> dict:
        if self.settings:
            self.settings.set_shortcut_id(app_name, appid)
        return {"ok": True}

    async def remove_shortcut_id(self, app_name: str) -> dict:
        if self.settings:
            self.settings.remove_shortcut_id(app_name)
        return {"ok": True}

    # --- metacritic / RAWG ---------------------------------------------------
    async def get_cached_scores(self, app_names: list[str]) -> dict:
        if not self.rawg:
            return {}
        return self.rawg.cached(app_names)

    async def refresh_scores(self, items: list[dict], force: bool = False) -> dict:
        if not self.rawg:
            return {"ok": False, "error": "rawg not ready"}
        return await self.rawg.refresh(items, decky.emit, force=force)

    # --- Steam reviews -------------------------------------------------------
    async def get_cached_steam_reviews(self, app_names: list[str]) -> dict:
        if not self.steam_reviews:
            return {}
        return self.steam_reviews.cached(app_names)

    async def refresh_steam_reviews(self, items: list[dict], force: bool = False) -> dict:
        if not self.steam_reviews:
            return {"ok": False, "error": "steam reviews not ready"}
        return await self.steam_reviews.refresh(items, decky.emit, force=force)

    async def check_update(self, app_name: str) -> dict:
        if not self.core:
            return {"installed": False, "update_available": False}
        return await self.core.update_status(app_name)

    async def game_description(self, app_name: str) -> dict:
        """Localized title + synopsis for the detail page. Prefers Epic's catalog,
        but Epic stores just the title as the "description" for most games, so
        when there's no real synopsis there fall back to Steam's short
        description (also localized)."""
        if not self.core:
            return {"ok": False, "description": "", "name": app_name, "source": "epic"}
        info = await self.core.description(app_name)
        title = info.get("title") or app_name
        desc = info.get("description") or ""

        def _real(d: str) -> bool:
            # Epic uses the title as a placeholder description for many games.
            return bool(d.strip()) and d.strip().lower() != title.strip().lower()

        source = "epic"
        if not _real(desc) and self.steam_reviews:
            lang = str(self.settings.get("preferred_language", "english") or "english") if self.settings else "english"
            try:
                res = await self.steam_reviews.description(app_name, title, lang)
                if res and res.get("description"):
                    desc, source = res["description"], "steam"
            except Exception:
                decky.logger.exception("steam description fallback failed")

        if not _real(desc):
            desc = ""  # don't pass the bare title off as a synopsis
        return {"ok": bool(desc), "description": desc, "name": title, "source": source}

    # --- downloads -----------------------------------------------------------
    async def start_download(self, app_name: str, base_path: str = "", max_workers: int = 0) -> dict:
        if not self.downloads:
            return {"ok": False, "error": self.core_error or "backend not ready"}
        base = base_path or str(self.settings.get("install_base_path", "") or "")
        mw = max_workers or int(self.settings.get("max_workers", 0) or 0)
        return await self.downloads.start(app_name, base_path=base, max_workers=mw)

    async def cancel_download(self, app_name: str) -> dict:
        if not self.downloads:
            return {"ok": False, "error": "backend not ready"}
        return await self.downloads.cancel(app_name)

    async def download_status(self) -> dict | None:
        if not self.downloads:
            return None
        return self.downloads.status()

    async def uninstall_game(self, app_name: str) -> dict:
        if not self.downloads:
            return {"ok": False, "error": "backend not ready"}
        return await self.downloads.uninstall(app_name)

    # --- launch + cloud saves ------------------------------------------------
    async def launch_game(self, app_name: str) -> dict:
        if not self.launcher:
            return {"ok": False, "error": self.core_error or "backend not ready"}
        return await self.launcher.launch(app_name)

    async def stop_game(self) -> dict:
        if not self.launcher:
            return {"ok": False, "error": "backend not ready"}
        return await self.launcher.stop()

    async def is_running(self) -> dict:
        if not self.launcher:
            return {"running": False, "app_name": None}
        return {"running": self.launcher.is_running(), "app_name": self.launcher.running_app()}

    async def sync_saves(self, app_name: str, direction: str = "both",
                         force_up: bool = False, force_down: bool = False) -> dict:
        if not self.saves:
            return {"ok": False, "error": "backend not ready"}
        return await self.saves.sync(app_name, direction=direction,
                                     force_up=force_up, force_down=force_down)

    async def saves_status(self, app_name: str) -> dict:
        if not self.saves:
            return {"ok": False, "error": "backend not ready"}
        return await self.saves.status(app_name)

    # --- settings ------------------------------------------------------------
    async def get_settings(self) -> dict:
        return self.settings.all() if self.settings else {}

    async def set_settings(self, patch: dict) -> dict:
        if not self.settings:
            return {}
        updated = self.settings.update(patch)
        # Re-point Epic catalog queries when the language changes; the next
        # library() call notices the locale mismatch and re-pulls localized data.
        if "preferred_language" in patch and self.core:
            self.core.set_locale(str(updated.get("preferred_language", "english")))
        return updated

    async def list_proton_builds(self) -> list[dict]:
        return proton.discover_proton_builds()
