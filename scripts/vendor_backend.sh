#!/usr/bin/env bash
#
# Vendor the Python backend dependencies into ./py_modules so they ship with the
# plugin and run on SteamOS (Linux x86_64) regardless of the dev machine OS.
#
# Why this is not a plain `pip install --target`:
#   * legendary requires Python >= 3.10; a 3.9 dev box can't `pip install` it, but
#     the package itself is pure-python, so we copy the package dir directly and
#     fabricate its .dist-info (legendary/__init__.py calls
#     importlib.metadata.version('legendary-gl') at import time).
#   * pycryptodomex / charset-normalizer have native extensions; we must fetch the
#     *Linux* wheels, never the host-OS ones. pycryptodomex ships an abi3 wheel
#     (CPython 3.7+), so it is Python-version independent on the Deck.
#
# Re-run this whenever bumping legendary or its deps.
#
# Usage:  bash scripts/vendor_backend.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYM="$REPO_ROOT/py_modules"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

LEGENDARY_REF="${LEGENDARY_REF:-master}"
PY_TARGET="${PY_TARGET:-3.11}"      # SteamOS CPython; pycryptodomex uses abi3 so this is not strict
PLAT="${PLAT:-manylinux2014_x86_64}"

echo ">> Cleaning previously vendored deps (keeps py_modules/epic)"
find "$PYM" -mindepth 1 -maxdepth 1 ! -name epic -exec rm -rf {} +

echo ">> Cloning legendary ($LEGENDARY_REF)"
git clone --depth 1 --branch "$LEGENDARY_REF" https://github.com/legendary-gl/legendary.git "$TMP/legendary-src" 2>/dev/null \
  || git clone --depth 1 https://github.com/legendary-gl/legendary.git "$TMP/legendary-src"

LEG_VER="$(grep -m1 -E '^version' "$TMP/legendary-src/pyproject.toml" | sed -E 's/.*"([^"]+)".*/\1/')"
echo ">> legendary version: $LEG_VER"

cp -r "$TMP/legendary-src/legendary" "$PYM/legendary"

# Fabricate dist-info so importlib.metadata.version('legendary-gl') resolves.
DI="$PYM/legendary_gl-$LEG_VER.dist-info"
mkdir -p "$DI"
cat > "$DI/METADATA" <<EOF
Metadata-Version: 2.1
Name: legendary-gl
Version: $LEG_VER
EOF
echo "Wheel-Version: 1.0" > "$DI/WHEEL"

echo ">> Downloading Linux wheels for native/runtime deps"
mkdir -p "$TMP/wheels"
# pycryptodomex: native, abi3 -> one wheel works across CPython 3.7+
pip download --only-binary=:all: --no-deps \
  --platform "$PLAT" --implementation cp --python-version "$PY_TARGET" --abi abi3 \
  pycryptodomex -d "$TMP/wheels"
# remaining deps: pip picks latest compatible (universal py3 or cp-tagged linux)
pip download --only-binary=:all: --no-deps \
  --platform "$PLAT" --python-version "$PY_TARGET" \
  requests urllib3 certifi idna charset-normalizer filelock -d "$TMP/wheels"

echo ">> Extracting wheels into py_modules"
for whl in "$TMP/wheels"/*.whl; do
  python -c "import sys,zipfile; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" "$whl" "$PYM"
done

echo ">> Pruning bytecode / test bloat"
find "$PYM" -type d -name '__pycache__' -prune -exec rm -rf {} +
find "$PYM" -type d -name 'tests' -prune -exec rm -rf {} +

echo ">> Done. Vendored into $PYM:"
ls -1 "$PYM"
