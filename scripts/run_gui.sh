#!/usr/bin/env bash
#
# Launch the desktop GUI on Linux (SteamOS Desktop Mode) over the SAME backend
# the Decky plugin uses — so you can test login / library / install / launch
# from a browser without switching to Game Mode.
#
# By default it points at the REAL Decky plugin config
# (~/homebrew/settings/decky-epic), reusing your existing Epic login and the
# games you already installed in Game Mode. The backend itself runs from THIS
# repo, so local fixes (e.g. Proton discovery) take effect immediately.
#
# Usage:
#   bash scripts/run_gui.sh
#   GUI_PORT=8888 bash scripts/run_gui.sh
#   DEVSTATE_CONFIG=1 bash scripts/run_gui.sh   # use throwaway .devstate config instead
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

VENV="$REPO_ROOT/.devstate/venv"
PY="$VENV/bin/python"

if [ ! -x "$PY" ]; then
  echo ">> Creating venv ($VENV)"
  python3 -m venv "$VENV"
fi

if ! "$PY" -c "import fastapi, uvicorn" 2>/dev/null; then
  echo ">> Installing GUI server deps (fastapi, uvicorn)…"
  "$PY" -m pip install -q --disable-pip-version-check fastapi "uvicorn[standard]"
fi

# Run the backend from this repo (fixed py_modules), reusing the real plugin's
# config + installed games unless DEVSTATE_CONFIG=1 asks for a throwaway state.
export DECKY_USER_HOME="${DECKY_USER_HOME:-$HOME}"
export DECKY_PLUGIN_DIR="$REPO_ROOT"
if [ -z "${DEVSTATE_CONFIG:-}" ]; then
  HB="$DECKY_USER_HOME/homebrew"
  export DECKY_PLUGIN_SETTINGS_DIR="${DECKY_PLUGIN_SETTINGS_DIR:-$HB/settings/decky-epic}"
  export DECKY_PLUGIN_RUNTIME_DIR="${DECKY_PLUGIN_RUNTIME_DIR:-$HB/data/decky-epic}"
  export DECKY_PLUGIN_LOG_DIR="${DECKY_PLUGIN_LOG_DIR:-$HB/logs/decky-epic}"
  echo ">> Using real plugin config: $DECKY_PLUGIN_SETTINGS_DIR"
else
  echo ">> Using throwaway .devstate config"
fi

PORT="${GUI_PORT:-8777}"
URL="http://127.0.0.1:$PORT"
echo ">> Starting decky-epic GUI on $URL  (Ctrl+C to stop)"
( sleep 1.5; command -v xdg-open >/dev/null && xdg-open "$URL" >/dev/null 2>&1 || true ) &

exec env PYTHONPATH="$REPO_ROOT/py_modules" GUI_PORT="$PORT" "$PY" webgui/server.py
