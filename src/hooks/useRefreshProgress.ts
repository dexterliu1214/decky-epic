import { useEffect, useState } from "react";
import { subscribe } from "../api";

interface Progress {
  done: number;
  total: number;
}

/** Tracks the plugin's background metadata refreshes (Steam reviews, Epic
 *  genres) so the library can show the user that data is still being fetched.
 *  Each source clears when its "done" event arrives. */
export function useRefreshProgress() {
  const [steam, setSteam] = useState<Progress | null>(null);
  const [genres, setGenres] = useState<Progress | null>(null);

  useEffect(() => {
    const p = (set: (v: Progress | null) => void) => (e: { done: number; total: number }) =>
      set(e.total > 0 ? { done: e.done, total: e.total } : null);
    const offs = [
      subscribe<{ done: number; total: number }>("epic_steam_progress", p(setSteam)),
      subscribe("epic_steam_done", () => setSteam(null)),
      subscribe<{ done: number; total: number }>("epic_genre_progress", p(setGenres)),
      subscribe("epic_genre_done", () => setGenres(null)),
    ];
    return () => offs.forEach((off) => off());
  }, []);

  return { steam, genres };
}
