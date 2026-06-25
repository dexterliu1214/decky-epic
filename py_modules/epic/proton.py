"""Discovery of Steam's installed Proton builds (we reuse them rather than ship our own).

A Proton build is a directory containing an executable ``proton`` launcher script.
They live under Steam's ``steamapps/common`` (official builds) and under
``compatibilitytools.d`` (GE-Proton and other custom tools).
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Optional

_log = logging.getLogger("decky-epic.proton")

# Matches the `"path"   "/some/library"` entries in libraryfolders.vdf
# (works for both the legacy flat format and the current nested one).
_VDF_PATH_RE = re.compile(r'"path"\s*"([^"]+)"')


def library_folders(root: Path) -> list[Path]:
    """Extra Steam library folders declared in libraryfolders.vdf.

    Games — and the Proton builds installed alongside them — often live on an SD
    card or external drive, which Steam records as an additional library folder
    rather than under the main install. Without reading this, Proton on a second
    library is invisible: the classic "No Proton build found" on a Steam Deck
    with games on the SD card.
    """
    paths: list[Path] = []
    for vdf in (root / "steamapps" / "libraryfolders.vdf",
                root / "config" / "libraryfolders.vdf"):
        try:
            text = vdf.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for m in _VDF_PATH_RE.finditer(text):
            paths.append(Path(m.group(1).replace("\\\\", "/")))
    return paths


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
    # Collect every base to scan: each Steam root plus all library folders it
    # declares (SD card / external drives). Deduped by resolved path.
    bases: list[Path] = []
    seen_bases: set[Path] = set()
    for root in steam_roots():
        for base in [root, *library_folders(root)]:
            try:
                real = base.resolve()
            except Exception:
                real = base
            if real not in seen_bases:
                seen_bases.add(real)
                bases.append(real)

    for base in bases:
        search_dirs = [
            base / "steamapps" / "common",
            base / "compatibilitytools.d",
            base / "steamapps" / "compatibilitytools.d",
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
