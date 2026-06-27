"""Windows dev harness — run the real backend Plugin against real legendary.

Decky only runs on Linux, but the backend is plain Python + legendary, which
works natively on Windows. This harness injects a stub ``decky`` module, points
the plugin's storage at a local ``.devstate`` dir, and exercises the actual RPC
methods so we can validate as much as possible without a Steam Deck.

Run it with the repo dev venv (which has the real legendary installed):

    .venv\\Scripts\\python.exe scripts\\devtools\\dev_harness.py validate
    .venv\\Scripts\\python.exe scripts\\devtools\\dev_harness.py login <authorizationCode>
    .venv\\Scripts\\python.exe scripts\\devtools\\dev_harness.py library
    .venv\\Scripts\\python.exe scripts\\devtools\\dev_harness.py saves <AppName>

On Windows, legendary resolves cloud-save paths via %LOCALAPPDATA% etc. directly
(no Proton), so auth + library + cloud-save *logic* are all testable here.
Launch is Linux/Proton-only and is expected to report "no Proton" on Windows.
"""
from __future__ import annotations

import asyncio
import logging
import multiprocessing
import os
import sys
import types

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEVSTATE = os.path.join(REPO, ".devstate")

# --- point the plugin's storage at a local dir ------------------------------
os.environ.setdefault("DECKY_USER_HOME", os.path.expanduser("~"))
os.environ["DECKY_PLUGIN_DIR"] = REPO
os.environ["DECKY_PLUGIN_SETTINGS_DIR"] = os.path.join(DEVSTATE, "settings")
os.environ["DECKY_PLUGIN_RUNTIME_DIR"] = os.path.join(DEVSTATE, "runtime")
os.environ["DECKY_PLUGIN_LOG_DIR"] = os.path.join(DEVSTATE, "logs")

# --- inject a stub `decky` module BEFORE importing main ---------------------
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

_events: list[tuple] = []


async def _emit(event: str, *args):
    _events.append((event, args))
    payload = args[0] if len(args) == 1 else args
    print(f"  [event] {event}: {payload}")


_decky = types.ModuleType("decky")
_decky.logger = logging.getLogger("decky")
_decky.emit = _emit
for k in ("DECKY_PLUGIN_DIR", "DECKY_PLUGIN_SETTINGS_DIR", "DECKY_PLUGIN_RUNTIME_DIR",
          "DECKY_PLUGIN_LOG_DIR", "DECKY_USER_HOME"):
    setattr(_decky, k, os.environ.get(k, ""))
sys.modules["decky"] = _decky

# --- path: epic from py_modules, but legendary from the venv ----------------
# repo root (for `import main`) + py_modules (for `import epic`) go at the END so
# the venv's site-packages legendary wins over the Linux-bundled py_modules copy.
sys.path.append(REPO)
sys.path.append(os.path.join(REPO, "py_modules"))

import main  # noqa: E402


def banner(t: str):
    print("\n" + "=" * 4 + " " + t + " " + "=" * 4)


async def cmd_validate(plugin):
    banner("backend_status")
    print(await plugin.backend_status())

    banner("legendary version")
    import legendary
    print(legendary.__version__, "from", legendary.__file__)

    banner("get_settings")
    print(await plugin.get_settings())

    banner("auth_login_url")
    print(await plugin.auth_login_url())

    banner("auth_status (expected logged_in=False until you `login`)")
    print(await plugin.auth_status())

    banner("download_status / is_running")
    print(await plugin.download_status())
    print(await plugin.is_running())

    banner("list_proton_builds (none on Windows is OK)")
    print(await plugin.list_proton_builds())

    banner("get_cached_scores([]) and refresh_scores with no key (graceful)")
    print(await plugin.get_cached_scores(["nope"]))
    print(await plugin.refresh_scores([{"app_name": "x", "title": "Hades"}], False))

    banner("auth_finish with a bogus code (must fail gracefully, not crash)")
    print(await plugin.auth_finish("not-a-real-code"))

    print("\nVALIDATE COMPLETE (no crashes = backend RPC surface is sound)")


async def cmd_login(plugin, code):
    print(await plugin.auth_finish(code))
    print(await plugin.auth_status())


async def cmd_library(plugin):
    games = await plugin.list_library(False)
    print(f"{len(games)} games")
    for g in games[:15]:
        flags = []
        if g["installed"]:
            flags.append("installed")
        if g["cloud_saves"]:
            flags.append("cloud")
        print(f"  - {g['title']}  [{g['app_name']}]  {','.join(flags)}  cover={'yes' if g['cover'] else 'no'}")


async def cmd_installed(plugin):
    for g in await plugin.list_installed():
        print(f"  - {g['title']} v{g['version']} @ {g['install_path']}")


async def cmd_download(plugin, app):
    res = await plugin.start_download(app, "", 0)
    print("start:", res)
    if not res.get("ok"):
        return
    # Wait for the download to reach a terminal state, printing progress.
    while True:
        await asyncio.sleep(2)
        st = await plugin.download_status()
        if not st:
            continue
        if st["state"] == "downloading":
            print(f"  {st['progress']:.1f}%  {st['downloaded_bytes']}/{st['dl_total_bytes']} bytes")
        else:
            print("final:", st["state"], st.get("error", ""))
            break


async def cmd_cancel(plugin, app):
    print(await plugin.cancel_download(app))


async def cmd_saves(plugin, app):
    print(await plugin.saves_status(app))


async def cmd_sync(plugin, app, direction):
    print(await plugin.sync_saves(app, direction, False, False))


async def main_async(argv):
    cmd = argv[0] if argv else "validate"
    rest = argv[1:]

    plugin = main.Plugin()
    await plugin._main()
    try:
        if cmd == "validate":
            await cmd_validate(plugin)
        elif cmd == "login":
            await cmd_login(plugin, rest[0])
        elif cmd == "status":
            print(await plugin.auth_status())
        elif cmd == "library":
            await cmd_library(plugin)
        elif cmd == "installed":
            await cmd_installed(plugin)
        elif cmd == "download":
            await cmd_download(plugin, rest[0])
        elif cmd == "cancel":
            await cmd_cancel(plugin, rest[0])
        elif cmd == "saves":
            await cmd_saves(plugin, rest[0])
        elif cmd == "sync":
            await cmd_sync(plugin, rest[0], rest[1] if len(rest) > 1 else "both")
        elif cmd == "proton":
            print(await plugin.list_proton_builds())
        elif cmd == "logout":
            print(await plugin.auth_logout())
        else:
            print(f"unknown command: {cmd}")
    finally:
        await plugin._unload()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    asyncio.run(main_async(sys.argv[1:]))
