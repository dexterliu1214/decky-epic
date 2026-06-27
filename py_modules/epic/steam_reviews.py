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
import json
import logging
import re
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

# Multi-character Roman numerals -> their integer string, so "Shenmue 3" and
# "Shenmue III" compare equal. Single letters (i/v/x) are excluded — too often
# real words or parts of a name.
_ROMAN_TO_INT = {
    "ii": "2", "iii": "3", "iv": "4", "vi": "6", "vii": "7", "viii": "8",
    "ix": "9", "xi": "11", "xii": "12", "xiii": "13",
}


def _sequel_nums(normalized: str) -> set:
    """Sequel/version numbers that distinguish two games, with Roman numerals
    folded to digits: {'2'} for "the outer worlds 2", {'3'} for both "shenmue 3"
    and "shenmue iii", {} for "the outer worlds"."""
    out = set()
    for t in normalized.split():
        if t.isdigit():
            out.add(t)
        elif t in _ROMAN_TO_INT:
            out.add(_ROMAN_TO_INT[t])
    return out


# Drop disambiguating release years like "(2016)" before matching.
_YEAR_RE = re.compile(r"\((?:19|20)\d{2}\)")
# Search hits that aren't the game itself.
_NON_GAME_RE = re.compile(
    r"\b(soundtrack|ost|demo|trailer|art\s?book|season\s?pass|wallpaper|upgrade|"
    r"prologue|playtest|beta)\b",
    re.IGNORECASE,
)


def _match_norm(name: str) -> str:
    """Normalize for matching: strip release years, then fold Roman numerals to
    digits so "Shenmue III" == "Shenmue 3"."""
    n = _normalize(_YEAR_RE.sub("", name or ""))
    return " ".join(_ROMAN_TO_INT.get(t, t) for t in n.split())


def _subtitle_head(name: str) -> str:
    """The part of a Steam name before a ': '/' - ' subtitle, normalized — so
    "TOEM: A Photo Adventure" yields "toem"."""
    return _match_norm(re.split(r"[:\-–—]", name or "", 1)[0])


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
            # Migrations for columns older caches lack.
            for col in ("localized_name TEXT", "name_lang TEXT", "genres TEXT"):
                try:
                    c.execute(f"ALTER TABLE reviews ADD COLUMN {col}")
                except sqlite3.OperationalError:
                    pass  # column already exists

    def _ttl_seconds(self) -> float:
        return float(self.settings.get("metacritic_cache_ttl_days", 14)) * 86400.0

    def cached(self, app_names: list[str]) -> dict[str, dict]:
        if not app_names:
            return {}
        out: dict[str, dict] = {}
        with self._conn() as c:
            qmarks = ",".join("?" * len(app_names))
            for row in c.execute(
                f"SELECT app_name, positive_pct, total_reviews, review_desc, matched_name, fetched_at, "
                f"localized_name, name_lang, genres FROM reviews WHERE app_name IN ({qmarks})",
                app_names,
            ):
                out[row[0]] = {
                    "positive_pct": row[1],
                    "total_reviews": row[2],
                    "review_desc": row[3],
                    "matched_name": row[4],
                    "fetched_at": row[5],
                    "localized_name": row[6],
                    "name_lang": row[7],
                    "genres": json.loads(row[8]) if row[8] else [],
                }
        return out

    def _upsert(self, app_name, title, appid, pct, total, desc, matched, localized, name_lang, genres) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO reviews(app_name,title,steam_appid,positive_pct,total_reviews,review_desc,"
                "matched_name,fetched_at,localized_name,name_lang,genres) VALUES(?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(app_name) DO UPDATE SET "
                "title=excluded.title, steam_appid=excluded.steam_appid, positive_pct=excluded.positive_pct, "
                "total_reviews=excluded.total_reviews, review_desc=excluded.review_desc, "
                "matched_name=excluded.matched_name, fetched_at=excluded.fetched_at, "
                "localized_name=excluded.localized_name, name_lang=excluded.name_lang, genres=excluded.genres",
                (app_name, title, appid, pct, total, desc, matched, time.time(), localized, name_lang,
                 json.dumps(genres) if genres else None),
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

        target = _match_norm(title)
        target_nums = _sequel_nums(target)
        # Keep only plausible candidates: actual games (not OST/demo/…) with the
        # same sequel number ("The Outer Worlds" must not match "…2").
        cands = []
        for it in items:
            raw = it.get("name", "")
            if _NON_GAME_RE.search(raw):
                continue
            nm = _match_norm(raw)
            if _sequel_nums(nm) != target_nums:
                continue
            cands.append((it, raw, nm))
        if not cands:
            return None, None

        # 1) Exact title match — confident. Prefer the shortest raw name (base
        #    game over an edition).
        exact = [(it, raw) for it, raw, nm in cands if nm == target]
        if exact:
            it, _ = min(exact, key=lambda x: len(x[1]))
            return it.get("id"), it.get("name")

        # 2) Unambiguous subtitle: exactly one candidate is "<target>: subtitle"
        #    ("TOEM" -> "TOEM: A Photo Adventure"). If several share the prefix
        #    (e.g. two different "The Textorcist: …"), it's ambiguous — skip.
        subs = [(it, raw) for it, raw, nm in cands if _subtitle_head(raw) == target]
        if len(subs) == 1:
            it, _ = subs[0]
            return it.get("id"), it.get("name")

        # 3) Fuzzy match — high enough to keep "… Extended Edition" type hits but
        #    reject loosely-related names ("Pine" vs "Pine Beat" ~0.6).
        best, best_ratio = None, 0.0
        for it, raw, nm in cands:
            ratio = difflib.SequenceMatcher(None, target, nm).ratio()
            if ratio > best_ratio:
                best, best_ratio = it, ratio
        if best and best_ratio >= 0.72:
            return best.get("id"), best.get("name")
        return None, None

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

    def _app_genres(self, appid: int) -> list:
        """Steam genres (English, for stable filter keys), e.g. Action, RPG."""
        import requests

        self._throttle()
        try:
            r = requests.get(
                "https://store.steampowered.com/api/appdetails",
                params={"appids": appid, "l": "english"},
                timeout=15,
            )
            d = (r.json() or {}).get(str(appid)) or {}
            if not d.get("success"):
                return []
            return [g.get("description") for g in ((d.get("data") or {}).get("genres") or []) if g.get("description")]
        except Exception as e:
            _log.warning("Steam genres failed for %s: %r", appid, e)
            return []

    def _fetch_one(self, title: str, lang: str = "english") -> Optional[dict]:
        appid, matched = self._resolve_appid(title)  # English search for reliable matching
        if not appid:
            # Record the miss so we don't keep re-searching every refresh.
            return {"steam_appid": None, "positive_pct": None, "total_reviews": 0,
                    "review_desc": "Not on Steam", "matched_name": None,
                    "localized_name": None, "name_lang": lang, "genres": []}
        rev = self._fetch_reviews(appid)
        if rev is None:
            return None  # transient error — leave it for the next refresh
        # Localized names now come from Epic's own catalog, so Steam only owes us
        # the review summary and genres here.
        genres = self._app_genres(appid)
        return {"steam_appid": appid, "matched_name": matched, "localized_name": None,
                "name_lang": lang, "genres": genres, **rev}

    # -- public async surface ------------------------------------------------
    async def refresh(self, items: list[dict], emit: EmitFn, force: bool = False) -> dict:
        """items: [{app_name, title}]. Fetch missing/stale reviews, emit progress.
        An entry is also refreshed when the cached localized name was fetched in a
        different language than the user's current preference."""
        import asyncio

        lang = str(self.settings.get("preferred_language", "english") or "english")
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
            res = await loop.run_in_executor(self._executor, self._fetch_one, it["title"], lang)
            if res is not None:
                self._upsert(it["app_name"], it["title"], res.get("steam_appid"),
                             res.get("positive_pct"), res.get("total_reviews"),
                             res.get("review_desc"), res.get("matched_name"),
                             res.get("localized_name"), res.get("name_lang"),
                             res.get("genres"))
            done += 1
            await emit(EVT_PROGRESS, {
                "app_name": it["app_name"],
                "positive_pct": (res or {}).get("positive_pct"),
                "total_reviews": (res or {}).get("total_reviews"),
                "review_desc": (res or {}).get("review_desc"),
                "localized_name": (res or {}).get("localized_name"),
                "genres": (res or {}).get("genres"),
                "done": done,
                "total": len(todo),
            })
        await emit(EVT_DONE, {"ok": True, "refreshed": len(todo)})
        return {"ok": True, "refreshed": len(todo)}

    # -- localized description ----------------------------------------------
    def _cached_appid(self, app_name: str) -> Optional[int]:
        with self._conn() as c:
            row = c.execute("SELECT steam_appid FROM reviews WHERE app_name=?", (app_name,)).fetchone()
        return row[0] if row and row[0] else None

    def _store_description(self, appid: int, lang: str) -> Optional[str]:
        import requests

        self._throttle()
        try:
            r = requests.get(
                "https://store.steampowered.com/api/appdetails",
                params={"appids": appid, "l": lang, "filters": "basic"},
                timeout=15,
            )
            d = (r.json() or {}).get(str(appid)) or {}
            if not d.get("success"):
                return None
            return (d.get("data") or {}).get("short_description") or None
        except Exception as e:
            _log.warning("Steam appdetails failed for %s: %r", appid, e)
            return None

    def _localized_name(self, title: str, lang: str, appid: int) -> Optional[str]:
        """Steam's localized display name for a game (store search names ARE
        localized, unlike appdetails). Match the known appid; fall back to the
        most relevant result."""
        import requests

        self._throttle()
        try:
            r = requests.get(STORE_SEARCH, params={"term": title, "cc": "us", "l": lang}, timeout=15)
            items = r.json().get("items") or []
        except Exception as e:
            _log.warning("Steam name lookup failed for %r: %r", title, e)
            return None
        for it in items:
            if it.get("id") == appid:
                return it.get("name")
        return items[0].get("name") if items else None

    async def description(self, app_name: str, title: str, lang: str = "tchinese") -> Optional[dict]:
        """Best-effort short description AND localized display name from Steam in
        the requested language. Reuses the cached Steam appid; resolves one if we
        don't have it yet. Steam returns localized text when available and falls
        back to the store default (usually English) for the same request."""
        import asyncio

        lang = lang or "english"

        def _do() -> Optional[dict]:
            appid = self._cached_appid(app_name)
            if not appid:
                appid, _ = self._resolve_appid(title)
            if not appid:
                return None
            desc = self._store_description(appid, lang)
            name = self._localized_name(title, lang, appid)
            if not desc and not name:
                return None
            return {"steam_appid": appid, "description": desc, "name": name}

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, _do)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
