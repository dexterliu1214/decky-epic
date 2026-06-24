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

export function getCachedScore(appName: string): number | null | undefined {
  return scores[appName];
}
