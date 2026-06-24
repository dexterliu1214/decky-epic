#!/usr/bin/env bash
#
# Deploy the built plugin to a Steam Deck running Decky in Developer Mode.
# Requires: `pnpm run build` already done, SSH access to the Deck, and Decky's
# "Developer Mode" enabled (which creates ~/homebrew/plugins and allows unsigned
# plugins). The Deck must have `python3` (>=3.10) available for the backend.
#
# Usage:
#   DECK_HOST=deck@steamdeck.local bash scripts/deploy_to_deck.sh
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DECK_HOST="${DECK_HOST:-deck@steamdeck.local}"
DEST="${DEST:-/home/deck/homebrew/plugins/decky-epic}"

echo ">> Building frontend"
( cd "$REPO_ROOT" && pnpm run build )

echo ">> Syncing to $DECK_HOST:$DEST"
ssh "$DECK_HOST" "mkdir -p '$DEST'"
rsync -avz --delete \
  --exclude node_modules \
  --exclude src \
  --exclude .git \
  --exclude '*.map' \
  "$REPO_ROOT"/dist \
  "$REPO_ROOT"/py_modules \
  "$REPO_ROOT"/defaults \
  "$REPO_ROOT"/assets \
  "$REPO_ROOT"/main.py \
  "$REPO_ROOT"/plugin.json \
  "$REPO_ROOT"/package.json \
  "$DECK_HOST:$DEST/"

echo ">> Restarting Decky plugin loader (may prompt for the deck sudo password)"
ssh -t "$DECK_HOST" "sudo systemctl restart plugin_loader" || \
  echo "   (could not restart plugin_loader automatically; toggle the plugin in Decky)"

echo ">> Done. Open Decky on the Deck to load decky-epic."
