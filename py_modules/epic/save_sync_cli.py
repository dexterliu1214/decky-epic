"""Standalone cloud-save sync, invoked by the Steam launch-options wrapper.

When a game runs in Game Mode it is launched *by Steam* (as a non-Steam
shortcut), so Steam — not our plugin — owns the Proton prefix
(``$STEAM_COMPAT_DATA_PATH``). This CLI is run by steam_save_wrapper.sh around
the game: it points legendary's save-path resolution at that real prefix and
then reuses ``SavesService._sync_blocking`` (the same logic the panel uses) to
pull before / push after.

    python3 save_sync_cli.py <pull|push> <app_name> [--compat <STEAM_COMPAT_DATA_PATH>]

Failures are non-fatal by design — the wrapper ignores our exit code so a sync
hiccup never stops the game from launching.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

# Self-bootstrap: make the vendored `epic` + `legendary` importable regardless
# of how Steam invokes us.
_HERE = os.path.dirname(os.path.abspath(__file__))      # .../py_modules/epic
_PYMODULES = os.path.dirname(_HERE)                      # .../py_modules
if _PYMODULES not in sys.path:
    sys.path.insert(0, _PYMODULES)

logging.basicConfig(level=logging.INFO, format="%(levelname)s save-sync: %(message)s")
_log = logging.getLogger("decky-epic.save-sync")


def _point_legendary_at_prefix(core, app_name: str, compat: str) -> None:
    """Record Steam's compatdata as this app's prefix and force save-path
    re-resolution against it."""
    cfg = core.lgd.config
    env_section = f"{app_name}.env"
    if not cfg.has_section(env_section):
        cfg.add_section(env_section)
    cfg.set(env_section, "STEAM_COMPAT_DATA_PATH", compat)
    if not cfg.has_section(app_name):
        cfg.add_section(app_name)
    cfg.set(app_name, "wine_prefix", os.path.join(compat, "pfx"))
    core.lgd.save_config()
    # Drop any cached save_path so SavesService recomputes against this prefix.
    ig = core.get_installed_game(app_name)
    if ig and ig.save_path:
        ig.save_path = ""
        core.lgd.set_installed_game(app_name, ig)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("direction", choices=["pull", "push"])
    ap.add_argument("app_name")
    ap.add_argument("--compat", default=os.environ.get("STEAM_COMPAT_DATA_PATH", ""))
    args = ap.parse_args()

    from epic import paths
    paths.apply_legendary_env()
    from legendary.core import LegendaryCore
    from epic.legendary_lock import apply_installed_json_locking
    apply_installed_json_locking()

    core = LegendaryCore()
    try:
        core.login()
    except Exception as e:
        _log.warning("login failed (%r) — skipping %s", e, args.direction)
        return 0

    if args.compat:
        try:
            _point_legendary_at_prefix(core, args.app_name, args.compat)
        except Exception as e:
            _log.warning("could not pin prefix %s: %r", args.compat, e)

    from epic.saves_service import SavesService

    class _Shim:
        core = None

    shim = _Shim()
    shim.core = core
    svc = SavesService(shim, emit=None)  # emit unused by the blocking path

    pull = args.direction == "pull"
    push = args.direction == "push"
    try:
        res = svc._sync_blocking(args.app_name, pull, push, False, False)
        _log.info("%s result: %s", args.direction, res.get("action") or res)
    except Exception as e:
        _log.warning("%s failed: %r", args.direction, e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
