import { useMemo, useState } from "react";
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
import type { GameSummary, SortMode } from "../types";

function sortGames(
  games: GameSummary[],
  scores: Record<string, number | null>,
  mode: SortMode,
): GameSummary[] {
  const arr = [...games];
  if (mode === "title") {
    arr.sort((a, b) => a.title.localeCompare(b.title));
  } else if (mode === "installed") {
    arr.sort((a, b) => Number(b.installed) - Number(a.installed) || a.title.localeCompare(b.title));
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

export function LibraryPage() {
  const { status: auth, loading: authLoading } = useAuth();
  const { games, scores, loading, error, reload } = useLibrary();
  const { download } = useOps();
  const [sort, setSort] = useState<SortMode>("metacritic");
  const [query, setQuery] = useState("");

  const visible = useMemo(() => {
    const filtered = query
      ? games.filter((g) => g.title.toLowerCase().includes(query.toLowerCase()))
      : games;
    return sortGames(filtered, scores, sort);
  }, [games, scores, sort, query]);

  const loggedIn = auth?.logged_in;

  return (
    <div style={{ marginTop: 40, padding: "0 28px 28px", height: "100%", overflowY: "scroll" }}>
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
