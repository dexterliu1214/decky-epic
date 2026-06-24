"""RAWG critic-score resolution with a local SQLite cache.

RAWG game objects carry a top-level ``metacritic`` int. We map each Epic title
to a RAWG game by name (best fuzzy match), cache the result, and serve the
library sort entirely off the cache. A throttled background refresh fills in
missing/stale entries and emits progress so the UI updates live.

Attribution: scores are provided by RAWG.io and must be credited in the UI.
"""
from __future__ import annotations

import difflib
import logging
import re
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Awaitable, Callable, Optional

from . import paths

_log = logging.getLogger("decky-epic.rawg")

EmitFn = Callable[[str, dict], Awaitable[None]]
EVT_PROGRESS = "epic_rawg_progress"
EVT_DONE = "epic_rawg_done"

RAWG_SEARCH = "https://api.rawg.io/api/games"
_MIN_INTERVAL = 0.34  # ~3 req/s, well under RAWG limits

_EDITION_RE = re.compile(
    r"\b(deluxe|ultimate|definitive|complete|game of the year|goty|gold|"
    r"standard|premium|enhanced|remastered|director'?s cut|edition|bundle)\b",
    re.IGNORECASE,
)
_TRADE_RE = re.compile(r"[™®©]")


def _normalize(title: str) -> str:
    t = _TRADE_RE.sub("", title or "")
    t = _EDITION_RE.sub("", t)
    t = re.sub(r"[^a-z0-9]+", " ", t.lower())
    return t.strip()


class RawgService:
    def __init__(self, settings) -> None:
        self.settings = settings
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="rawg")
        self._req_lock = threading.Lock()
        self._last_req = 0.0
        self._db_path = str(paths.CACHE_DIR / "rawg.sqlite")
        self._init_db()

    # -- db ------------------------------------------------------------------
    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path, timeout=10)

    def _init_db(self) -> None:
        with self._conn() as c:
            c.execute(
                """CREATE TABLE IF NOT EXISTS scores (
                    app_name TEXT PRIMARY KEY,
                    title TEXT,
                    rawg_id INTEGER,
                    metacritic INTEGER,
                    matched_name TEXT,
                    fetched_at REAL
                )"""
            )

    def _ttl_seconds(self) -> float:
        return float(self.settings.get("metacritic_cache_ttl_days", 14)) * 86400.0

    def cached(self, app_names: list[str]) -> dict[str, dict]:
        if not app_names:
            return {}
        out: dict[str, dict] = {}
        with self._conn() as c:
            qmarks = ",".join("?" * len(app_names))
            for row in c.execute(
                f"SELECT app_name, metacritic, matched_name, fetched_at FROM scores "
                f"WHERE app_name IN ({qmarks})",
                app_names,
            ):
                out[row[0]] = {
                    "metacritic": row[1],
                    "matched_name": row[2],
                    "fetched_at": row[3],
                }
        return out

    def _upsert(self, app_name, title, rawg_id, metacritic, matched_name) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO scores(app_name,title,rawg_id,metacritic,matched_name,fetched_at) "
                "VALUES(?,?,?,?,?,?) ON CONFLICT(app_name) DO UPDATE SET "
                "title=excluded.title, rawg_id=excluded.rawg_id, metacritic=excluded.metacritic, "
                "matched_name=excluded.matched_name, fetched_at=excluded.fetched_at",
                (app_name, title, rawg_id, metacritic, matched_name, time.time()),
            )

    # -- RAWG http -----------------------------------------------------------
    def _throttle(self) -> None:
        with self._req_lock:
            dt = time.time() - self._last_req
            if dt < _MIN_INTERVAL:
                time.sleep(_MIN_INTERVAL - dt)
            self._last_req = time.time()

    def _fetch_one(self, title: str, api_key: str) -> Optional[dict]:
        import requests  # vendored

        self._throttle()
        try:
            r = requests.get(
                RAWG_SEARCH,
                params={"search": title, "key": api_key, "page_size": 6},
                timeout=15,
            )
            if r.status_code != 200:
                _log.warning("RAWG search %r -> HTTP %s", title, r.status_code)
                return None
            results = r.json().get("results") or []
        except Exception as e:
            _log.warning("RAWG search failed for %r: %r", title, e)
            return None
        if not results:
            return None

        target = _normalize(title)
        best, best_key = None, (-1.0, 0)
        for g in results:
            ratio = difflib.SequenceMatcher(None, target, _normalize(g.get("name", ""))).ratio()
            # Higher ratio wins; on a tie prefer the shorter original name so the
            # base game ("Control") beats an edition ("Control Ultimate Edition").
            key = (ratio, -len(g.get("name", "")))
            if key > best_key:
                best, best_key = g, key
        if not best or best_key[0] < 0.5:
            best = results[0]
        return {
            "rawg_id": best.get("id"),
            "metacritic": best.get("metacritic"),
            "matched_name": best.get("name"),
        }

    # -- public async surface ------------------------------------------------
    async def refresh(self, items: list[dict], emit: EmitFn, force: bool = False) -> dict:
        """items: [{app_name, title}]. Fetch missing/stale scores, emit progress."""
        import asyncio

        api_key = str(self.settings.get("rawg_api_key", "") or "").strip()
        if not api_key:
            await emit(EVT_DONE, {"ok": False, "error": "no_api_key"})
            return {"ok": False, "error": "no_api_key"}

        cached = self.cached([i["app_name"] for i in items])
        ttl = self._ttl_seconds()
        now = time.time()
        todo = []
        for it in items:
            c = cached.get(it["app_name"])
            stale = (not c) or (now - (c.get("fetched_at") or 0) > ttl)
            if force or stale:
                todo.append(it)

        loop = asyncio.get_running_loop()
        done = 0
        for it in todo:
            res = await loop.run_in_executor(
                self._executor, self._fetch_one, it["title"], api_key
            )
            if res is not None:
                self._upsert(it["app_name"], it["title"], res["rawg_id"],
                             res["metacritic"], res["matched_name"])
            done += 1
            await emit(EVT_PROGRESS, {
                "app_name": it["app_name"],
                "metacritic": (res or {}).get("metacritic"),
                "done": done,
                "total": len(todo),
            })
        await emit(EVT_DONE, {"ok": True, "refreshed": len(todo)})
        return {"ok": True, "refreshed": len(todo)}

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
