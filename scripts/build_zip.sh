#!/usr/bin/env bash
#
# Build the frontend and package the plugin into a Decky Loader installable zip.
#
# The archive has a single top-level folder named after the plugin (decky-epic/)
# containing only the runtime files Decky needs — dev/build artifacts (src,
# node_modules, source maps, __pycache__) are excluded. Install it on the Deck
# via Decky's "Install from ZIP" (Developer Mode) or by unpacking it into
# ~/homebrew/plugins/.
#
# Requires: pnpm (the project's package manager) and zip.
#
# Usage:
#   bash scripts/build_zip.sh
#   OUT_DIR=/path/to/dist bash scripts/build_zip.sh   # override output location
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLUGIN_NAME="$(grep -oP '"name"\s*:\s*"\K[^"]+' "$REPO_ROOT/plugin.json" | head -1)"
VERSION="$(grep -oP '"version"\s*:\s*"\K[^"]+' "$REPO_ROOT/package.json" | head -1)"
OUT_DIR="${OUT_DIR:-$REPO_ROOT}"
OUT="$OUT_DIR/${PLUGIN_NAME}-v${VERSION}.zip"

command -v pnpm >/dev/null 2>&1 || { echo "error: pnpm not found on PATH" >&2; exit 1; }
command -v zip  >/dev/null 2>&1 || { echo "error: zip not found on PATH"  >&2; exit 1; }

echo ">> Installing dependencies"
( cd "$REPO_ROOT" && pnpm install --frozen-lockfile )

echo ">> Building frontend"
( cd "$REPO_ROOT" && pnpm run build )

# Stage the runtime files under a folder named after the plugin so the zip
# unpacks to <plugin>/... as Decky expects.
STAGE_ROOT="$(mktemp -d)"
trap 'rm -rf "$STAGE_ROOT"' EXIT
STAGE="$STAGE_ROOT/$PLUGIN_NAME"
mkdir -p "$STAGE"

echo ">> Staging plugin files"
cp -r "$REPO_ROOT"/dist "$REPO_ROOT"/py_modules "$REPO_ROOT"/defaults "$REPO_ROOT"/assets "$STAGE"/
cp "$REPO_ROOT"/main.py "$REPO_ROOT"/plugin.json "$REPO_ROOT"/package.json \
   "$REPO_ROOT"/LICENSE "$REPO_ROOT"/README.md "$REPO_ROOT"/decky.pyi "$STAGE"/

# Drop build/dev artifacts that should not ship.
rm -f "$STAGE"/dist/*.map
find "$STAGE" -name '__pycache__' -type d -prune -exec rm -rf {} +
find "$STAGE" -name '*.pyc' -delete

echo ">> Creating zip"
rm -f "$OUT"
( cd "$STAGE_ROOT" && zip -rq -X "$OUT" "$PLUGIN_NAME" )

echo ">> Done: $OUT"
