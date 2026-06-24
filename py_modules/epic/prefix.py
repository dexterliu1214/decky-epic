"""Per-game Proton/Wine prefix management.

Epic games are not Steam apps, so there is no Steam-assigned compatdata prefix.
We allocate our own compatdata directory per game under the plugin runtime dir.
Proton creates ``<compatdata>/pfx`` inside it on first launch.

We also persist the prefix into legendary's config so that ``get_save_path`` can
resolve Windows save-path tokens (``{appdata}`` etc.) against the prefix registry
when syncing cloud saves — this is the linchpin of cloud-save support.
"""
from __future__ import annotations

import logging
from pathlib import Path

from . import paths, proton

_log = logging.getLogger("decky-epic.prefix")


def compatdata_dir(app_name: str) -> Path:
    return paths.prefix_for(app_name)


def pfx_dir(app_name: str) -> Path:
    return compatdata_dir(app_name) / "pfx"


def write_legendary_prefix_config(core, app_name: str, steam_root: str) -> str:
    """Tell legendary which Proton prefix this game uses, via the same
    ``STEAM_COMPAT_DATA_PATH`` key its ``get_save_path`` looks for. Returns the
    compatdata path."""
    compat = str(compatdata_dir(app_name))
    cfg = core.lgd.config
    env_section = f"{app_name}.env"
    if not cfg.has_section(env_section):
        cfg.add_section(env_section)
    cfg.set(env_section, "STEAM_COMPAT_DATA_PATH", compat)
    cfg.set(env_section, "STEAM_COMPAT_CLIENT_INSTALL_PATH", steam_root)
    # Also record a plain wine_prefix as a belt-and-suspenders fallback.
    if not cfg.has_section(app_name):
        cfg.add_section(app_name)
    cfg.set(app_name, "wine_prefix", str(pfx_dir(app_name)))
    core.lgd.save_config()
    return compat


def proton_launch_env(app_name: str, steam_root: str) -> dict:
    """Environment overrides required for Proton to run with our prefix."""
    return {
        "STEAM_COMPAT_DATA_PATH": str(compatdata_dir(app_name)),
        "STEAM_COMPAT_CLIENT_INSTALL_PATH": steam_root,
    }


def ensure_prefix(app_name: str) -> Path:
    cd = compatdata_dir(app_name)
    cd.mkdir(parents=True, exist_ok=True)
    return cd


def default_steam_root() -> str:
    roots = proton.steam_roots()
    return str(roots[0]) if roots else ""
