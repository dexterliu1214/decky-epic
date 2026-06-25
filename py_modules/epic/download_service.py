"""Download orchestration.

The actual transfer runs in an isolated subprocess (``download_cli.py``) rather
than as a ``multiprocessing.Process`` forked from the plugin host: legendary's
``DLManager`` fork disturbed Decky's plugin IPC and the plugin was unloaded the
instant the download finished, so the install never reached installed.json and
the UI hung at 100%. Launching a clean child via ``create_subprocess_exec``
(close_fds) keeps every legendary fork away from Decky's file descriptors.

We read newline-delimited JSON progress from the child's stdout and re-emit the
frontend events.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from typing import Awaitable, Callable, Optional

from . import paths

_log = logging.getLogger("decky-epic.download")

EmitFn = Callable[[str, dict], Awaitable[None]]

EVT_PROGRESS = "epic_download_progress"
EVT_STATE = "epic_download_state"

_CLI = os.path.join(os.path.dirname(os.path.abspath(__file__)), "download_cli.py")


class DownloadService:
    def __init__(self, epic_core, loop: asyncio.AbstractEventLoop, emit: EmitFn) -> None:
        self.epic = epic_core
        self.loop = loop
        self.emit = emit
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._task: Optional[asyncio.Task] = None
        self._app: Optional[str] = None
        self._current: Optional[dict] = None  # public status snapshot

    # -- public API ----------------------------------------------------------
    def status(self) -> Optional[dict]:
        return self._current

    def is_busy(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    async def start(self, app_name: str, base_path: str = "", max_workers: int = 0) -> dict:
        if self.is_busy():
            return {"ok": False, "error": "A download is already in progress."}

        base = base_path or str(paths.DEFAULT_INSTALL_DIR)
        argv = [sys.executable, _CLI, app_name, "--base", base, "--workers", str(int(max_workers or 0))]
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
        except Exception as e:
            _log.exception("failed to launch download subprocess")
            return {"ok": False, "error": f"{e}"}

        self._proc = proc
        self._app = app_name
        self._current = {
            "app_name": app_name, "title": app_name, "state": "downloading",
            "progress": 0.0, "download_speed": 0.0, "dl_total_bytes": 0,
            "downloaded_bytes": 0, "eta_seconds": None,
        }
        self._task = asyncio.create_task(self._pump(app_name, proc))
        await self.emit(EVT_STATE, {"app_name": app_name, "state": "downloading"})
        return {"ok": True}

    async def cancel(self, app_name: str) -> dict:
        if not self.is_busy() or self._app != app_name or self._proc is None:
            return {"ok": False, "error": "No matching active download."}
        try:
            self._proc.terminate()
        except Exception as e:
            return {"ok": False, "error": f"{e}"}
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
        if self._proc is not None and self._proc.returncode is None:
            try:
                self._proc.terminate()
            except Exception:
                pass

    # -- subprocess pump -----------------------------------------------------
    async def _pump(self, app_name: str, proc: asyncio.subprocess.Process) -> None:
        dl_total = 0
        assert proc.stdout is not None
        try:
            async for raw in proc.stdout:
                try:
                    msg = json.loads(raw.decode("utf-8", "replace").strip())
                except Exception:
                    continue
                kind = msg.get("type")
                if kind == "start":
                    dl_total = int(msg.get("dl_total_bytes") or 0)
                    if self._current:
                        self._current["title"] = msg.get("title") or app_name
                        self._current["dl_total_bytes"] = dl_total
                elif kind == "progress":
                    perc = float(msg.get("progress") or 0.0)
                    speed = float(msg.get("download_speed") or 0.0)
                    downloaded = int(dl_total * perc / 100.0) if dl_total else 0
                    eta = max(0, int((dl_total - downloaded) / speed)) if (speed > 0 and dl_total) else None
                    snap = {
                        "app_name": app_name, "state": "downloading",
                        "progress": round(perc, 2), "download_speed": speed,
                        "dl_total_bytes": dl_total, "downloaded_bytes": downloaded,
                        "eta_seconds": eta, "current_filename": msg.get("current_filename"),
                    }
                    self._current = snap
                    await self.emit(EVT_PROGRESS, snap)
                elif kind == "done":
                    await self._finish(app_name, "done")
                    break
                elif kind == "error":
                    await self._finish(app_name, "error", error=msg.get("error"))
                    break
        except Exception as e:
            _log.exception("download pump failed")
            await self._finish(app_name, "error", error=f"{e}")

        rc = await proc.wait()
        # If the child died without a terminal message, reconcile the state.
        if self._current and self._current.get("state") == "downloading":
            if rc == 130:
                await self._finish(app_name, "cancelled")
            else:
                stderr = b""
                try:
                    stderr = await proc.stderr.read() if proc.stderr else b""
                except Exception:
                    pass
                await self._finish(app_name, "error",
                                   error=stderr.decode("utf-8", "replace")[-500:] or f"exit code {rc}")

    async def _finish(self, app_name: str, state: str, error: Optional[str] = None) -> None:
        payload = {"app_name": app_name, "state": state}
        if error:
            payload["error"] = error
        if self._current and self._current.get("app_name") == app_name:
            self._current = {**self._current, **payload}
        await self.emit(EVT_STATE, payload)
