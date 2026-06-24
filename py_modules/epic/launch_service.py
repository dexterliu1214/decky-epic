"""Launch orchestration — the reason games run *inside* the plugin.

Because we own the process lifecycle we can bracket the run with cloud-save sync:

    syncing_down -> (download cloud save) -> launching -> running
        -> [game process] -> syncing_up -> (upload local save) -> exited

The game is run through a reused Steam Proton build pointed at our per-game
compatdata prefix.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shlex
import sys
from typing import Awaitable, Callable, Optional

from . import prefix, proton

IS_WINDOWS = sys.platform == "win32"

_log = logging.getLogger("decky-epic.launch")

EmitFn = Callable[[str, dict], Awaitable[None]]
EVT_LAUNCH = "epic_launch_state"


class LaunchService:
    def __init__(self, epic_core, saves, emit: EmitFn, get_setting: Callable[[str, object], object]) -> None:
        self.epic = epic_core
        self.saves = saves
        self.emit = emit
        self.get_setting = get_setting
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._app: Optional[str] = None

    def is_running(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    def running_app(self) -> Optional[str]:
        return self._app if self.is_running() else None

    async def launch(self, app_name: str) -> dict:
        if self.is_running():
            return {"ok": False, "error": f"Already running: {self._app}"}

        if IS_WINDOWS:
            # Native Windows launch — no Proton, no prefix. Cloud-save tokens
            # resolve directly against %LOCALAPPDATA% etc.
            built_fn = (self._build_params_native, app_name)
        else:
            steam_root = prefix.default_steam_root()
            if not steam_root:
                return {"ok": False, "error": "Could not locate the Steam installation."}
            pb = proton.resolve_proton(str(self.get_setting("preferred_proton", "") or ""))
            if not pb:
                return {"ok": False, "error": "No Proton build found. Install Proton (e.g. GE-Proton) via Steam first."}
            # Record the prefix in legendary config so save-path resolution works.
            prefix.ensure_prefix(app_name)
            await self.epic.run(prefix.write_legendary_prefix_config, self.epic.core, app_name, steam_root)
            built_fn = (self._build_params, app_name, pb["path"], steam_root)

        # 1) Pull cloud save before launch.
        await self.emit(EVT_LAUNCH, {"app_name": app_name, "state": "syncing_down"})
        try:
            await self.saves.sync(app_name, direction="pull")
        except Exception as e:
            _log.warning("pre-launch save pull failed: %r", e)

        # 2) Resolve the launch command.
        built = await self.epic.run(*built_fn)
        if not built.get("ok"):
            await self.emit(EVT_LAUNCH, {"app_name": app_name, "state": "error", "error": built.get("error")})
            return built

        # 3) Spawn the game under Proton.
        await self.emit(EVT_LAUNCH, {"app_name": app_name, "state": "launching"})
        try:
            proc = await asyncio.create_subprocess_exec(
                *built["argv"], cwd=built["cwd"] or None, env=built["env"]
            )
        except Exception as e:
            _log.exception("spawn failed")
            await self.emit(EVT_LAUNCH, {"app_name": app_name, "state": "error", "error": f"{e}"})
            return {"ok": False, "error": f"{e}"}

        self._proc = proc
        self._app = app_name
        await self.emit(EVT_LAUNCH, {"app_name": app_name, "state": "running", "pid": proc.pid})

        # 4) Wait for exit + upload, without blocking the RPC return.
        asyncio.create_task(self._wait_and_upload(app_name, proc))
        return {"ok": True, "pid": proc.pid}

    async def stop(self) -> dict:
        if not self.is_running() or self._proc is None:
            return {"ok": False, "error": "No game is running."}
        try:
            self._proc.terminate()
        except Exception as e:
            return {"ok": False, "error": f"{e}"}
        return {"ok": True}

    async def _wait_and_upload(self, app_name: str, proc) -> None:
        code = await proc.wait()
        was = self._app
        self._proc = None
        self._app = None
        # Upload local save after play.
        await self.emit(EVT_LAUNCH, {"app_name": app_name, "state": "syncing_up"})
        try:
            await self.saves.sync(app_name, direction="push")
        except Exception as e:
            _log.warning("post-exit save push failed: %r", e)
        await self.emit(EVT_LAUNCH, {"app_name": app_name, "state": "exited", "code": code})

    # -- blocking ------------------------------------------------------------
    def _build_params(self, app_name: str, proton_script: str, steam_root: str) -> dict:
        core = self.epic.core
        try:
            core.login()
        except Exception as e:
            _log.warning("login before launch failed: %r", e)
        wrapper = f"{shlex.quote(proton_script)} run"
        try:
            params = core.get_launch_parameters(app_name, wrapper=wrapper, disable_wine=True)
        except Exception as e:
            return {"ok": False, "error": f"{e}"}

        argv = list(params.launch_command)
        argv.append(os.path.join(params.game_directory, params.game_executable))
        argv.extend(params.game_parameters)
        argv.extend(params.user_parameters)
        argv.extend(params.egl_parameters)

        env = os.environ.copy()
        env.update(params.environment)
        env.update(prefix.proton_launch_env(app_name, steam_root))
        return {"ok": True, "argv": argv, "cwd": params.working_directory, "env": env}

    def _build_params_native(self, app_name: str) -> dict:
        """Native launch (Windows): legendary builds a plain exe command."""
        core = self.epic.core
        try:
            core.login()
        except Exception as e:
            _log.warning("login before launch failed: %r", e)
        try:
            params = core.get_launch_parameters(app_name)
        except Exception as e:
            return {"ok": False, "error": f"{e}"}

        argv = list(params.launch_command)
        argv.append(os.path.join(params.game_directory, params.game_executable))
        argv.extend(params.game_parameters)
        argv.extend(params.user_parameters)
        argv.extend(params.egl_parameters)

        env = os.environ.copy()
        env.update(params.environment)
        return {"ok": True, "argv": argv, "cwd": params.working_directory, "env": env}
