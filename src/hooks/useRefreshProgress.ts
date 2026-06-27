import { useEffect, useState } from "react";
import { subscribe } from "../api";

interface Progress {
  done: number;
  total: number;
}

/** Tracks the plugin's background metadata refreshes (Metacritic + Steam) so the
 *  library can show the user that data is still being fetched. Each source
 *  clears when its "done" event arrives. */
export function useRefreshProgress() {
  const [rawg, setRawg] = useState<Progress | null>(null);
  const [steam, setSteam] = useState<Progress | null>(null);

  useEffect(() => {
    const offs = [
      subscribe<{ done: number; total: number }>("epic_rawg_progress", (p) =>
        setRawg(p.total > 0 ? { done: p.done, total: p.total } : null),
      ),
      subscribe("epic_rawg_done", () => setRawg(null)),
      subscribe<{ done: number; total: number }>("epic_steam_progress", (p) =>
        setSteam(p.total > 0 ? { done: p.done, total: p.total } : null),
      ),
      subscribe("epic_steam_done", () => setSteam(null)),
    ];
    return () => offs.forEach((off) => off());
  }, []);

  return { rawg, steam };
}
