import type { GameSummary } from "../types";

// Lightweight in-memory cache so the detail page can render instantly after
// navigation without re-fetching the whole library.
let games: GameSummary[] = [];
let scores: Record<string, number | null> = {};

export function setLibraryCache(g: GameSummary[], s: Record<string, number | null>) {
  games = g;
  scores = s;
}

export function getCachedGame(appName: string): GameSummary | undefined {
  return games.find((g) => g.app_name === appName);
}

/** Patch one game's installed flag in the cache so the library grid and a
 *  re-opened detail page reflect an install/uninstall without a full refetch. */
export function setCachedInstalled(appName: string, installed: boolean) {
  const g = games.find((x) => x.app_name === appName);
  if (g) g.installed = installed;
}

export function getCachedScore(appName: string): number | null | undefined {
  return scores[appName];
}
