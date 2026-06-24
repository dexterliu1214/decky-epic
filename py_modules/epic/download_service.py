"""Download orchestration.

legendary's ``DLManager`` is a ``multiprocessing.Process`` that streams
``UIUpdate`` status objects into a queue. We:

  1. call ``core.prepare_download`` briefly under the shared core lock to obtain
     the manager + analysis + InstalledGame, then
  2. run the actual transfer on a *dedicated* thread so the long-lived download
     never holds the core lock (auth / library calls stay responsive), and
  3. finalize with ``core.install_game`` (writes installed.json) back under the
     core lock.

Progress is pushed to the frontend via the injected ``emit`` coroutine.
"""
from __future__ import annotations

import asyncio
import logging
import multiprocessing as mp
import queue as queue_mod
import threading
import time
from typing import Awaitable, Callable, Optional

from . import paths

_log = logging.getLogger("decky-epic.download")

EmitFn = Callable[[str, dict], Awaitable[None]]

EVT_PROGRESS = "epic_download_progress"
EVT_STATE = "epic_download_state"


class DownloadService:
    def __init__(self, epic_core, loop: asyncio.AbstractEventLoop, emit: EmitFn) -> None:
        self.epic = epic_core
        self.loop = loop
        self.emit = emit
        self._thread: Optional[threading.Thread] = None
        self._dlm = None
        self._cancel = threading.Event()
        self._current: Optional[dict] = None  # public status snapshot

    # -- public API ----------------------------------------------------------
    def status(self) -> Optional[dict]:
        return self._current

    def is_busy(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    async def start(self, app_name: str, base_path: str = "", max_workers: int = 0) -> dict:
        if self.is_busy():
            return {"ok": False, "error": "A download is already in progress."}

        status_q: mp.Queue = mp.Queue()
        base = base_path or str(paths.DEFAULT_INSTALL_DIR)

        def _prepare():
            core = self.epic.core
            try:
                core.login()
            except Exception as e:
                _log.warning("login before download failed: %r", e)
            game = core.get_game(app_name, update_meta=True)
            if not game:
                raise ValueError(f"Game not found: {app_name}")
            dlm, analysis, igame = core.prepare_download(
                game=game, base_path=base, status_q=status_q,
                max_workers=max_workers, platform="Windows",
            )
            return game, dlm, analysis, igame

        try:
            game, dlm, analysis, igame = await self.epic.run(_prepare)
        except Exception as e:
            _log.exception("prepare_download failed")
            return {"ok": False, "error": f"{e}"}

        self._dlm = dlm
        self._cancel.clear()
        self._current = {
            "app_name": app_name,
            "title": getattr(game, "app_title", app_name),
            "state": "downloading",
            "progress": 0.0,
            "download_speed": 0.0,
            "dl_total_bytes": int(getattr(analysis, "dl_size", 0) or 0),
            "downloaded_bytes": 0,
            "eta_seconds": None,
        }
        self._thread = threading.Thread(
            target=self._run, args=(app_name, dlm, analysis, igame, status_q),
            name=f"epic-dl-{app_name}", daemon=True,
        )
        self._thread.start()
        await self.emit(EVT_STATE, {"app_name": app_name, "state": "downloading"})
        return {"ok": True}

    async def cancel(self, app_name: str) -> dict:
        if not self.is_busy() or not self._current or self._current["app_name"] != app_name:
            return {"ok": False, "error": "No matching active download."}
        self._cancel.set()
        return {"ok": True}

    async def uninstall(self, app_name: str) -> dict:
        def _do():
            core = self.epic.core
            igame = core.get_installed_game(app_name)
            if not igame:
                return {"ok": False, "error": "Not installed."}
            core.uninstall_game(igame, delete_files=True)
            return {"ok": True}

        return await self.epic.run(_do)

    def shutdown(self) -> None:
        self._cancel.set()
        if self._dlm is not None:
            try:
                if self._dlm.is_alive():
                    self._dlm.terminate()
            except Exception:
                pass

    # -- worker thread -------------------------------------------------------
    def _emit_threadsafe(self, event: str, payload: dict) -> None:
        try:
            asyncio.run_coroutine_threadsafe(self.emit(event, payload), self.loop)
        except Exception as e:
            _log.warning("emit %s failed: %r", event, e)

    def _run(self, app_name, dlm, analysis, igame, status_q: mp.Queue) -> None:
        dl_total = int(getattr(analysis, "dl_size", 0) or 0)
        try:
            dlm.start()
        except Exception as e:
            _log.exception("dlm.start failed")
            self._finish(app_name, "error", error=f"{e}")
            return

        while dlm.is_alive():
            if self._cancel.is_set():
                break
            try:
                upd = status_q.get(timeout=1.0)
            except queue_mod.Empty:
                continue
            except Exception:
                continue
            perc = float(getattr(upd, "progress", 0.0) or 0.0)
            speed = float(getattr(upd, "download_speed", 0.0) or 0.0)
            downloaded = int(dl_total * perc / 100.0) if dl_total else 0
            eta = None
            if speed > 0 and dl_total:
                eta = max(0, int((dl_total - downloaded) / speed))
            snap = {
                "app_name": app_name,
                "state": "downloading",
                "progress": round(perc, 2),
                "download_speed": speed,
                "dl_total_bytes": dl_total,
                "downloaded_bytes": downloaded,
                "eta_seconds": eta,
                "current_filename": getattr(upd, "current_filename", None),
            }
            self._current = snap
            self._emit_threadsafe(EVT_PROGRESS, snap)

        if self._cancel.is_set():
            try:
                dlm.terminate()
            except Exception:
                pass
            try:
                dlm.join(timeout=10)
            except Exception:
                pass
            self._finish(app_name, "cancelled")
            return

        try:
            dlm.join()
        except Exception as e:
            _log.warning("dlm.join error: %r", e)

        # Finalize install (write installed.json) under the core lock.
        try:
            fut = asyncio.run_coroutine_threadsafe(
                self.epic.run(self.epic.core.install_game, igame), self.loop
            )
            fut.result(timeout=120)
        except Exception as e:
            _log.exception("install_game finalize failed")
            self._finish(app_name, "error", error=f"{e}")
            return

        self._finish(app_name, "done")

    def _finish(self, app_name: str, state: str, error: Optional[str] = None) -> None:
        payload = {"app_name": app_name, "state": state}
        if error:
            payload["error"] = error
        if self._current and self._current.get("app_name") == app_name:
            self._current = {**self._current, **payload}
        self._dlm = None
        self._emit_threadsafe(EVT_STATE, payload)
