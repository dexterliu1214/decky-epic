#!/usr/bin/env bash
#
# Steam launch-options wrapper for cloud-save sync around a Game-Mode launch.
# Set as a non-Steam shortcut's launch options:
#
#     bash "<plugin>/py_modules/epic/steam_save_wrapper.sh" <app_name> %command%
#
# Steam expands %command% to the full Proton command and runs this on the Linux
# host. We pull the cloud save before the game, run it, then push after it exits.
# Sync is best-effort: it never blocks or fails the launch.
set -u

APP="${1:-}"; shift || true
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Reuse the real Decky plugin config (login + installed games) unless overridden.
export DECKY_USER_HOME="${DECKY_USER_HOME:-$HOME}"
export DECKY_PLUGIN_SETTINGS_DIR="${DECKY_PLUGIN_SETTINGS_DIR:-$DECKY_USER_HOME/homebrew/settings/decky-epic}"
export DECKY_PLUGIN_RUNTIME_DIR="${DECKY_PLUGIN_RUNTIME_DIR:-$DECKY_USER_HOME/homebrew/data/decky-epic}"

PY="$(command -v python3 || true)"

sync() {  # $1 = pull|push
  [ -n "$APP" ] && [ -n "$PY" ] || return 0
  "$PY" "$HERE/save_sync_cli.py" "$1" "$APP" --compat "${STEAM_COMPAT_DATA_PATH:-}" || true
}

sync pull
"$@"            # run the game (blocks until it exits)
status=$?
sync push
exit "$status"
