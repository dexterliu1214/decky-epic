"""Windows GUI server — a local desktop app over the SAME plugin backend.

Decky's React UI is bound to the Steam runtime, so for Windows we serve our own
Steam-like web UI on top of the identical `main.Plugin` backend (real legendary).
A stub `decky` module forwards backend events to connected browsers over SSE.

Run via scripts/run_gui.ps1 (installs fastapi/uvicorn into the dev venv).
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import types

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEVSTATE = os.path.join(REPO, ".devstate")

# Same local storage as the CLI harness so a login persists between them.
# All overridable via env so the launcher can point at the *real* Decky plugin
# config (~/homebrew/settings/decky-epic) and reuse its login + installed games.
os.environ.setdefault("DECKY_USER_HOME", os.path.expanduser("~"))
os.environ.setdefault("DECKY_PLUGIN_DIR", REPO)
os.environ.setdefault("DECKY_PLUGIN_SETTINGS_DIR", os.path.join(DEVSTATE, "settings"))
os.environ.setdefault("DECKY_PLUGIN_RUNTIME_DIR", os.path.join(DEVSTATE, "runtime"))
os.environ.setdefault("DECKY_PLUGIN_LOG_DIR", os.path.join(DEVSTATE, "logs"))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
_log = logging.getLogger("decky-epic.gui")

# --- event broker: backend `decky.emit` -> SSE subscribers ------------------
_subscribers: set[asyncio.Queue] = set()


async def _emit(event: str, *args):
    payload = args[0] if len(args) == 1 else list(args)
    msg = {"event": event, "payload": payload}
    for q in list(_subscribers):
        try:
            q.put_nowait(msg)
        except Exception:
            pass


# --- inject stub `decky` BEFORE importing main ------------------------------
_decky = types.ModuleType("decky")
_decky.logger = logging.getLogger("decky")
_decky.emit = _emit
for k in ("DECKY_PLUGIN_DIR", "DECKY_PLUGIN_SETTINGS_DIR", "DECKY_PLUGIN_RUNTIME_DIR",
          "DECKY_PLUGIN_LOG_DIR", "DECKY_USER_HOME"):
    setattr(_decky, k, os.environ.get(k, ""))
sys.modules["decky"] = _decky

# epic from py_modules; legendary from the venv (append => venv wins).
sys.path.append(REPO)
sys.path.append(os.path.join(REPO, "py_modules"))

import main  # noqa: E402

from contextlib import asynccontextmanager  # noqa: E402

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

plugin = main.Plugin()
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


@asynccontextmanager
async def lifespan(_app: "FastAPI"):
    await plugin._main()
    _log.info("backend ready")
    yield
    await plugin._unload()


app = FastAPI(title="decky-epic (Windows GUI)", lifespan=lifespan)


# --- SSE --------------------------------------------------------------------
@app.get("/events")
async def events():
    q: asyncio.Queue = asyncio.Queue(maxsize=1000)
    _subscribers.add(q)

    async def gen():
        import json
        try:
            yield "retry: 2000\n\n"
            while True:
                msg = await q.get()
                yield f"data: {json.dumps(msg)}\n\n"
        finally:
            _subscribers.discard(q)

    return StreamingResponse(gen(), media_type="text/event-stream")


# --- REST -------------------------------------------------------------------
@app.get("/api/state")
async def state():
    return {
        "backend": await plugin.backend_status(),
        "auth": await plugin.auth_status(),
        "settings": await plugin.get_settings(),
        "running": await plugin.is_running(),
        "download": await plugin.download_status(),
        "login_url": await plugin.auth_login_url(),
        "platform": sys.platform,
    }


@app.post("/api/auth/finish")
async def auth_finish(req: Request):
    body = await req.json()
    return await plugin.auth_finish(body.get("code", ""))


@app.post("/api/auth/logout")
async def auth_logout():
    return await plugin.auth_logout()


@app.get("/api/library")
async def library(refresh: int = 0):
    games = await plugin.list_library(bool(refresh))
    return {"games": games}


@app.post("/api/download/start")
async def download_start(req: Request):
    body = await req.json()
    return await plugin.start_download(body["app_name"], body.get("base_path", ""), int(body.get("max_workers", 0)))


@app.post("/api/download/cancel")
async def download_cancel(req: Request):
    body = await req.json()
    return await plugin.cancel_download(body["app_name"])


@app.get("/api/download/status")
async def download_status():
    return JSONResponse(await plugin.download_status())


@app.post("/api/uninstall")
async def uninstall(req: Request):
    body = await req.json()
    return await plugin.uninstall_game(body["app_name"])


@app.post("/api/launch")
async def launch(req: Request):
    body = await req.json()
    return await plugin.launch_game(body["app_name"])


@app.post("/api/stop")
async def stop():
    return await plugin.stop_game()


@app.get("/api/saves/status")
async def saves_status(app: str):
    return await plugin.saves_status(app)


@app.post("/api/saves/sync")
async def saves_sync(req: Request):
    body = await req.json()
    return await plugin.sync_saves(
        body["app_name"], body.get("direction", "both"),
        bool(body.get("force_up", False)), bool(body.get("force_down", False)),
    )


@app.get("/api/settings")
async def get_settings():
    return await plugin.get_settings()


@app.post("/api/settings")
async def set_settings(req: Request):
    body = await req.json()
    return await plugin.set_settings(body)


@app.get("/api/proton")
async def proton_builds():
    return await plugin.list_proton_builds()


# --- static SPA -------------------------------------------------------------
@app.get("/")
async def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def run():
    import uvicorn

    host = os.environ.get("GUI_HOST", "127.0.0.1")
    port = int(os.environ.get("GUI_PORT", "8777"))
    _log.info("decky-epic GUI on http://%s:%d", host, port)
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    import multiprocessing

    multiprocessing.freeze_support()
    run()
