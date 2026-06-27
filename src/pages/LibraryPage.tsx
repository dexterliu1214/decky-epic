import { useEffect, useMemo, useRef, useState } from "react";
import { DialogButton, Focusable, Navigation, Spinner, TextField } from "@decky/ui";
import { FaCog, FaSyncAlt } from "react-icons/fa";

import { GameCard } from "../components/GameCard";
import { SortControl } from "../components/SortControl";
import { DownloadProgress } from "../components/DownloadProgress";
import { RawgAttribution } from "../components/RawgAttribution";
import { useAuth } from "../hooks/useAuth";
import { useLibrary } from "../hooks/useLibrary";
import { useOps } from "../hooks/useOps";
import { gameRoute, SETTINGS_ROUTE } from "../routes";
import type { GameSummary, SortMode, SteamReview } from "../types";

// Wilson lower bound of the positive ratio: balances how positive a game is
// against how many reviews back that up, so a 100%-from-8-reviews game doesn't
// outrank a 99%-from-20k one. Returns -1 when there are no usable reviews.
function steamRank(r?: SteamReview): number {
  const n = r?.total_reviews ?? 0;
  if (r?.positive_pct == null || n <= 0) return -1;
  const p = r.positive_pct / 100;
  const z = 1.96;
  const denom = 1 + (z * z) / n;
  const center = p + (z * z) / (2 * n);
  const margin = z * Math.sqrt((p * (1 - p) + (z * z) / (4 * n)) / n);
  return (center - margin) / denom;
}

function sortGames(
  games: GameSummary[],
  scores: Record<string, number | null>,
  steamReviews: Record<string, SteamReview>,
  mode: SortMode,
): GameSummary[] {
  const arr = [...games];
  if (mode === "title") {
    arr.sort((a, b) => a.title.localeCompare(b.title));
  } else if (mode === "installed") {
    arr.sort((a, b) => Number(b.installed) - Number(a.installed) || a.title.localeCompare(b.title));
  } else if (mode === "steam") {
    arr.sort((a, b) => {
      const va = steamRank(steamReviews[a.app_name]);
      const vb = steamRank(steamReviews[b.app_name]);
      return vb - va || a.title.localeCompare(b.title);
    });
  } else {
    arr.sort((a, b) => {
      const sa = scores[a.app_name];
      const sb = scores[b.app_name];
      const va = sa == null ? -1 : sa;
      const vb = sb == null ? -1 : sb;
      return vb - va || a.title.localeCompare(b.title);
    });
  }
  return arr;
}

// Module-level so they survive the page unmounting when you open a game's detail
// page and navigate back — restoring scroll, sort, and search instead of resetting.
let savedScrollTop = 0;
let savedSort: SortMode = "metacritic";
let savedQuery = "";

export function LibraryPage() {
  const { status: auth, loading: authLoading } = useAuth();
  const { games, scores, steamReviews, loading, error, reload } = useLibrary();
  const { download } = useOps();
  const [sort, setSort] = useState<SortMode>(savedSort);
  const [query, setQuery] = useState(savedQuery);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Persist sort + search across navigation.
  useEffect(() => {
    savedSort = sort;
    savedQuery = query;
  }, [sort, query]);

  // Restore the saved scroll position once the grid has rendered. Cards are a
  // fixed size, so the layout height is stable even before cover images load.
  useEffect(() => {
    if (loading || savedScrollTop <= 0) return;
    const el = scrollRef.current;
    if (!el) return;
    const id = requestAnimationFrame(() => {
      el.scrollTop = savedScrollTop;
    });
    return () => cancelAnimationFrame(id);
  }, [loading]);

  const visible = useMemo(() => {
    const filtered = query
      ? games.filter((g) => g.title.toLowerCase().includes(query.toLowerCase()))
      : games;
    return sortGames(filtered, scores, steamReviews, sort);
  }, [games, scores, steamReviews, sort, query]);

  const loggedIn = auth?.logged_in;

  return (
    <div
      ref={scrollRef}
      onScroll={(e) => {
        savedScrollTop = e.currentTarget.scrollTop;
      }}
      style={{ marginTop: 40, padding: "0 28px 28px", height: "100%", overflowY: "scroll" }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 14 }}>
        <h1 style={{ margin: 0, fontSize: 26 }}>Epic Library</h1>
        <div style={{ flex: 1 }} />
        <DialogButton
          style={{ width: 46, minWidth: 46, padding: 8 }}
          onClick={() => reload(true)}
        >
          <FaSyncAlt />
        </DialogButton>
        <DialogButton
          style={{ width: 46, minWidth: 46, padding: 8 }}
          onClick={() => Navigation.Navigate(SETTINGS_ROUTE)}
        >
          <FaCog />
        </DialogButton>
      </div>

      {!authLoading && !loggedIn && (
        <div style={{ padding: 24, background: "#1a1d23", borderRadius: 8, marginBottom: 16 }}>
          <p style={{ marginTop: 0 }}>You are not signed in to Epic Games.</p>
          <DialogButton onClick={() => Navigation.Navigate(SETTINGS_ROUTE)}>
            Sign in
          </DialogButton>
        </div>
      )}

      {download && download.state === "downloading" && (
        <div style={{ marginBottom: 16 }}>
          <DownloadProgress status={download} />
        </div>
      )}

      <Focusable style={{ display: "flex", gap: 12, alignItems: "center", marginBottom: 16 }}>
        <div style={{ flex: 1 }}>
          <TextField
            label="Search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <SortControl value={sort} onChange={setSort} />
      </Focusable>

      {error && <div style={{ color: "#f87171", marginBottom: 12 }}>Error: {error}</div>}

      {loading ? (
        <div style={{ display: "flex", justifyContent: "center", padding: 40 }}>
          <Spinner />
        </div>
      ) : (
        <Focusable
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))",
            gap: 16,
          }}
        >
          {visible.map((g) => (
            <GameCard
              key={g.app_name}
              game={g}
              score={scores[g.app_name]}
              steamReview={steamReviews[g.app_name]}
              onActivate={() => Navigation.Navigate(gameRoute(g.app_name))}
            />
          ))}
        </Focusable>
      )}

      {!loading && visible.length === 0 && loggedIn && (
        <div style={{ opacity: 0.7, padding: 24 }}>No games found.</div>
      )}

      <RawgAttribution />
    </div>
  );
}
