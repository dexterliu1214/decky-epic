import { useCallback, useEffect, useState } from "react";
import {
  getCachedGenres,
  getCachedSteamReviews,
  listLibrary,
  refreshGenres,
  refreshSteamReviews,
  subscribe,
} from "../api";
import { setLibraryCache } from "../state/libraryCache";
import type { GameSummary, SteamReview } from "../types";

export function useLibrary() {
  const [games, setGames] = useState<GameSummary[]>([]);
  const [steamReviews, setSteamReviews] = useState<Record<string, SteamReview>>({});
  const [genres, setGenres] = useState<Record<string, string[]>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (forceLibrary = false) => {
    setLoading(true);
    setError(null);
    try {
      const lib = await listLibrary(forceLibrary);
      setGames(lib);
      const appNames = lib.map((g) => g.app_name);
      const items = lib.map((g) => ({ app_name: g.app_name, title: g.title }));

      setSteamReviews(await getCachedSteamReviews(appNames));
      setGenres(await getCachedGenres(appNames));

      // Kick throttled background refreshes; all update live via events.
      void refreshSteamReviews(items, false);
      void refreshGenres(items, false);
    } catch (e) {
      setError(`${e}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(false);
  }, [load]);

  useEffect(() => {
    const off = subscribe<{ app_name: string } & SteamReview>(
      "epic_steam_progress",
      (p) =>
        setSteamReviews((prev) => ({
          ...prev,
          [p.app_name]: {
            positive_pct: p.positive_pct,
            total_reviews: p.total_reviews,
            review_desc: p.review_desc,
            localized_name: p.localized_name,
          },
        })),
    );
    return off;
  }, []);

  useEffect(() => {
    const off = subscribe<{ app_name: string; genres: string[] }>(
      "epic_genre_progress",
      (p) => setGenres((prev) => ({ ...prev, [p.app_name]: p.genres || [] })),
    );
    return off;
  }, []);

  useEffect(() => {
    setLibraryCache(games);
  }, [games]);

  return { games, steamReviews, genres, loading, error, reload: load, setGames };
}
