"""Offline validation of the RAWG module — no API key / network needed.

Monkeypatches requests.get to return a canned RAWG search payload, then checks:
fuzzy title matching, metacritic extraction, edition-suffix normalization, the
no-key path, and the SQLite cache round-trip.
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DECKY_PLUGIN_SETTINGS_DIR"] = tempfile.mkdtemp(prefix="rawg-test-")
os.environ["DECKY_PLUGIN_RUNTIME_DIR"] = os.environ["DECKY_PLUGIN_SETTINGS_DIR"]
sys.path.append(os.path.join(REPO, "py_modules"))

import requests  # venv
from epic.rawg import RawgService, _normalize
from epic.settings_store import SettingsStore

problems = []


def check(cond, msg):
    print(("  OK  " if cond else " FAIL ") + msg)
    if not cond:
        problems.append(msg)


# canned RAWG /games?search= responses keyed loosely by query
CANNED = {
    "hades": {"results": [
        {"id": 1, "name": "Hades II", "metacritic": 90},
        {"id": 2, "name": "Hades", "metacritic": 93},
    ]},
    "control": {"results": [
        {"id": 3, "name": "Control Ultimate Edition", "metacritic": 84},
        {"id": 4, "name": "Control", "metacritic": 82},
    ]},
    "empty": {"results": []},
}


class FakeResp:
    def __init__(self, data):
        self.status_code = 200
        self._data = data

    def json(self):
        return self._data


def fake_get(url, params=None, timeout=None):
    q = (params or {}).get("search", "").lower()
    key = "empty"
    if "hades" in q:
        key = "hades"
    elif "control" in q:
        key = "control"
    return FakeResp(CANNED[key])


async def run():
    # normalization strips edition suffixes / trademark glyphs
    # edition/ultimate are stripped as edition suffixes for matching purposes
    check(_normalize("Control™ Ultimate Edition") == "control", f"_normalize -> {_normalize('Control Ultimate Edition')!r}")

    requests.get = fake_get  # monkeypatch

    settings = SettingsStore()
    settings.update({"rawg_api_key": "FAKE_KEY"})
    svc = RawgService(settings)

    events = []

    async def emit(event, payload):
        events.append((event, payload))

    items = [
        {"app_name": "AppHades", "title": "Hades: Definitive Edition"},
        {"app_name": "AppControl", "title": "Control"},
        {"app_name": "AppMissing", "title": "Totally Unknown Empty Game"},
    ]
    res = await svc.refresh(items, emit, force=True)
    check(res.get("ok") is True, f"refresh ok ({res})")

    cached = svc.cached(["AppHades", "AppControl", "AppMissing"])
    check(cached.get("AppHades", {}).get("metacritic") == 93, f"Hades matched 93 ({cached.get('AppHades')})")
    check(cached.get("AppControl", {}).get("metacritic") == 82, f"Control matched 82 ({cached.get('AppControl')})")
    # missing game: empty results -> no upsert -> absent from cache
    check("AppMissing" not in cached, "unmatched game not cached")

    # progress + done events emitted
    check(any(e[0] == "epic_rawg_done" for e in events), "epic_rawg_done emitted")
    check(sum(1 for e in events if e[0] == "epic_rawg_progress") == 3, "one progress event per item")

    # no-key path
    settings.update({"rawg_api_key": ""})
    svc2 = RawgService(settings)
    res2 = await svc2.refresh(items, emit, force=True)
    check(res2.get("error") == "no_api_key", "no-key path returns no_api_key")

    svc.shutdown()
    svc2.shutdown()
    print("\n" + ("RAWG OFFLINE TESTS PASSED" if not problems else f"{len(problems)} PROBLEM(S)"))
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
