"""Print the Epic launch arguments for a game, one per line.

Game-Mode launches go through Steam as a bare exe, so the game never receives
the Epic parameters (-epicuserid / -AUTH_* / -EpicPortal ...). Without them an
EOS game can't tell which Epic account is running and falls back to its default
(non-Epic) save folder — which then never matches Epic's CloudSaveFolder, so
cloud sync sees "no save".

steam_save_wrapper.sh runs this at launch time (the -AUTH_PASSWORD exchange code
is single-use and short-lived, so it must be generated per launch, not baked
into the shortcut) and appends the lines to the game command.

    python3 epic_launch_args.py <app_name>

Prints nothing and exits 0 on any failure, so the game still launches.
"""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_PYMODULES = os.path.dirname(_HERE)
if _PYMODULES not in sys.path:
    sys.path.insert(0, _PYMODULES)


def main() -> int:
    if len(sys.argv) < 2:
        return 0
    app_name = sys.argv[1]
    try:
        from epic import paths
        paths.apply_legendary_env()
        from legendary.core import LegendaryCore

        core = LegendaryCore()
        core.login()
        params = core.get_launch_parameters(app_name)
        args = list(params.game_parameters) + list(params.user_parameters) + list(params.egl_parameters)
        sys.stdout.write("\n".join(args))
        if args:
            sys.stdout.write("\n")
    except Exception as e:
        sys.stderr.write(f"epic_launch_args failed: {e!r}\n")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
