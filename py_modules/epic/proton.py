"""Discovery of Steam's installed Proton builds (we reuse them rather than ship our own).

A Proton build is a directory containing an executable ``proton`` launcher script.
They live under Steam's ``steamapps/common`` (official builds) and under
``compatibilitytools.d`` (GE-Proton and other custom tools).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

_log = logging.getLogger("decky-epic.proton")


def steam_roots() -> list[Path]:
    home = Path(os.environ.get("DECKY_USER_HOME", str(Path.home())))
    candidates = [
        home / ".steam" / "steam",
        home / ".steam" / "root",
        home / ".local" / "share" / "Steam",
        home / ".var" / "app" / "com.valvesoftware.Steam" / "data" / "Steam",  # flatpak
    ]
    roots: list[Path] = []
    seen = set()
    for c in candidates:
        try:
            real = c.resolve()
        except Exception:
            real = c
        if real.exists() and real not in seen:
            seen.add(real)
            roots.append(real)
    return roots


def _is_proton_dir(d: Path) -> bool:
    return (d / "proton").is_file()


def discover_proton_builds() -> list[dict]:
    """Return [{name, path (proton script), tool_dir}] sorted newest-ish first."""
    builds: dict[str, dict] = {}
    for root in steam_roots():
        search_dirs = [
            root / "steamapps" / "common",
            root / "compatibilitytools.d",
            root / "steamapps" / "compatibilitytools.d",
        ]
        for sd in search_dirs:
            if not sd.is_dir():
                continue
            for child in sorted(sd.iterdir()):
                try:
                    if child.is_dir() and _is_proton_dir(child):
                        name = child.name
                        builds[name] = {
                            "name": name,
                            "path": str(child / "proton"),
                            "tool_dir": str(child),
                        }
                except Exception as e:
                    _log.debug("scanning %s failed: %r", child, e)

    def sort_key(b: dict):
        n = b["name"].lower()
        # Prefer GE-Proton and higher version numbers; crude but effective.
        is_ge = "ge" in n
        digits = "".join(ch if ch.isdigit() else " " for ch in n).split()
        ver = tuple(int(x) for x in digits[:3]) if digits else (0,)
        return (is_ge, ver)

    return sorted(builds.values(), key=sort_key, reverse=True)


def default_proton() -> Optional[dict]:
    builds = discover_proton_builds()
    return builds[0] if builds else None


def resolve_proton(preferred_name: str = "") -> Optional[dict]:
    builds = discover_proton_builds()
    if preferred_name:
        for b in builds:
            if b["name"] == preferred_name:
                return b
    return builds[0] if builds else None
