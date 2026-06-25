#!/usr/bin/env bash
#
# Deploy the locally-built plugin into the on-device Decky plugins dir and
# restart the loader. Run this ON the Steam Deck itself (no SSH). Needs sudo
# because ~/homebrew/plugins is root-owned.
#
#   bash scripts/deploy_local.sh
#
# Build the frontend first (scripts/build_zip.sh does this, or `pnpm run build`).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${DEST:-/home/deck/homebrew/plugins/decky-epic}"

if [ ! -f "$REPO_ROOT/dist/index.js" ]; then
  echo "!! dist/index.js missing — run 'pnpm run build' (or scripts/build_zip.sh) first." >&2
  exit 1
fi

echo ">> Syncing runtime files to $DEST (sudo)"
sudo mkdir -p "$DEST/dist" "$DEST/py_modules"
# Frontend bundle, backend entry, and the epic package (where our fixes live).
sudo cp -f  "$REPO_ROOT/dist/index.js"      "$DEST/dist/index.js"
sudo cp -f  "$REPO_ROOT/main.py"            "$DEST/main.py"
sudo cp -f  "$REPO_ROOT/plugin.json"        "$DEST/plugin.json"
sudo cp -f  "$REPO_ROOT/package.json"       "$DEST/package.json"
sudo cp -rf "$REPO_ROOT/py_modules/epic"    "$DEST/py_modules/"

echo ">> Restarting Decky plugin loader"
sudo systemctl restart plugin_loader && echo ">> Done. Re-open the Epic plugin in Decky." \
  || echo "   (couldn't restart plugin_loader; toggle the plugin in Decky instead)"
