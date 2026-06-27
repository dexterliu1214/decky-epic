"""Validate the backend against the REAL legendary API (run with the repo .venv).

Asserts that every LegendaryCore method / signature and model field the backend
relies on actually exists in the installed legendary, and that EpicCore + all
epic.* modules import and construct. Catches API drift without a Steam Deck.

    .venv\\Scripts\\python.exe scripts\\devtools\\verify_legendary_api.py
"""
from __future__ import annotations

import inspect
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Append (not prepend) so the venv's legendary wins over the Linux-bundled copy.
sys.path.append(os.path.join(REPO, "py_modules"))

_tmp = tempfile.mkdtemp(prefix="legverify-")
os.environ["DECKY_PLUGIN_SETTINGS_DIR"] = os.path.join(_tmp, "settings")
os.environ["DECKY_PLUGIN_RUNTIME_DIR"] = os.path.join(_tmp, "runtime")

problems: list[str] = []


def check(cond, msg):
    print(("  OK  " if cond else " FAIL ") + msg)
    if not cond:
        problems.append(msg)


def has_params(func, names):
    sig = inspect.signature(func)
    return all(n in sig.parameters for n in names)


import legendary
from legendary.core import LegendaryCore

print(f"legendary {legendary.__version__} from {legendary.__file__}")
check(".venv" in legendary.__file__ or "site-packages" in legendary.__file__,
      "legendary resolves to the venv copy (not the Linux-bundled one)")

for m in ["auth_code", "login", "get_game", "get_game_list", "get_installed_list",
          "get_installed_game", "prepare_download", "install_game", "uninstall_game",
          "get_save_games", "get_save_path", "check_savegame_state", "download_saves",
          "upload_save", "get_launch_parameters"]:
    check(hasattr(LegendaryCore, m), f"LegendaryCore.{m} exists")

check(has_params(LegendaryCore.prepare_download, ["game", "base_path", "status_q", "max_workers", "platform"]),
      "prepare_download(game, base_path, status_q, max_workers, platform)")
check(has_params(LegendaryCore.get_launch_parameters, ["app_name", "wrapper", "disable_wine"]),
      "get_launch_parameters(app_name, wrapper, disable_wine)")
check(has_params(LegendaryCore.download_saves, ["app_name", "save_dir", "clean_dir", "manifest_name"]),
      "download_saves(app_name, save_dir, clean_dir, manifest_name)")
check(has_params(LegendaryCore.get_save_path, ["app_name", "platform"]),
      "get_save_path(app_name, platform)")

from legendary.models.downloading import UIUpdate
from legendary.models.game import SaveGameStatus, LaunchParameters

check({"progress", "download_speed", "write_speed"}.issubset(set(UIUpdate.__dataclass_fields__)),
      "UIUpdate has progress/download_speed/write_speed")
check(all(hasattr(SaveGameStatus, s) for s in ["LOCAL_NEWER", "REMOTE_NEWER", "SAME_AGE", "NO_SAVE"]),
      "SaveGameStatus enum complete")
check({"launch_command", "game_executable", "game_directory", "working_directory",
       "game_parameters", "egl_parameters", "environment"}.issubset(set(LaunchParameters.__dataclass_fields__)),
      "LaunchParameters fields present")

from epic.core_service import EpicCore, _extract_auth_code, _cover_url, _supports_cloud_saves

ec = EpicCore()
check(ec.core is not None, "EpicCore() constructs a LegendaryCore")
check(hasattr(ec.core, "lgd") and hasattr(ec.core.lgd, "invalidate_userdata"),
      "core.lgd.invalidate_userdata exists (logout path)")
check(EpicCore.login_url().startswith("https://"), "login_url() is https")
check(_extract_auth_code('{"authorizationCode":"abc"}') == "abc", "_extract_auth_code parses JSON")
check(_cover_url({"keyImages": [{"type": "DieselGameBoxTall", "url": "X"}]}) == "X", "_cover_url picks tall art")
check(_supports_cloud_saves({"customAttributes": {"CloudSaveFolder": {"value": "{appdata}/x"}}}) is True,
      "_supports_cloud_saves detects CloudSaveFolder")
ec.close()

import importlib
for mod in ["epic.download_service", "epic.saves_service", "epic.launch_service",
            "epic.proton", "epic.prefix", "epic.steam_reviews", "epic.settings_store"]:
    importlib.import_module(mod)
    print(f"  imported {mod}")

print("\n" + ("ALL CHECKS PASSED" if not problems else f"{len(problems)} PROBLEM(S): " + "; ".join(problems)))
sys.exit(1 if problems else 0)
