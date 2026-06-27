// Launching Epic games in Game Mode requires going through Steam: a process we
// spawn directly with `proton run` creates a window gamescope never shows
// (gamescope only displays the app Steam is focused on). So we register the game
// as a non-Steam shortcut, assign a Proton compat tool, and RunGame it — then
// gamescope shows it with full Game Mode integration.
//
// SteamClient is an ambient global provided by @decky/ui's type declarations.

import { artworkB64, getSettings, getShortcutId, removeShortcutId, setShortcutId, steamLaunchInfo } from "./api";

export interface SteamLaunchSpec {
  appName: string;
  name: string;
  exe: string;
  startDir: string;
  launchOptions: string;
  /** Preferred Proton display name (from plugin settings), best-effort match. */
  preferredProton?: string;
}

const NONSTEAM_APP_TYPE = 1073741824; // 1 << 30, the non-Steam shortcut bit
// ELibraryAssetType slots (see @decky/ui App.d.ts).
const ASSET_CAPSULE = 0; // portrait library cover
const ASSET_HERO = 1; // big library-page background
const ASSET_LOGO = 2; // transparent logo overlaid on the hero
const ASSET_HEADER = 3; // landscape capsule (friends / recent strip)

/** Set every Steam shortcut artwork from the game's Epic art (best-effort). */
async function applyCoverArt(appid: number, appName: string): Promise<void> {
  try {
    const art = await artworkB64(appName);
    if (!art.ok) return;
    const slots: [typeof art.cover, number][] = [
      [art.cover, ASSET_CAPSULE],
      [art.hero, ASSET_HERO],
      [art.header, ASSET_HEADER],
      [art.logo, ASSET_LOGO],
    ];
    for (const [img, slot] of slots) {
      if (img?.b64) {
        await SteamClient.Apps.SetCustomArtworkForApp(appid, img.b64, img.type || "jpg", slot);
      }
    }
  } catch {
    /* artwork is best-effort; never block the launch on it */
  }
}

/** Does Steam still know about this shortcut appid? */
function shortcutExists(appid: number): boolean {
  try {
    return !!(window as any).appStore?.GetAppOverviewByAppID?.(appid);
  } catch {
    return false;
  }
}

/** Find an existing non-Steam shortcut whose exe matches, to avoid duplicates. */
function findExistingShortcut(exe: string): number | null {
  const wanted = exe.replace(/^"|"$/g, "");
  try {
    const apps = (window as any).collectionStore?.allAppsCollection?.allApps ?? [];
    for (const a of apps) {
      const ov = a?.appid ? a : a?.overview ?? a;
      const appid = ov?.appid ?? a?.appid;
      if (!appid) continue;
      const isShortcut = (ov?.app_type & NONSTEAM_APP_TYPE) !== 0 || ov?.app_type === NONSTEAM_APP_TYPE;
      if (!isShortcut) continue;
      const exePath = (ov?.shortcut_override ?? ov?.strShortcutExe ?? "").replace(/^"|"$/g, "");
      if (exePath && exePath === wanted) return appid;
    }
  } catch {
    /* store shape varies across Steam builds; fall through to creating one */
  }
  return null;
}

async function pickCompatTool(appid: number, preferred?: string): Promise<string | null> {
  try {
    const tools = await SteamClient.Apps.GetAvailableCompatTools(appid);
    if (!tools?.length) return null;
    const byDisplay = (needle: string) =>
      tools.find((t) => t.strDisplayName?.toLowerCase().includes(needle.toLowerCase()));
    // 1) exact-ish match to the user's preferred Proton; 2) GE-Proton; 3) newest
    // numbered Proton; 4) Experimental; 5) whatever is first.
    const chosen =
      (preferred && byDisplay(preferred)) ||
      byDisplay("ge-proton") ||
      tools
        .filter((t) => /proton\s*\d/i.test(t.strDisplayName || ""))
        .sort((a, b) => (b.strDisplayName || "").localeCompare(a.strDisplayName || "", undefined, { numeric: true }))[0] ||
      byDisplay("experimental") ||
      tools[0];
    return chosen?.strToolName ?? null;
  } catch {
    return null;
  }
}

/** Ensure a shortcut exists + has Proton, and return its 32-bit appid.
 *
 * Reuse is keyed off a persisted app_name -> appid map: relying on scanning the
 * app store by exe was unreliable (Steam stores the exe quoted and the store
 * shape varies), which created a NEW shortcut — and a fresh Proton prefix, so
 * settings/saves reset — on every launch. */
export async function ensureSteamShortcut(spec: SteamLaunchSpec): Promise<number> {
  let appid: number | null = null;
  const stored = (await getShortcutId(spec.appName).catch(() => ({ appid: null }))).appid;
  if (stored != null && shortcutExists(stored)) {
    appid = stored;
  } else {
    appid = findExistingShortcut(spec.exe); // fallback for pre-existing shortcuts
  }

  if (appid == null) {
    appid = await SteamClient.Apps.AddShortcut(spec.name, spec.exe, spec.startDir, spec.launchOptions);
  }
  // AddShortcut's name arg is ignored on some Steam builds (it falls back to the
  // exe basename, e.g. "Backpack Hero.exe"), so always set the name explicitly.
  SteamClient.Apps.SetShortcutName(appid, spec.name);
  SteamClient.Apps.SetShortcutStartDir(appid, spec.startDir);
  SteamClient.Apps.SetShortcutLaunchOptions(appid, spec.launchOptions);
  const tool = await pickCompatTool(appid, spec.preferredProton);
  if (tool) SteamClient.Apps.SpecifyCompatTool(appid, tool);
  // Apply capsule + Hero art every time (not just on create) so pre-existing
  // shortcuts get backfilled. Fire-and-forget: art is best-effort and must not
  // delay the launch.
  void applyCoverArt(appid, spec.appName);
  await setShortcutId(spec.appName, appid).catch(() => undefined); // remember for reuse
  return appid;
}

/** 64-bit gameID for a non-Steam shortcut: appid << 32 | 0x02000000. */
export function shortcutGameId(appid: number): string {
  return ((BigInt(appid) << 32n) | 0x02000000n).toString();
}

export async function launchViaSteam(spec: SteamLaunchSpec): Promise<number> {
  const appid = await ensureSteamShortcut(spec);
  const gameId = shortcutGameId(appid);
  SteamClient.Apps.RunGame(gameId, "", -1, 0);
  return appid;
}

export function terminateSteamGame(appid: number): void {
  SteamClient.Apps.TerminateApp(shortcutGameId(appid), false);
}

/** Build a launch spec from backend info + the user's preferred Proton. */
async function specFor(appName: string): Promise<SteamLaunchSpec | null> {
  const info = await steamLaunchInfo(appName);
  if (!info.ok || !info.exe) return null;
  const settings = await getSettings().catch(() => null);
  return {
    appName,
    name: info.name || appName,
    exe: info.exe,
    startDir: info.start_dir || "",
    launchOptions: info.launch_options || "",
    preferredProton: (settings as any)?.preferred_proton || undefined,
  };
}

/** Register (or refresh) a shortcut for a freshly-installed game, no launch. */
export async function syncShortcutForInstall(appName: string): Promise<number | null> {
  const spec = await specFor(appName);
  if (!spec) return null;
  return ensureSteamShortcut(spec);
}

/** Launch a game in Game Mode, creating/reusing its shortcut as needed. */
export async function launchAppViaSteam(appName: string): Promise<number | null> {
  const spec = await specFor(appName);
  if (!spec) return null;
  return launchViaSteam(spec);
}

/** Remove a game's shortcut (persisted appid first, exe scan as fallback) and
 *  forget the mapping. Pass the exe (resolved BEFORE uninstalling) for fallback. */
export async function removeShortcutForApp(appName: string, exe?: string): Promise<void> {
  const stored = (await getShortcutId(appName).catch(() => ({ appid: null }))).appid;
  let removed = false;
  if (stored != null) {
    try { SteamClient.Apps.RemoveShortcut(stored); removed = true; } catch { /* noop */ }
  }
  if (!removed && exe) {
    const appid = findExistingShortcut(exe);
    if (appid != null) {
      try { SteamClient.Apps.RemoveShortcut(appid); } catch { /* noop */ }
    }
  }
  await removeShortcutId(appName).catch(() => undefined);
}

/**
 * Track start/exit of a launched shortcut. unAppID is unreliable (0) for
 * non-Steam shortcuts, so we latch onto the nInstanceID seen at start and match
 * the later exit by that instance. Returns an unsubscribe fn.
 */
export function watchGameLifetime(onChange: (running: boolean) => void): () => void {
  let instanceId: number | null = null;
  const reg = SteamClient.GameSessions.RegisterForAppLifetimeNotifications((n: any) => {
    if (n.bRunning) {
      if (instanceId == null) instanceId = n.nInstanceID;
      onChange(true);
    } else if (instanceId == null || n.nInstanceID === instanceId) {
      onChange(false);
    }
  });
  return () => {
    try {
      reg.unregister();
    } catch {
      /* noop */
    }
  };
}
