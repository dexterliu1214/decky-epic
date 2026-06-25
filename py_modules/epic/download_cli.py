"""Run a legendary download to completion in an isolated subprocess.

legendary's ``DLManager`` is a ``multiprocessing.Process``. When it was forked
directly from the Decky plugin host, finishing the download disturbed Decky's
plugin IPC and the plugin got unloaded mid-finalize — the install never landed
in installed.json and the UI hung at 100%.

Running the whole download here, launched via ``create_subprocess_exec`` (which
exec's a clean Python with close_fds), keeps every fork isolated from Decky. We
stream progress to stdout as JSON lines; the plugin reads them and re-emits the
frontend events.

    python3 download_cli.py <app_name> [--base <dir>] [--workers <n>]

stdout protocol (one JSON object per line):
    {"type":"start","title":..,"dl_total_bytes":..}
    {"type":"progress","progress":..,"download_speed":..,"current_filename":..}
    {"type":"done"}
    {"type":"error","error":".."}
"""
from __future__ import annotations

import argparse
import json
import os
import queue as queue_mod
import signal
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))      # .../py_modules/epic
_PYMODULES = os.path.dirname(_HERE)                      # .../py_modules
if _PYMODULES not in sys.path:
    sys.path.insert(0, _PYMODULES)


def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("app_name")
    ap.add_argument("--base", default="")
    ap.add_argument("--workers", type=int, default=0)
    args = ap.parse_args()

    import multiprocessing as mp

    from epic import paths
    paths.apply_legendary_env()
    from legendary.core import LegendaryCore

    core = LegendaryCore()
    try:
        core.login()
    except Exception as e:
        _emit({"type": "error", "error": f"Login failed: {e}"})
        return 1

    game = core.get_game(args.app_name, update_meta=True)
    if not game:
        _emit({"type": "error", "error": f"Game not found: {args.app_name}"})
        return 1

    status_q: "mp.Queue" = mp.Queue()
    base = args.base or str(paths.DEFAULT_INSTALL_DIR)
    try:
        dlm, analysis, igame = core.prepare_download(
            game=game, base_path=base, status_q=status_q,
            max_workers=args.workers, platform="Windows",
        )
    except Exception as e:
        _emit({"type": "error", "error": f"{e}"})
        return 1

    _emit({"type": "start", "title": getattr(game, "app_title", args.app_name),
           "dl_total_bytes": int(getattr(analysis, "dl_size", 0) or 0)})

    def _stop(*_):
        try:
            dlm.terminate()
        except Exception:
            pass
        os._exit(130)

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    try:
        dlm.start()
    except Exception as e:
        _emit({"type": "error", "error": f"{e}"})
        return 1

    while dlm.is_alive():
        try:
            upd = status_q.get(timeout=1.0)
        except queue_mod.Empty:
            continue
        except Exception:
            continue
        _emit({
            "type": "progress",
            "progress": round(float(getattr(upd, "progress", 0.0) or 0.0), 2),
            "download_speed": float(getattr(upd, "download_speed", 0.0) or 0.0),
            "current_filename": getattr(upd, "current_filename", None),
        })

    try:
        dlm.join()
    except Exception:
        pass

    try:
        core.install_game(igame)
    except Exception as e:
        _emit({"type": "error", "error": f"install finalize failed: {e}"})
        return 1

    _emit({"type": "done"})
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # last-resort
        _emit({"type": "error", "error": f"{e}"})
        sys.exit(1)
