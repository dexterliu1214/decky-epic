"""Epic cloud-save sync — the headline feature.

Ports legendary's CLI ``sync-saves`` decision logic into in-process calls on
``LegendaryCore`` so we keep full control of timing and conflict handling:

  * ``pull``  — download cloud save if it is newer (run BEFORE launching a game)
  * ``push``  — upload local save if it is newer (run AFTER the game exits)
  * ``both``  — interactive/manual two-way sync (the Game detail "Sync" button)

Save-path resolution depends on the per-game Proton prefix being recorded in
legendary config first (see ``prefix.write_legendary_prefix_config``).
"""
from __future__ import annotations

import logging
import os
from typing import Awaitable, Callable, Optional

_log = logging.getLogger("decky-epic.saves")

EmitFn = Callable[[str, dict], Awaitable[None]]
EVT_SAVES = "epic_saves_status"


class SavesService:
    def __init__(self, epic_core, emit: EmitFn) -> None:
        self.epic = epic_core
        self.emit = emit

    async def status(self, app_name: str) -> dict:
        return await self.epic.run(self._status_blocking, app_name)

    async def sync(self, app_name: str, direction: str = "both",
                   force_up: bool = False, force_down: bool = False) -> dict:
        pull = direction in ("both", "pull")
        push = direction in ("both", "push")
        await self.emit(EVT_SAVES, {"app_name": app_name, "state": "syncing", "direction": direction})
        result = await self.epic.run(
            self._sync_blocking, app_name, pull, push, force_up, force_down
        )
        await self.emit(EVT_SAVES, {"app_name": app_name, "state": "done", **result})
        return result

    # -- blocking helpers (run on the core executor) -------------------------
    def _ensure_save_path(self, core, app_name: str):
        igame = core.get_installed_game(app_name)
        if not igame:
            return None, {"ok": False, "error": "Game is not installed."}
        if not igame.save_path:
            try:
                sp = core.get_save_path(app_name, platform=igame.platform)
            except ValueError as e:
                return igame, {"ok": False, "error": str(e), "supported": False}
            if "%" in sp or "{" in sp:
                return igame, {
                    "ok": False,
                    "needs_path": True,
                    "computed_path": sp,
                    "error": "Save path contains unresolved variables. "
                             "Launch the game once so Proton creates its prefix, then retry.",
                }
            os.makedirs(sp, exist_ok=True)
            igame.save_path = sp
            core.lgd.set_installed_game(app_name, igame)
        return igame, None

    def _status_blocking(self, app_name: str) -> dict:
        from legendary.models.game import SaveGameStatus

        core = self.epic.core
        try:
            core.login()
        except Exception as e:
            _log.warning("login during saves status failed: %r", e)
        game = core.get_game(app_name)
        if not game or not (game.supports_cloud_saves or game.supports_mac_cloud_saves):
            return {"ok": True, "supported": False}

        igame, err = self._ensure_save_path(core, app_name)
        if err:
            return {"supported": True, **err}

        saves = core.get_save_games(app_name)
        latest = {s.app_name: s for s in sorted(saves, key=lambda a: a.datetime)}
        remote = latest.get(app_name)
        res, (dt_l, dt_r) = core.check_savegame_state(igame.save_path, remote)
        return {
            "ok": True,
            "supported": True,
            "status": res.name.lower(),
            "has_remote": remote is not None,
            "local_dt": dt_l.isoformat() if dt_l else None,
            "remote_dt": dt_r.isoformat() if dt_r else None,
            "save_path": igame.save_path,
        }

    def _sync_blocking(self, app_name: str, pull: bool, push: bool,
                       force_up: bool, force_down: bool) -> dict:
        from legendary.models.game import SaveGameStatus

        core = self.epic.core
        try:
            core.login()
        except Exception as e:
            return {"ok": False, "error": f"Login failed: {e}"}

        game = core.get_game(app_name)
        if not game or not (game.supports_cloud_saves or game.supports_mac_cloud_saves):
            return {"ok": True, "supported": False, "action": "none"}

        igame, err = self._ensure_save_path(core, app_name)
        if err:
            return {"supported": True, **err}

        saves = core.get_save_games(app_name)
        latest = {s.app_name: s for s in sorted(saves, key=lambda a: a.datetime)}
        remote = latest.get(app_name)
        res, (dt_l, dt_r) = core.check_savegame_state(igame.save_path, remote)

        base = {
            "ok": True,
            "supported": True,
            "status": res.name.lower(),
            "local_dt": dt_l.isoformat() if dt_l else None,
            "remote_dt": dt_r.isoformat() if dt_r else None,
        }

        if res == SaveGameStatus.NO_SAVE:
            return {**base, "action": "none"}
        if res == SaveGameStatus.SAME_AGE and not (force_up or force_down):
            return {**base, "action": "none"}

        try:
            if (res == SaveGameStatus.REMOTE_NEWER and not force_up) or force_down:
                if not pull:
                    return {**base, "action": "skipped_download", "conflict": True}
                _log.info("Downloading cloud save for %s", app_name)
                core.download_saves(app_name, save_dir=igame.save_path, clean_dir=True,
                                    manifest_name=remote.manifest_name)
                return {**base, "action": "downloaded"}
            elif res == SaveGameStatus.LOCAL_NEWER or force_up:
                if not push:
                    return {**base, "action": "skipped_upload", "conflict": True}
                _log.info("Uploading local save for %s", app_name)
                core.upload_save(app_name, igame.save_path, dt_l, False)
                return {**base, "action": "uploaded"}
        except Exception as e:
            _log.exception("save sync transfer failed")
            return {**base, "ok": False, "error": f"{e}", "action": "error"}

        return {**base, "action": "none"}
