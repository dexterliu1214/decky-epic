"""Async wrapper around legendary's synchronous ``LegendaryCore``.

legendary is a blocking, single-threaded engine and not safe for concurrent use,
so every call is funnelled through one worker thread guarded by an asyncio lock.
The Decky main loop stays responsive while legendary does network / disk work.
"""
from __future__ import annotations

import asyncio
import functools
import html as _html
import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Optional

from . import paths

_log = logging.getLogger("decky-epic.core")

# Persisted library snapshot so opening the library is instant instead of a
# ~10s network round-trip every time. The "installed" flag is re-overlaid live
# from the local installed list, so only purchases/removals need a refresh.
LIBRARY_CACHE_FILE = paths.CACHE_DIR / "library.json"
GENRE_CACHE_FILE = paths.CACHE_DIR / "genres.json"

EPIC_LOGIN_URL = "https://legendary.gl/epiclogin"


def _cover_url(metadata: dict) -> Optional[str]:
    """Pick a Steam-like tall box-art URL from Epic keyImages."""
    images = (metadata or {}).get("keyImages") or []
    by_type = {img.get("type"): img.get("url") for img in images if img.get("url")}
    for t in ("DieselGameBoxTall", "DieselStoreFrontTall", "OfferImageTall",
              "DieselGameBox", "OfferImageWide", "Thumbnail"):
        if by_type.get(t):
            return by_type[t]
    # fall back to the first available image
    return next(iter(by_type.values()), None)


def _wide_url(metadata: dict) -> Optional[str]:
    """Pick a wide/landscape image from Epic keyImages — used for both the Steam
    Hero (big library-page background) and the Header (small landscape capsule).
    Falls back to the square box art when a title has no true wide image."""
    images = (metadata or {}).get("keyImages") or []
    by_type = {img.get("type"): img.get("url") for img in images if img.get("url")}
    for t in ("DieselGameBoxWide", "DieselStoreFrontWide", "OfferImageWide",
              "TakeoverWide", "DieselGameBox"):
        if by_type.get(t):
            return by_type[t]
    return None


def _logo_url(metadata: dict) -> Optional[str]:
    """Pick the transparent game-logo image (shown over the Hero), if any.
    Only ~5% of Epic titles ship one, so there's no fallback — leave the Steam
    Logo slot empty rather than stuffing it with non-transparent box art."""
    images = (metadata or {}).get("keyImages") or []
    by_type = {img.get("type"): img.get("url") for img in images if img.get("url")}
    for t in ("DieselGameBoxLogo", "OfferImageLogo"):
        if by_type.get(t):
            return by_type[t]
    return None


def _download_b64(url: Optional[str]) -> Optional[dict]:
    """Fetch an image URL and return {b64, type} (jpg/png), or None on failure."""
    if not url:
        return None
    try:
        import base64
        import requests
        r = requests.get(url, timeout=20)
        r.raise_for_status()
    except Exception:
        return None
    ctype = (r.headers.get("Content-Type") or "").lower()
    img_type = "png" if ("png" in ctype or url.lower().endswith(".png")) else "jpg"
    return {"b64": base64.b64encode(r.content).decode("ascii"), "type": img_type}


def _supports_cloud_saves(metadata: dict) -> bool:
    ca = (metadata or {}).get("customAttributes") or {}
    return bool(ca.get("CloudSaveFolder", {}).get("value"))


def _is_game(summary: dict) -> bool:
    """True for actual games. Epic libraries also carry Unreal Engine assets,
    plugins, add-ons, and software — those lack the "games" category path."""
    return "games" in (summary.get("categories") or [])


# Map our settings' Steam-style language codes to Epic catalog locale codes, so
# game titles and descriptions come back localized straight from Epic.
_EPIC_LOCALE = {
    "english": "en",
    "tchinese": "zh-Hant",
    "schinese": "zh-Hans",
    "japanese": "ja",
    "koreana": "ko",
    "french": "fr",
    "german": "de",
    "spanish": "es-ES",
    "italian": "it",
    "portuguese": "pt-BR",
    "russian": "ru",
    "thai": "th",
}


def epic_locale(steam_lang: str) -> str:
    return _EPIC_LOCALE.get(steam_lang or "english", "en")


# Epic Store front-end APIs — the real, localized synopsis lives here, not in the
# entitlement catalog (whose `description` is just the title for most games).
# Resolve the product slug from the namespace, then fetch the localized content.
_STORE_GRAPHQL = "https://store.epicgames.com/graphql"
_STORE_CONTENT = "https://store-content.ak.epicgames.com/api/{locale}/content/products/{slug}"
_SLUG_QUERY = ('query($ns:String!){Catalog{catalogNs(namespace:$ns){'
              'mappings(pageType:"productHome"){pageSlug}}}}')
# The official store synopsis, localized: the catalogOffers `description` is the
# exact marketing copy shown on store.epicgames.com. We pull the namespace's
# offers and prefer the BASE_GAME one (add-ons describe only the DLC).
_OFFER_DESC_QUERY = ('query($ns:String!,$loc:String){Catalog{catalogOffers(namespace:$ns,locale:$loc,'
                     'params:{count:20}){elements{title description longDescription offerType}}}}')
# Epic Store offer tags. Beyond genres (Action, RPG) these include thematic tags
# like Roguelike, Open World, Souls-like, etc. We pull several offers per
# namespace and union their tags, since a single offer (e.g. a special edition)
# can carry a thinner set.
_TAGS_QUERY = ('query($ns:String!,$loc:String){Catalog{catalogOffers(namespace:$ns,locale:$loc,'
               'params:{count:20}){elements{tags{name groupName}}}}}')
# Bumped when the set of tags we extract changes, so old cache entries (e.g. the
# previous genre-only data, or English tags from before localization) are
# treated as stale and re-fetched automatically.
_TAG_CACHE_VERSION = 3
# Tag groups that aren't descriptive of the game itself — dropped from the filter.
_TAG_GROUP_DENYLIST = {
    "platform", "epicfeature", "subscription", "ageratingsystem",
    # age-rating boards
    "usk", "esrb", "pegi", "oflc", "grac", "cero", "rars", "classind", "dejus",
}
# Epic catalog locale -> Epic Store content locale.
_STORE_LOCALE = {
    "en": "en-US", "zh-Hant": "zh-Hant", "zh-Hans": "zh-CN", "ja": "ja", "ko": "ko",
    "fr": "fr", "de": "de", "es-ES": "es-ES", "it": "it", "pt-BR": "pt-BR",
    "ru": "ru", "th": "th",
}


def _strip_markup(text: Optional[str]) -> str:
    """Plain-text a synopsis: drop legendary's longDescription markers, HTML
    tags, markdown heading hashes, and collapse blank lines."""
    t = re.sub(r"<!--.*?-->", "", text or "", flags=re.S)
    t = re.sub(r"<[^>]+>", "", t)
    t = re.sub(r"(?m)^#{1,6}\s*", "", t)  # markdown headings
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def _md_inline(s: str) -> str:
    """Inline markdown -> HTML on escaped text (so stray ``<`` can't inject):
    images, links, inline code, bold and italic."""
    s = _html.escape(s)
    # Images (![alt](url)) before links, since they share the [..](..) shape.
    s = re.sub(r"!\[([^\]]*)\]\((https?://[^)\s]+)\)",
               r'<img src="\2" alt="\1" style="max-width:100%;border-radius:8px" />', s)
    s = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2">\1</a>', s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"__(.+?)__", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<em>\1</em>", s)
    s = re.sub(r"(?<!_)_(?!_)(.+?)(?<!_)_(?!_)", r"<em>\1</em>", s)
    return s


def _md_to_html(t: str) -> str:
    """Convert standard markdown block syntax to HTML: ATX headings (``#``..
    ``######``), unordered (``-``/``*``/``+``) and ordered (``1.``) lists,
    blockquotes (``>``), horizontal rules, and blank-line-separated paragraphs.
    Inline formatting is applied per line via :func:`_md_inline`."""
    out: list = []
    para: list = []
    items: list = []        # pending list items
    list_tag = ""           # "ul" or "ol" for the pending list
    quote: list = []        # pending blockquote lines

    def flush_para():
        if para:
            out.append("<p>" + "<br>".join(_md_inline(x) for x in para) + "</p>")
            para.clear()

    def flush_list():
        nonlocal list_tag
        if items:
            out.append(f"<{list_tag}>" + "".join(f"<li>{_md_inline(x)}</li>" for x in items)
                       + f"</{list_tag}>")
            items.clear()
            list_tag = ""

    def flush_quote():
        if quote:
            out.append("<blockquote>" + "<br>".join(_md_inline(x) for x in quote) + "</blockquote>")
            quote.clear()

    def flush_all():
        flush_para(); flush_list(); flush_quote()

    for raw in t.split("\n"):
        line = raw.strip()
        if not line:
            flush_all(); continue
        if re.match(r"^(-{3,}|\*{3,}|_{3,})$", line):           # horizontal rule
            flush_all(); out.append("<hr />")
        elif m := re.match(r"^(#{1,6})\s+(.*)$", line):         # heading
            flush_all()
            lvl = min(len(m.group(1)) + 1, 6)                   # # -> h2, ## -> h3, ...
            out.append(f"<h{lvl}>{_md_inline(m.group(2))}</h{lvl}>")
        elif m := re.match(r"^>\s?(.*)$", line):                # blockquote
            flush_para(); flush_list()
            quote.append(m.group(1))
        elif m := re.match(r"^[-*+]\s+(.*)$", line):            # unordered list
            flush_para(); flush_quote()
            if list_tag != "ul":
                flush_list(); list_tag = "ul"
            items.append(m.group(1))
        elif m := re.match(r"^\d+\.\s+(.*)$", line):            # ordered list
            flush_para(); flush_quote()
            if list_tag != "ol":
                flush_list(); list_tag = "ol"
            items.append(m.group(1))
        else:                                                  # paragraph text
            flush_list(); flush_quote()
            para.append(line)
    flush_all()
    return "".join(out)


def _long_description_html(text: Optional[str]) -> str:
    """Normalize Epic's long description to HTML for direct rendering. Epic ships
    it in two flavours: real HTML (passed through untouched) and a marker/markdown
    dialect (``<!--textBlock-->``, ``# heading``, ``- bullet``) which we convert
    so it renders properly instead of showing literal ``#`` and run-together lines."""
    t = (text or "").strip()
    if not t:
        return ""
    has_markers = "<!--" in t
    has_md = bool(re.search(r"(?m)^\s*(#{1,6}\s|[-*+]\s|>\s|\d+\.\s)", t)) or "![" in t
    has_real_html = bool(re.search(r"</?(p|div|ul|ol|li|h[1-6]|strong|em|br|span|a|img)\b", t, re.I))
    # Genuine HTML that isn't Epic's marker dialect: render as-is.
    if has_real_html and not has_markers and not has_md:
        return t
    return _md_to_html(re.sub(r"<!--.*?-->", "", t, flags=re.S))


class EpicCore:
    def __init__(self) -> None:
        paths.apply_legendary_env()
        # Imported lazily, AFTER the config env var is set, and after vendored
        # deps are on sys.path (Decky adds py_modules automatically).
        from legendary.core import LegendaryCore
        from .legendary_lock import apply_installed_json_locking
        apply_installed_json_locking()  # cross-process-safe installed.json writes

        self._core = LegendaryCore()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="legendary")
        self._lock = asyncio.Lock()
        self._locale = "en"  # Epic catalog locale for titles/descriptions
        self._slug_cache: dict[str, Optional[str]] = {}  # namespace -> store slug

    def set_locale(self, steam_lang: str) -> None:
        """Point legendary's Epic catalog queries at the user's language so the
        library's titles and descriptions come back localized."""
        loc = epic_locale(steam_lang)
        self._locale = loc
        # Epic wants language and country separately (e.g. zh-Hant / US).
        self._core.language_code = loc
        self._core.egs.language_code = loc

    @property
    def core(self):  # exposed for download/launch/saves services
        return self._core

    @property
    def executor(self) -> ThreadPoolExecutor:
        return self._executor

    @property
    def lock(self) -> asyncio.Lock:
        return self._lock

    async def run(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        loop = asyncio.get_running_loop()
        async with self._lock:
            return await loop.run_in_executor(
                self._executor, functools.partial(fn, *args, **kwargs)
            )

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    # -- auth ----------------------------------------------------------------
    @staticmethod
    def login_url() -> str:
        return EPIC_LOGIN_URL

    def _display_name(self) -> Optional[str]:
        ud = self._core.lgd.userdata
        return ud.get("displayName") if ud else None

    async def auth_status(self) -> dict:
        def _status() -> dict:
            if not self._core.lgd.userdata:
                return {"logged_in": False, "user": None}
            ok = False
            try:
                ok = self._core.login()
            except Exception as e:  # offline / expired
                _log.warning("login refresh failed: %r", e)
            return {"logged_in": bool(ok), "user": self._display_name()}

        return await self.run(_status)

    async def finish_auth(self, pasted: str) -> dict:
        def _do() -> dict:
            code = _extract_auth_code(pasted)
            if not code:
                return {"ok": False, "error": "No authorization code found in input."}
            try:
                ok = self._core.auth_code(code)
            except Exception as e:
                return {"ok": False, "error": f"{e}"}
            if ok:
                try:
                    self._core.login()
                except Exception as e:
                    _log.warning("post-auth login failed: %r", e)
            return {"ok": bool(ok), "user": self._display_name()}

        return await self.run(_do)

    async def logout(self) -> dict:
        def _do() -> dict:
            self._core.lgd.invalidate_userdata()
            return {"ok": True}

        return await self.run(_do)

    # -- library -------------------------------------------------------------
    def _game_summary(self, game) -> dict:
        md = getattr(game, "metadata", {}) or {}
        return {
            "app_name": game.app_name,
            "title": game.app_title,
            "cover": _cover_url(md),
            "cloud_saves": _supports_cloud_saves(md),
            "categories": [c.get("path") for c in (md.get("categories") or [])],
        }

    def _fetch_library_blocking(self, force_meta: bool = False) -> list[dict]:
        try:
            self._core.login()
        except Exception as e:
            _log.warning("login during library fetch failed: %r", e)
        # force_meta re-pulls every game's catalog metadata so titles and
        # descriptions come back in the current locale (16-way parallel inside
        # legendary, ~15s for the whole library).
        games = self._core.get_game_and_dlc_list(update_assets=True, force_refresh=force_meta)[0]
        installed = {ig.app_name for ig in self._core.get_installed_list()}
        out = []
        for g in games:
            s = self._game_summary(g)
            s["installed"] = g.app_name in installed
            out.append(s)
        return out

    def _overlay_installed_blocking(self, games: list[dict]) -> list[dict]:
        try:
            installed = {ig.app_name for ig in self._core.get_installed_list()}
            for g in games:
                g["installed"] = g["app_name"] in installed
        except Exception as e:
            _log.warning("installed overlay failed: %r", e)
        return games

    @staticmethod
    def _read_library_cache() -> Optional[dict]:
        try:
            with open(LIBRARY_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def _write_library_cache(self, games: list[dict]) -> None:
        try:
            tmp = LIBRARY_CACHE_FILE.with_suffix(".json.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"ts": time.time(), "locale": self._locale, "games": games}, f)
            tmp.replace(LIBRARY_CACHE_FILE)
        except Exception as e:
            _log.warning("could not write library cache: %r", e)

    async def library(self, force_refresh: bool = False) -> list[dict]:
        cached = self._read_library_cache()
        # A cache written under a different locale carries wrong-language titles;
        # treat it as a miss so we re-pull localized metadata from Epic.
        locale_changed = bool(cached) and cached.get("locale") != self._locale
        if not force_refresh and cached and not locale_changed:
            games = await self.run(self._overlay_installed_blocking, cached.get("games") or [])
            return [g for g in games if _is_game(g)]
        # force_meta re-pulls each game's catalog metadata so titles come back in
        # the current locale — needed on a manual refresh or a locale change,
        # since legendary otherwise serves the metadata it cached on first sync.
        games = await self.run(self._fetch_library_blocking, force_refresh or locale_changed)
        self._write_library_cache(games)
        return [g for g in games if _is_game(g)]

    async def installed(self) -> list[dict]:
        def _list() -> list[dict]:
            out = []
            for ig in self._core.get_installed_list():
                out.append({
                    "app_name": ig.app_name,
                    "title": ig.title,
                    "version": ig.version,
                    "install_path": ig.install_path,
                    "install_size": ig.install_size,
                })
            return out

        return await self.run(_list)

    async def steam_launch_info(self, app_name: str) -> dict:
        """Resolve what the frontend needs to create a non-Steam shortcut for
        this game (so it shows in Game Mode via gamescope). The frontend handles
        AddShortcut / compat tool / RunGame."""
        def _info() -> dict:
            import os
            ig = self._core.get_installed_game(app_name)
            if not ig:
                return {"ok": False, "error": "Game is not installed."}
            exe = os.path.join(ig.install_path, ig.executable)
            cover = None
            try:
                g = self._core.get_game(app_name)
                cover = _cover_url(getattr(g, "metadata", {}) or {})
            except Exception as e:
                _log.warning("cover lookup failed for %s: %r", app_name, e)
            # Host-side cloud-save wrapper: pulls before launch, pushes after
            # exit, resolving saves against Steam's actual Proton prefix.
            wrapper = paths.PLUGIN_DIR / "py_modules" / "epic" / "steam_save_wrapper.sh"
            launch_options = f'bash "{wrapper}" {app_name} %command%'
            return {
                "ok": True,
                "app_name": app_name,
                "name": ig.title,          # display name only; no ".exe"
                "exe": exe,
                "start_dir": ig.install_path,
                "cover": cover,
                "launch_options": launch_options,
            }

        return await self.run(_info)

    async def update_status(self, app_name: str) -> dict:
        """Whether an installed game has a newer build on Epic. Refreshes the
        asset list (light) and compares build versions via legendary."""
        def _u() -> dict:
            ig = self._core.get_installed_game(app_name)
            if not ig:
                return {"installed": False, "update_available": False}
            try:
                latest = self._core.is_latest(app_name)
                return {"installed": True, "update_available": not latest, "version": ig.version}
            except Exception as e:
                _log.warning("update check failed for %s: %r", app_name, e)
                return {"installed": True, "update_available": False, "error": f"{e}"}

        return await self.run(_u)

    def _catalog_text(self, ns: str, cid: str, locale: str) -> tuple:
        """(title, description) from Epic's catalog at a specific locale. Swaps
        the egs locale just for this call — safe because all core work runs on a
        single locked executor."""
        prev = self._core.egs.language_code
        self._core.egs.language_code = locale
        try:
            info = self._core.egs.get_game_info(ns, cid, timeout=10.0) or {}
            return info.get("title"), info.get("description")
        except Exception as e:
            _log.warning("catalog fetch (%s) failed: %r", locale, e)
            return None, None
        finally:
            self._core.egs.language_code = prev

    def _store_slug(self, namespace: str) -> Optional[str]:
        """Resolve a game's Epic Store product slug from its namespace (cached)."""
        if namespace in self._slug_cache:
            return self._slug_cache[namespace]
        slug = None
        try:
            r = self._core.egs.session.get(
                _STORE_GRAPHQL,
                params={"query": _SLUG_QUERY, "variables": json.dumps({"ns": namespace})},
                timeout=10,
            )
            maps = (((r.json().get("data") or {}).get("Catalog") or {}).get("catalogNs") or {}).get("mappings") or []
            slug = maps[0].get("pageSlug") if maps else None
        except Exception as e:
            _log.warning("store slug lookup failed for %s: %r", namespace, e)
        self._slug_cache[namespace] = slug
        return slug

    def _store_description(self, slug: str, store_locale: str) -> Optional[str]:
        """Localized synopsis from the Epic Store content API for a product slug."""
        try:
            r = self._core.egs.session.get(
                _STORE_CONTENT.format(locale=store_locale, slug=slug), timeout=10)
            if r.status_code != 200:
                return None
            pages = r.json().get("pages") or []
            if not pages:
                return None
            about = (pages[0].get("data") or {}).get("about") or {}
            return _strip_markup(about.get("shortDescription") or about.get("description")) or None
        except Exception as e:
            _log.warning("store content fetch failed (%s/%s): %r", store_locale, slug, e)
            return None

    def _store_offer(self, namespace: str, store_locale: str) -> tuple:
        """The official store copy from catalogOffers, localized: a (short
        synopsis, raw long description) pair. The short synopsis is plain-texted;
        the long description keeps its original markup (it may contain HTML) so
        the UI can render it as-is. Prefer the BASE_GAME offer; fall back to the
        first offer that has a short description."""
        try:
            r = self._core.egs.session.get(
                _STORE_GRAPHQL,
                params={"query": _OFFER_DESC_QUERY,
                        "variables": json.dumps({"ns": namespace, "loc": store_locale})},
                timeout=10,
            )
            els = (((r.json().get("data") or {}).get("Catalog") or {})
                   .get("catalogOffers") or {}).get("elements") or []
            base = next((e for e in els if e.get("offerType") == "BASE_GAME"
                         and (e.get("description") or "").strip()), None)
            chosen = base or next((e for e in els if (e.get("description") or "").strip()), None)
            if not chosen:
                return "", ""
            short = _strip_markup(chosen.get("description")) or ""
            long_raw = (chosen.get("longDescription") or "").strip()
            return short, long_raw
        except Exception as e:
            _log.warning("store offer fetch failed (%s/%s): %r", store_locale, namespace, e)
            return "", ""

    async def description(self, app_name: str) -> dict:
        """Localized title + synopsis, entirely from Epic. The synopsis is taken
        from the Epic Store front-end (store.epicgames.com) so the detail page
        shows the real marketing copy users see on the store, localized with an
        English fallback. The catalog synopsis / longDescription are only used as
        fallbacks when the store has nothing. The title still comes from the
        catalog (its localized title)."""
        def _real(d: Optional[str], title: str) -> bool:
            d = (d or "").strip()
            return bool(d) and d.lower() != title.strip().lower()

        def _d() -> dict:
            try:
                g = self._core.get_game(app_name)
                md = getattr(g, "metadata", {}) or {}
            except Exception:
                return {"title": app_name, "description": ""}
            title = md.get("title") or app_name
            ns, cid = md.get("namespace"), md.get("id")

            # Localized title (and a catalog synopsis kept only as a fallback).
            catalog_desc = ""
            if ns and cid:
                loc_title, loc_desc = self._catalog_text(ns, cid, self._locale)
                title = loc_title or title
                if _real(loc_desc, title):
                    catalog_desc = loc_desc.strip()

            # Primary synopsis: the official Epic Store copy (catalogOffers),
            # localized with an English fallback. Also grab the raw long
            # description (kept as-is — it may contain HTML the UI renders).
            desc = ""
            long_desc = ""
            if ns:
                store_loc = _STORE_LOCALE.get(self._locale, "en-US")
                desc, long_desc = self._store_offer(ns, store_loc)
                if not desc and not long_desc and store_loc != "en-US":
                    desc, long_desc = self._store_offer(ns, "en-US")

            # Secondary: the store-content product page (older API), if the
            # storefront offers had no description.
            if not desc and ns:
                slug = self._store_slug(ns)
                if slug:
                    store_loc = _STORE_LOCALE.get(self._locale, "en-US")
                    desc = self._store_description(slug, store_loc) or ""
                    if not desc and store_loc != "en-US":
                        desc = self._store_description(slug, "en-US") or ""

            # Fallbacks: localized catalog synopsis, English catalog, longDescription.
            if not desc:
                desc = catalog_desc
            if not desc and ns and cid and self._locale != "en":
                en_title, en_desc = self._catalog_text(ns, cid, "en")
                if _real(en_desc, en_title or title):
                    desc = en_desc.strip()
            if not desc:
                desc = _strip_markup(md.get("longDescription"))

            # Long description for the detail page: prefer the store's, else the
            # catalog metadata's. Normalize to HTML — pass real HTML through, but
            # convert Epic's marker/markdown dialect so it renders properly.
            if not long_desc:
                long_desc = md.get("longDescription") or ""

            return {"title": title, "description": desc,
                    "long_description": _long_description_html(long_desc)}

        return await self.run(_d)

    # -- achievements --------------------------------------------------------
    def _achievements_blocking(self, app_name: str) -> dict:
        """Epic achievements for a game: the localized catalog list merged with
        the signed-in user's unlock progress. Catalog text comes back in the
        current locale (egs.language_code); the per-user record needs a login."""
        empty = {"total": 0, "unlocked": 0, "achievements": []}
        try:
            g = self._core.get_game(app_name)
            ns = (getattr(g, "metadata", {}) or {}).get("namespace")
        except Exception:
            ns = None
        if not ns:
            return empty

        try:
            data = self._core.egs.get_game_achievements(ns) or {}
            rec = (((data.get("data") or {}).get("Achievement") or {})
                   .get("productAchievementsRecordBySandbox") or {})
        except Exception as e:
            _log.warning("achievements fetch failed for %s: %r", app_name, e)
            return empty
        catalog = rec.get("achievements") or []
        if not catalog:
            return empty

        # The user's unlock state, keyed by the internal achievement name. Best
        # effort: a logged-out / data-less response just leaves everything locked.
        progress: dict = {}
        try:
            udata = self._core.egs.get_game_achievements_user(ns) or {}
            records = ((((udata.get("data") or {}).get("PlayerAchievement") or {})
                        .get("playerAchievementGameRecordsBySandbox") or {}).get("records") or [])
            for r in records:
                for pa in (r.get("playerAchievements") or []):
                    p = pa.get("playerAchievement") or {}
                    name = p.get("achievementName")
                    if name:
                        progress[name] = p
        except Exception as e:
            _log.warning("user achievements fetch failed for %s: %r", app_name, e)

        out = []
        for item in catalog:
            ac = item.get("achievement") or {}
            name = ac.get("name")
            p = progress.get(name) or {}
            unlocked = bool(p.get("unlocked"))
            # Hidden achievements stay masked until the user unlocks them.
            masked = bool(ac.get("hidden")) and not unlocked
            out.append({
                "name": name,
                "unlocked": unlocked,
                "hidden": masked,
                "title": ac.get("unlockedDisplayName") or "",
                "description": "" if masked else (ac.get("unlockedDescription") or ""),
                "icon": (ac.get("unlockedIconLink") if unlocked else ac.get("lockedIconLink"))
                         or ac.get("unlockedIconLink"),
                "xp": ac.get("XP"),
                "rarity": (ac.get("rarity") or {}).get("percent"),
                "unlock_date": p.get("unlockDate"),
            })
        # Unlocked first, then rarest-to-commonest so the showcase reads well.
        out.sort(key=lambda a: (not a["unlocked"], a["rarity"] if a["rarity"] is not None else 101))
        return {
            "total": rec.get("totalAchievements") or len(out),
            "unlocked": sum(1 for a in out if a["unlocked"]),
            "achievements": out,
        }

    async def achievements(self, app_name: str) -> dict:
        return await self.run(self._achievements_blocking, app_name)

    # -- tags (Epic Store offer tags) ----------------------------------------
    def _epic_genres(self, namespace: str) -> list:
        """Descriptive tag names from the Epic Store offers — genres plus thematic
        tags like Roguelike or Open World. Platform/rating/Epic-feature groups are
        dropped, and tags are unioned across all of the namespace's offers."""
        try:
            store_loc = _STORE_LOCALE.get(self._locale, "en-US")
            r = self._core.egs.session.get(
                _STORE_GRAPHQL,
                params={"query": _TAGS_QUERY,
                        "variables": json.dumps({"ns": namespace, "loc": store_loc})},
                timeout=10,
            )
            els = (((r.json().get("data") or {}).get("Catalog") or {}).get("catalogOffers") or {}).get("elements") or []
            names = set()
            for el in els:
                for t in el.get("tags") or []:
                    name = t.get("name")
                    grp = (t.get("groupName") or "").lower()
                    if name and grp not in _TAG_GROUP_DENYLIST:
                        names.add(name)
            return sorted(names)
        except Exception as e:
            _log.warning("epic tags failed for %s: %r", namespace, e)
            return []

    def _genres_for_app(self, app_name: str) -> list:
        try:
            g = self._core.get_game(app_name)
            ns = (getattr(g, "metadata", {}) or {}).get("namespace")
        except Exception:
            ns = None
        return self._epic_genres(ns) if ns else []

    @staticmethod
    def _read_genre_cache() -> dict:
        try:
            with open(GENRE_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    @staticmethod
    def _write_genre_cache(data: dict) -> None:
        try:
            tmp = GENRE_CACHE_FILE.with_suffix(".json.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f)
            tmp.replace(GENRE_CACHE_FILE)
        except Exception as e:
            _log.warning("could not write genre cache: %r", e)

    def cached_genres(self, app_names: list) -> dict:
        cache = self._read_genre_cache()
        return {a: (cache.get(a) or {}).get("genres", []) for a in app_names if a in cache}

    async def refresh_genres(self, items: list, emit, force: bool = False) -> dict:
        """Fetch missing/stale Epic genres for each game (namespace -> Store offer
        tags), caching to genres.json and emitting progress. Each lookup runs as
        its own locked executor task so it interleaves with other core work."""
        cache = self._read_genre_cache()
        ttl = 30 * 86400  # genres rarely change
        now = time.time()
        todo = [it for it in items
                if force or it["app_name"] not in cache
                or cache[it["app_name"]].get("v") != _TAG_CACHE_VERSION
                or cache[it["app_name"]].get("loc") != self._locale
                or (now - (cache[it["app_name"]].get("fetched_at") or 0) > ttl)]
        done = 0
        for it in todo:
            app = it["app_name"]
            genres = await self.run(self._genres_for_app, app)
            cache[app] = {"genres": genres, "fetched_at": time.time(),
                          "v": _TAG_CACHE_VERSION, "loc": self._locale}
            done += 1
            if done % 20 == 0:
                self._write_genre_cache(cache)
            await emit("epic_genre_progress",
                       {"app_name": app, "genres": genres, "done": done, "total": len(todo)})
        if todo:
            self._write_genre_cache(cache)
        await emit("epic_genre_done", {"ok": True, "refreshed": len(todo)})
        return {"ok": True, "refreshed": len(todo)}

    async def artwork_b64(self, app_name: str) -> dict:
        """Download the game's Epic art, base64-encoded, so the frontend can set
        every Steam shortcut artwork (no CORS): portrait Capsule, wide Hero
        background, landscape Header, and the transparent Logo when one exists.
        Hero and Header share the same wide image (downloaded once)."""
        def _fetch() -> dict:
            try:
                g = self._core.get_game(app_name)
                md = getattr(g, "metadata", {}) or {}
            except Exception as e:
                return {"ok": False, "error": f"{e}"}
            cover = _download_b64(_cover_url(md))
            wide = _download_b64(_wide_url(md))   # Hero + Header
            logo = _download_b64(_logo_url(md))
            if not any((cover, wide, logo)):
                return {"ok": False, "error": "No artwork available."}
            return {"ok": True, "cover": cover, "hero": wide, "header": wide, "logo": logo}

        return await self.run(_fetch)


def _extract_auth_code(pasted: str) -> str:
    """Accept either the raw authorization code or the JSON blob Epic shows
    (``{"authorizationCode":"...", ...}``) and return the code."""
    text = (pasted or "").strip()
    if not text:
        return ""
    if text.startswith("{"):
        try:
            data = json.loads(text)
            return str(data.get("authorizationCode") or data.get("code") or "").strip()
        except Exception:
            return ""
    return text
