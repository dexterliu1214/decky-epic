"""Steam review-score resolution with a local SQLite cache.

Epic titles aren't Steam apps, so we map each title to a Steam app via the
public store search endpoint, then cache its review summary (positive %, total
review count, descriptive tier like "Very Positive"). The library sort serves
entirely off the cache; a throttled background refresh fills in missing/stale
entries and emits progress so the UI updates live.

Mirrors RawgService so the two score sources behave identically.
"""
from __future__ import annotations

import difflib
import logging
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Awaitable, Callable, Optional

from . import paths
from .rawg import _normalize  # reuse the edition/trademark-stripping title normaliser

_log = logging.getLogger("decky-epic.steam")

EmitFn = Callable[[str, dict], Awaitable[None]]
EVT_PROGRESS = "epic_steam_progress"
EVT_DONE = "epic_steam_done"

STORE_SEARCH = "https://store.steampowered.com/api/storesearch/"
APP_REVIEWS = "https://store.steampowered.com/appreviews/{appid}"
_MIN_INTERVAL = 0.5  # be gentle with the public Steam store endpoints


class SteamReviewsService:
    def __init__(self, settings) -> None:
        self.settings = settings
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="steamrev")
        self._req_lock = threading.Lock()
        self._last_req = 0.0
        self._db_path = str(paths.CACHE_DIR / "steam_reviews.sqlite")
        self._init_db()

    # -- db ------------------------------------------------------------------
    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path, timeout=10)

    def _init_db(self) -> None:
        with self._conn() as c:
            c.execute(
                """CREATE TABLE IF NOT EXISTS reviews (
                    app_name TEXT PRIMARY KEY,
                    title TEXT,
                    steam_appid INTEGER,
                    positive_pct INTEGER,
                    total_reviews INTEGER,
                    review_desc TEXT,
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
                f"SELECT app_name, positive_pct, total_reviews, review_desc, matched_name, fetched_at "
                f"FROM reviews WHERE app_name IN ({qmarks})",
                app_names,
            ):
                out[row[0]] = {
                    "positive_pct": row[1],
                    "total_reviews": row[2],
                    "review_desc": row[3],
                    "matched_name": row[4],
                    "fetched_at": row[5],
                }
        return out

    def _upsert(self, app_name, title, appid, pct, total, desc, matched) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO reviews(app_name,title,steam_appid,positive_pct,total_reviews,review_desc,"
                "matched_name,fetched_at) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(app_name) DO UPDATE SET "
                "title=excluded.title, steam_appid=excluded.steam_appid, positive_pct=excluded.positive_pct, "
                "total_reviews=excluded.total_reviews, review_desc=excluded.review_desc, "
                "matched_name=excluded.matched_name, fetched_at=excluded.fetched_at",
                (app_name, title, appid, pct, total, desc, matched, time.time()),
            )

    # -- Steam http ----------------------------------------------------------
    def _throttle(self) -> None:
        with self._req_lock:
            dt = time.time() - self._last_req
            if dt < _MIN_INTERVAL:
                time.sleep(_MIN_INTERVAL - dt)
            self._last_req = time.time()

    def _resolve_appid(self, title: str):
        import requests  # vendored

        self._throttle()
        try:
            r = requests.get(STORE_SEARCH, params={"term": title, "cc": "us", "l": "en"}, timeout=15)
            if r.status_code != 200:
                return None, None
            items = r.json().get("items") or []
        except Exception as e:
            _log.warning("Steam search failed for %r: %r", title, e)
            return None, None
        if not items:
            return None, None

        target = _normalize(title)
        best, best_key = None, (-1.0, 0)
        for it in items:
            ratio = difflib.SequenceMatcher(None, target, _normalize(it.get("name", ""))).ratio()
            key = (ratio, -len(it.get("name", "")))  # prefer base game over editions
            if key > best_key:
                best, best_key = it, key
        if not best or best_key[0] < 0.5:
            best = items[0]
        return best.get("id"), best.get("name")

    def _fetch_reviews(self, appid: int) -> Optional[dict]:
        import requests

        self._throttle()
        try:
            r = requests.get(
                APP_REVIEWS.format(appid=appid),
                params={"json": 1, "language": "all", "purchase_type": "all",
                        "num_per_page": 0, "review_type": "all"},
                timeout=15,
            )
            if r.status_code != 200:
                return None
            qs = (r.json() or {}).get("query_summary") or {}
        except Exception as e:
            _log.warning("Steam reviews failed for %s: %r", appid, e)
            return None
        total = int(qs.get("total_reviews") or 0)
        pos = int(qs.get("total_positive") or 0)
        if total <= 0:
            return {"positive_pct": None, "total_reviews": 0,
                    "review_desc": qs.get("review_score_desc") or "No user reviews"}
        return {"positive_pct": round(pos * 100 / total), "total_reviews": total,
                "review_desc": qs.get("review_score_desc") or ""}

    def _fetch_one(self, title: str) -> Optional[dict]:
        appid, matched = self._resolve_appid(title)
        if not appid:
            # Record the miss so we don't keep re-searching every refresh.
            return {"steam_appid": None, "positive_pct": None, "total_reviews": 0,
                    "review_desc": "Not on Steam", "matched_name": None}
        rev = self._fetch_reviews(appid)
        if rev is None:
            return None  # transient error — leave it for the next refresh
        return {"steam_appid": appid, "matched_name": matched, **rev}

    # -- public async surface ------------------------------------------------
    async def refresh(self, items: list[dict], emit: EmitFn, force: bool = False) -> dict:
        """items: [{app_name, title}]. Fetch missing/stale reviews, emit progress."""
        import asyncio

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
            res = await loop.run_in_executor(self._executor, self._fetch_one, it["title"])
            if res is not None:
                self._upsert(it["app_name"], it["title"], res.get("steam_appid"),
                             res.get("positive_pct"), res.get("total_reviews"),
                             res.get("review_desc"), res.get("matched_name"))
            done += 1
            await emit(EVT_PROGRESS, {
                "app_name": it["app_name"],
                "positive_pct": (res or {}).get("positive_pct"),
                "total_reviews": (res or {}).get("total_reviews"),
                "review_desc": (res or {}).get("review_desc"),
                "done": done,
                "total": len(todo),
            })
        await emit(EVT_DONE, {"ok": True, "refreshed": len(todo)})
        return {"ok": True, "refreshed": len(todo)}

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
