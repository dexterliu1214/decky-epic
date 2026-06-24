import { callable, addEventListener, removeEventListener } from "@decky/api";
import type {
  AuthStatus,
  DownloadStatus,
  GameSummary,
  InstalledGame,
  PluginSettings,
  ProtonBuild,
  SavesStatus,
  ScoreEntry,
} from "./types";

// --- health ----------------------------------------------------------------
export const ping = callable<[], string>("ping");
export const backendStatus = callable<[], { ready: boolean; error: string | null }>("backend_status");

// --- auth ------------------------------------------------------------------
export const authLoginUrl = callable<[], string>("auth_login_url");
export const authStatus = callable<[], AuthStatus>("auth_status");
export const authFinish = callable<[string], { ok: boolean; user?: string | null; error?: string }>("auth_finish");
export const authLogout = callable<[], { ok: boolean; error?: string }>("auth_logout");

// --- library ---------------------------------------------------------------
export const listLibrary = callable<[boolean], GameSummary[]>("list_library");
export const listInstalled = callable<[], InstalledGame[]>("list_installed");

// --- metacritic ------------------------------------------------------------
export const getCachedScores = callable<[string[]], Record<string, ScoreEntry>>("get_cached_scores");
export const refreshScores =
  callable<[{ app_name: string; title: string }[], boolean], { ok: boolean; refreshed?: number; error?: string }>(
    "refresh_scores",
  );

// --- downloads -------------------------------------------------------------
export const startDownload =
  callable<[string, string, number], { ok: boolean; error?: string }>("start_download");
export const cancelDownload = callable<[string], { ok: boolean; error?: string }>("cancel_download");
export const downloadStatus = callable<[], DownloadStatus | null>("download_status");
export const uninstallGame = callable<[string], { ok: boolean; error?: string }>("uninstall_game");

// --- launch + saves --------------------------------------------------------
export const launchGame = callable<[string], { ok: boolean; pid?: number; error?: string }>("launch_game");
export const stopGame = callable<[], { ok: boolean; error?: string }>("stop_game");
export const isRunning = callable<[], { running: boolean; app_name: string | null }>("is_running");
export const syncSaves =
  callable<[string, string, boolean, boolean], SavesStatus>("sync_saves");
export const savesStatus = callable<[string], SavesStatus>("saves_status");

// --- settings --------------------------------------------------------------
export const getSettings = callable<[], PluginSettings>("get_settings");
export const setSettings = callable<[Partial<PluginSettings>], PluginSettings>("set_settings");
export const listProtonBuilds = callable<[], ProtonBuild[]>("list_proton_builds");

// --- events ----------------------------------------------------------------
export type EventName =
  | "epic_download_progress"
  | "epic_download_state"
  | "epic_launch_state"
  | "epic_saves_status"
  | "epic_rawg_progress"
  | "epic_rawg_done";

/** Subscribe to a backend event; returns an unsubscribe fn. */
export function subscribe<T = any>(event: EventName, cb: (payload: T) => void): () => void {
  const handler = (payload: T) => cb(payload);
  addEventListener(event, handler as any);
  return () => removeEventListener(event, handler as any);
}
