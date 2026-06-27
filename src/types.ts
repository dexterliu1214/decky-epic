export interface AuthStatus {
  logged_in: boolean;
  user: string | null;
  error?: string | null;
}

export interface GameSummary {
  app_name: string;
  title: string;
  cover: string | null;
  cloud_saves: boolean;
  categories: string[];
  installed: boolean;
}

export interface InstalledGame {
  app_name: string;
  title: string;
  version: string;
  install_path: string;
  install_size: number;
}

export interface ScoreEntry {
  metacritic: number | null;
  matched_name: string | null;
  fetched_at: number | null;
}

export interface SteamReview {
  positive_pct: number | null;
  total_reviews: number | null;
  review_desc: string | null;
  localized_name?: string | null;
  matched_name?: string | null;
  fetched_at?: number | null;
}

export interface DownloadStatus {
  app_name: string;
  title?: string;
  state: "downloading" | "done" | "cancelled" | "error";
  progress: number;
  download_speed: number;
  dl_total_bytes: number;
  downloaded_bytes: number;
  eta_seconds: number | null;
  current_filename?: string | null;
  error?: string;
}

export interface DownloadStateEvent {
  app_name: string;
  state: "downloading" | "done" | "cancelled" | "error";
  error?: string;
}

export interface LaunchStateEvent {
  app_name: string;
  state: "syncing_down" | "launching" | "running" | "syncing_up" | "exited" | "error";
  pid?: number;
  code?: number;
  error?: string;
}

export interface SavesStatus {
  ok?: boolean;
  supported: boolean;
  status?: "local_newer" | "remote_newer" | "same_age" | "no_save";
  has_remote?: boolean;
  local_dt?: string | null;
  remote_dt?: string | null;
  save_path?: string;
  needs_path?: boolean;
  computed_path?: string;
  error?: string;
  action?: string;
  conflict?: boolean;
}

export interface PluginSettings {
  rawg_api_key: string;
  install_base_path: string;
  preferred_proton: string;
  max_workers: number;
  metacritic_cache_ttl_days: number;
  preferred_language: string;
}

export interface ProtonBuild {
  name: string;
  path: string;
  tool_dir: string;
}

export type SortMode = "metacritic" | "steam" | "title" | "installed";
