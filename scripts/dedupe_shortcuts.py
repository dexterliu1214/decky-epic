#!/usr/bin/env python3
"""Remove duplicate decky-epic Steam shortcuts and their orphan Proton prefixes.

An earlier bug created a new non-Steam shortcut — and a fresh Proton prefix —
on every launch, so the library filled with duplicate "<game> (Epic)" entries
and in-game settings reset each time. This collapses each game's duplicates to a
single shortcut, keeping the prefix that holds the NEWEST save so progress is
preserved, and pins that appid in the plugin settings so it's reused from now on.

Steam MUST be closed first (it rewrites shortcuts.vdf on exit):
    steam -shutdown          # then wait a few seconds

    python3 scripts/dedupe_shortcuts.py            # dedupe + report orphan prefixes
    python3 scripts/dedupe_shortcuts.py --purge    # also delete orphan prefixes

Requires the `vdf` package (pip install vdf).
"""
from __future__ import annotations

import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time

HOME = os.path.expanduser("~")
COMPATDATA = os.path.join(HOME, ".local/share/Steam/steamapps/compatdata")
SETTINGS = os.path.join(HOME, "homebrew/settings/decky-epic/settings.json")
MARKER = "decky-epic"  # only touch our own shortcuts


def _steam_running() -> bool:
    try:
        return subprocess.run(["pgrep", "-x", "steam"], capture_output=True).returncode == 0
    except Exception:
        return False


def _newest_mtime(appid: int) -> float:
    d = os.path.join(COMPATDATA, str(appid))
    latest = 0.0
    for root, _, files in os.walk(d):
        for f in files:
            try:
                latest = max(latest, os.stat(os.path.join(root, f)).st_mtime)
            except OSError:
                pass
    return latest


def _app_name_from_launch(opts: str) -> str | None:
    # LaunchOptions: bash "<...>/steam_save_wrapper.sh" <app_name> %command%
    m = re.search(r"steam_save_wrapper\.sh\"?\s+(\S+)", opts or "")
    return m.group(1) if m else None


def main() -> int:
    purge = "--purge" in sys.argv[1:]

    if _steam_running():
        print("!! Steam is running — close it first:  steam -shutdown", file=sys.stderr)
        return 1

    try:
        import vdf
    except ImportError:
        print("!! needs the 'vdf' package:  pip install vdf", file=sys.stderr)
        return 1

    vdfs = glob.glob(os.path.join(HOME, ".local/share/Steam/userdata/*/config/shortcuts.vdf"))
    if not vdfs:
        print("no shortcuts.vdf found")
        return 0
    path = vdfs[0]

    with open(path, "rb") as f:
        data = vdf.binary_load(f)
    shortcuts = data.get("shortcuts", {})

    # Group our shortcuts by exe.
    groups: dict[str, list] = {}
    others: list = []
    for v in shortcuts.values():
        exe = (v.get("Exe") or v.get("exe") or "").strip('"')
        if MARKER in exe:
            groups.setdefault(exe, []).append(v)
        else:
            others.append(v)

    kept: list = list(others)
    removed_appids: list[int] = []
    settings_map: dict[str, int] = {}

    for exe, entries in groups.items():
        # keep the entry whose prefix has the newest save
        def key(v):
            return _newest_mtime((v.get("appid", 0)) & 0xFFFFFFFF)
        entries.sort(key=key, reverse=True)
        keeper = entries[0]
        keep_appid = keeper.get("appid", 0) & 0xFFFFFFFF
        kept.append(keeper)
        app_name = _app_name_from_launch(keeper.get("LaunchOptions", ""))
        if app_name:
            settings_map[app_name] = keep_appid
        print(f"{os.path.basename(exe)}: keeping appid {keep_appid} "
              f"(newest saves), removing {len(entries) - 1} duplicate(s)")
        for v in entries[1:]:
            removed_appids.append(v.get("appid", 0) & 0xFFFFFFFF)

    if not removed_appids:
        print("No duplicates to remove.")
        return 0

    # Back up and write the re-indexed shortcuts.
    backup = f"{path}.bak.{int(time.time())}"
    shutil.copy2(path, backup)
    print(f"backup: {backup}")
    data["shortcuts"] = {str(i): v for i, v in enumerate(kept)}
    with open(path, "wb") as f:
        vdf.binary_dump(data, f)
    print(f"shortcuts.vdf: {len(shortcuts)} -> {len(kept)} entries")

    # Pin kept appids in plugin settings so launches reuse them.
    if settings_map and os.path.exists(SETTINGS):
        try:
            with open(SETTINGS, "r", encoding="utf-8") as f:
                s = json.load(f)
            s.setdefault("steam_shortcuts", {}).update(settings_map)
            with open(SETTINGS, "w", encoding="utf-8") as f:
                json.dump(s, f, indent=2)
            print(f"pinned in settings: {settings_map}")
        except Exception as e:
            print(f"(could not update settings.json: {e})")

    # Orphan prefixes.
    orphans = [a for a in removed_appids if os.path.isdir(os.path.join(COMPATDATA, str(a)))]
    if orphans:
        print(f"\norphan Proton prefixes ({len(orphans)}):")
        for a in orphans:
            d = os.path.join(COMPATDATA, str(a))
            sz = subprocess.run(["du", "-sh", d], capture_output=True, text=True).stdout.split("\t")[0]
            print(f"  {a}  ({sz})")
        if purge:
            for a in orphans:
                shutil.rmtree(os.path.join(COMPATDATA, str(a)), ignore_errors=True)
            print("purged orphan prefixes.")
        else:
            print("re-run with --purge to delete them and reclaim space.")

    print("\nDone. Restart Steam.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
