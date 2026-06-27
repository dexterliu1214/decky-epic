"""Path resolution and legendary config isolation.

Decky exposes its per-plugin directories both via the ``decky`` module and as
environment variables. We read the env vars (with fallbacks) so this module
stays importable outside the Decky runtime for unit tests.

Crucially we point ``LEGENDARY_CONFIG_PATH`` at our own settings dir *before*
``LegendaryCore`` is constructed, so legendary's tokens / installed.json /
metadata live under the plugin and never touch a system-wide ~/.config/legendary.
"""
from __future__ import annotations

import os
from pathlib import Path


def _env_dir(name: str, fallback: Path) -> Path:
    val = os.environ.get(name)
    p = Path(val) if val else fallback
    p.mkdir(parents=True, exist_ok=True)
    return p


# Decky-provided locations (persisted vs. transient).
USER_HOME = Path(os.environ.get("DECKY_USER_HOME", str(Path.home())))
SETTINGS_DIR = _env_dir("DECKY_PLUGIN_SETTINGS_DIR", USER_HOME / ".config" / "decky-epic")
RUNTIME_DIR = _env_dir("DECKY_PLUGIN_RUNTIME_DIR", USER_HOME / ".cache" / "decky-epic")
LOG_DIR = _env_dir("DECKY_PLUGIN_LOG_DIR", RUNTIME_DIR / "logs")
PLUGIN_DIR = Path(os.environ.get("DECKY_PLUGIN_DIR", Path(__file__).resolve().parents[2]))

# Isolated legendary config (tokens, installed.json, metadata, manifests).
LEGENDARY_CONFIG_DIR = _env_dir(
    "DECKY_EPIC_LEGENDARY_CONFIG", SETTINGS_DIR / "legendary"
)

# Per-game Proton/Wine prefixes (compatdata). Transient-ish but should survive
# across plugin reloads, so keep under runtime dir which Decky persists per plugin.
PREFIXES_DIR = _env_dir("DECKY_EPIC_PREFIXES", RUNTIME_DIR / "prefixes")

# Default install location for games (user-overridable in settings).
DEFAULT_INSTALL_DIR = USER_HOME / "Games" / "decky-epic"

# Local caches (Steam reviews, Epic genres, etc.).
CACHE_DIR = _env_dir("DECKY_EPIC_CACHE", SETTINGS_DIR / "cache")

SETTINGS_FILE = SETTINGS_DIR / "settings.json"


def apply_legendary_env() -> None:
    """Force legendary to use our isolated config dir. Call before constructing
    ``LegendaryCore``."""
    os.environ["LEGENDARY_CONFIG_PATH"] = str(LEGENDARY_CONFIG_DIR)


def prefix_for(app_name: str) -> Path:
    """compatdata-style prefix directory for a given Epic app."""
    p = PREFIXES_DIR / app_name
    p.mkdir(parents=True, exist_ok=True)
    return p
