export const LIBRARY_ROUTE = "/decky-epic/library";
export const GAME_ROUTE = "/decky-epic/game";
export const ACHIEVEMENTS_ROUTE = "/decky-epic/achievements";
export const SETTINGS_ROUTE = "/decky-epic/settings";

// App name is passed as a query param so the route matches on pathname only
// (no react-router param dependency).
export const gameRoute = (appName: string) =>
  `${GAME_ROUTE}?app=${encodeURIComponent(appName)}`;

export const achievementsRoute = (appName: string) =>
  `${ACHIEVEMENTS_ROUTE}?app=${encodeURIComponent(appName)}`;

export function currentAppName(): string {
  try {
    return new URLSearchParams(window.location.search).get("app") || "";
  } catch {
    return "";
  }
}
