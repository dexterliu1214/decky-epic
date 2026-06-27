import { useCallback, useEffect, useState } from "react";
import {
  getCachedScores,
  getCachedSteamReviews,
  listLibrary,
  refreshScores,
  refreshSteamReviews,
  subscribe,
} from "../api";
import { setLibraryCache } from "../state/libraryCache";
import type { GameSummary, SteamReview } from "../types";

export function useLibrary() {
  const [games, setGames] = useState<GameSummary[]>([]);
  const [scores, setScores] = useState<Record<string, number | null>>({});
  const [steamReviews, setSteamReviews] = useState<Record<string, SteamReview>>({});
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

      const cached = await getCachedScores(appNames);
      const map: Record<string, number | null> = {};
      for (const [k, v] of Object.entries(cached)) map[k] = v.metacritic;
      setScores(map);

      setSteamReviews(await getCachedSteamReviews(appNames));

      // Kick throttled background refreshes; both update live via events.
      void refreshScores(items, false);
      void refreshSteamReviews(items, false);
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
    const off = subscribe<{ app_name: string; metacritic: number | null }>(
      "epic_rawg_progress",
      (p) => setScores((prev) => ({ ...prev, [p.app_name]: p.metacritic })),
    );
    return off;
  }, []);

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
    setLibraryCache(games, scores);
  }, [games, scores]);

  return { games, scores, steamReviews, loading, error, reload: load, setGames };
}
