import { useCallback, useEffect, useRef, useState } from "react";
import { DialogButton, Focusable, Navigation, Spinner } from "@decky/ui";
import { toaster } from "@decky/api";
import { FaCloud, FaCloudDownloadAlt, FaCloudUploadAlt, FaDownload, FaPlay, FaStop, FaThumbsUp, FaTrash } from "react-icons/fa";

import { DownloadProgress } from "../components/DownloadProgress";
import { MetacriticBadge } from "../components/MetacriticBadge";
import { RawgAttribution } from "../components/RawgAttribution";
import {
  cancelDownload,
  checkUpdate,
  gameDescription,
  getCachedSteamReviews,
  savesStatus,
  startDownload,
  steamLaunchInfo,
  syncSaves,
  uninstallGame,
} from "../api";
import { launchAppViaSteam, removeShortcutForApp, terminateSteamGame, watchGameLifetime } from "../steam";
import { useOps } from "../hooks/useOps";
import { getCachedGame, getCachedScore, setCachedInstalled } from "../state/libraryCache";
import { currentAppName, LIBRARY_ROUTE } from "../routes";
import type { SavesStatus, SteamReview } from "../types";

// Steam's review tiers, colour-coded the way the store does (blue = positive).
function steamColor(pct: number): string {
  if (pct >= 80) return "#66c0f4";
  if (pct >= 40) return "#b9a074";
  return "#a34c25";
}

const LAUNCH_LABEL: Record<string, string> = {
  syncing_down: "Syncing cloud save…",
  launching: "Launching…",
  running: "Running",
  syncing_up: "Saving to cloud…",
  exited: "Exited",
  error: "Error",
};

export function GameDetailPage() {
  const appName = currentAppName();
  const game = getCachedGame(appName);
  const score = getCachedScore(appName);
  const { download, launch } = useOps();

  const [installed, setInstalled] = useState<boolean>(game?.installed ?? false);
  const [saves, setSaves] = useState<SavesStatus | null>(null);
  const [busy, setBusy] = useState(false);
  // Game Mode launches go through Steam (a non-Steam shortcut), so running state
  // comes from Steam's app-lifetime notifications, not backend events.
  const [steamAppid, setSteamAppid] = useState<number | null>(null);
  const [steamRunning, setSteamRunning] = useState(false);
  const [steamReview, setSteamReview] = useState<SteamReview | null>(null);
  const [description, setDescription] = useState<string | null>(null);
  const [localizedName, setLocalizedName] = useState<string | null>(null);
  const [updateAvailable, setUpdateAvailable] = useState(false);

  // Check for a newer Epic build whenever the game is installed.
  useEffect(() => {
    if (!appName || !installed) {
      setUpdateAvailable(false);
      return;
    }
    void checkUpdate(appName)
      .then((r) => setUpdateAvailable(!!r.update_available))
      .catch(() => undefined);
  }, [appName, installed]);

  // Pull the cached Steam review (populated by the library's background refresh).
  useEffect(() => {
    if (!appName) return;
    void getCachedSteamReviews([appName])
      .then((m) => setSteamReview(m[appName] ?? null))
      .catch(() => undefined);
  }, [appName]);

  // Fetch the synopsis + localized name (preferred-language, from Steam).
  useEffect(() => {
    if (!appName) return;
    void gameDescription(appName)
      .then((r) => {
        setDescription(r.ok ? r.description ?? null : null);
        setLocalizedName(r.ok ? r.name ?? null : null);
      })
      .catch(() => undefined);
  }, [appName]);

  const isThisDownloading =
    download?.app_name === appName && download.state === "downloading";
  const launchState = launch?.app_name === appName ? launch.state : undefined;
  const isRunningThis = steamRunning || busy;

  const loadSaves = useCallback(async () => {
    if (!installed || !game?.cloud_saves) return;
    try {
      setSaves(await savesStatus(appName));
    } catch (e) {
      setSaves({ supported: false, error: `${e}` });
    }
  }, [appName, installed, game?.cloud_saves]);

  useEffect(() => {
    void loadSaves();
  }, [loadSaves]);

  // Mark installed + refresh saves when a download finishes — but only ONCE per
  // completion. The op state lingers at "done", and loadSaves (a dep) is rebuilt
  // whenever `installed` changes, so without this guard a later setInstalled(false)
  // (uninstall) would re-trigger this effect and immediately flip it back to true.
  const downloadDoneHandled = useRef(false);
  useEffect(() => {
    const done = download?.app_name === appName && download.state === "done";
    if (done && !downloadDoneHandled.current) {
      downloadDoneHandled.current = true;
      setInstalled(true);
      void loadSaves();
      // A finished download/update may have brought the game up to date.
      void checkUpdate(appName)
        .then((r) => setUpdateAvailable(!!r.update_available))
        .catch(() => undefined);
    } else if (!done) {
      downloadDoneHandled.current = false;
    }
  }, [download, appName, loadSaves]);

  useEffect(() => {
    if (launch?.app_name === appName && (launch.state === "exited")) {
      void loadSaves();
    }
  }, [launch, appName, loadSaves]);

  // Track the Steam-launched game's start/exit; refresh saves when it exits.
  useEffect(() => {
    if (steamAppid == null) return;
    const off = watchGameLifetime((running) => {
      setSteamRunning(running);
      if (!running) void loadSaves();
    });
    return off;
  }, [steamAppid, loadSaves]);

  if (!appName) {
    return <div style={{ marginTop: 60, padding: 28 }}>No game selected.</div>;
  }

  // Prefer the Steam localized name (in the user's chosen language) over Epic's.
  const title = localizedName ?? game?.title ?? appName;

  const doInstall = async () => {
    setBusy(true);
    try {
      const res = await startDownload(appName, "", 0);
      if (!res.ok) toaster.toast({ title: "Install failed", body: res.error || "" });
    } finally {
      setBusy(false);
    }
  };

  const doPlay = async () => {
    setBusy(true);
    try {
      const appid = await launchAppViaSteam(appName);
      if (appid == null) {
        toaster.toast({ title: "Launch failed", body: "Could not resolve the game executable." });
        return;
      }
      setSteamAppid(appid);
      setSteamRunning(true);
    } catch (e) {
      toaster.toast({ title: "Launch failed", body: `${e}` });
    } finally {
      setBusy(false);
    }
  };

  const doStop = () => {
    if (steamAppid != null) terminateSteamGame(steamAppid);
  };

  const doSync = async (direction: "both" | "pull" | "push", up = false, down = false) => {
    setBusy(true);
    try {
      const res = await syncSaves(appName, direction, up, down);
      if (res.ok === false) toaster.toast({ title: "Sync issue", body: res.error || "" });
      else
        toaster.toast({
          title: "Cloud save",
          body: res.action ? `Action: ${res.action}` : "Up to date",
        });
      await loadSaves();
    } finally {
      setBusy(false);
    }
  };

  const doUninstall = async () => {
    setBusy(true);
    try {
      // Resolve the exe while still installed so we can drop the Steam shortcut.
      const info = await steamLaunchInfo(appName).catch(() => null);
      const res = await uninstallGame(appName);
      if (res.ok) {
        setInstalled(false);
        setSaves(null);
        setSteamAppid(null);
        setCachedInstalled(appName, false); // keep the grid / re-opened detail in sync
        void removeShortcutForApp(appName, info?.exe);
        toaster.toast({ title: "Uninstalled", body: title });
      } else toaster.toast({ title: "Uninstall failed", body: res.error || "" });
    } catch (e) {
      // Never leave the button silently dead — surface the failure.
      toaster.toast({ title: "Uninstall failed", body: `${e}` });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Focusable
      // A Focusable scroll container lets the controller scroll the whole page,
      // not just hop between the focusable rows (a plain div won't scroll).
      flow-children="vertical"
      style={{ marginTop: 40, padding: "0 28px 28px", height: "100%", overflowY: "scroll" }}
    >
      <DialogButton
        style={{ width: 120, marginBottom: 16 }}
        onClick={() => Navigation.Navigate(LIBRARY_ROUTE)}
      >
        ← Library
      </DialogButton>

      <Focusable style={{ display: "flex", gap: 20 }}>
        {game?.cover && (
          <img
            src={game.cover}
            style={{ width: 200, borderRadius: 8, alignSelf: "flex-start", boxShadow: "0 4px 12px rgba(0,0,0,0.5)" }}
          />
        )}
        <div style={{ flex: 1 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <h1 style={{ margin: 0, fontSize: 28 }}>{title}</h1>
            <MetacriticBadge score={score} size={34} />
          </div>
          {steamReview?.positive_pct != null && (
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 8 }}>
              <FaThumbsUp style={{ color: steamColor(steamReview.positive_pct) }} />
              <span style={{ color: steamColor(steamReview.positive_pct), fontWeight: 600 }}>
                {steamReview.review_desc}
              </span>
              <span style={{ opacity: 0.7, fontSize: 14 }}>
                {steamReview.positive_pct}% positive
                {steamReview.total_reviews ? ` · ${steamReview.total_reviews.toLocaleString()} reviews` : ""}
              </span>
            </div>
          )}
          {game?.cloud_saves && (
            <div style={{ display: "flex", alignItems: "center", gap: 6, opacity: 0.8, marginTop: 6 }}>
              <FaCloud /> Cloud saves supported
            </div>
          )}

          {launchState && (
            <div style={{ marginTop: 12, opacity: 0.9 }}>{LAUNCH_LABEL[launchState] || launchState}</div>
          )}

          {/* Primary actions */}
          <Focusable style={{ display: "flex", gap: 12, marginTop: 18, flexWrap: "wrap" }}>
            {!installed && !isThisDownloading && (
              <DialogButton disabled={busy} onClick={doInstall} style={{ width: 180 }}>
                Install
              </DialogButton>
            )}
            {isThisDownloading && (
              <DialogButton onClick={() => cancelDownload(appName)} style={{ width: 180 }}>
                Cancel download
              </DialogButton>
            )}
            {installed && !isRunningThis && (
              <DialogButton disabled={busy} onClick={doPlay} style={{ width: 180 }}>
                <FaPlay /> &nbsp;Play
              </DialogButton>
            )}
            {isRunningThis && (
              <DialogButton disabled={steamAppid == null} onClick={doStop} style={{ width: 180 }}>
                <FaStop /> &nbsp;Stop
              </DialogButton>
            )}
            {installed && updateAvailable && !isThisDownloading && (
              <DialogButton disabled={busy} onClick={doInstall} style={{ width: 180 }}>
                <FaDownload /> &nbsp;Update
              </DialogButton>
            )}
            {installed && (
              <DialogButton disabled={busy} onClick={doUninstall} style={{ width: 180 }}>
                <FaTrash /> &nbsp;Uninstall
              </DialogButton>
            )}
          </Focusable>
          {installed && updateAvailable && (
            <div style={{ marginTop: 8, color: "#fbbf24", fontSize: 13 }}>
              An update is available.
            </div>
          )}
        </div>
      </Focusable>

      {description && (
        <Focusable
          onActivate={() => undefined}
          style={{ marginTop: 22, fontSize: 15, lineHeight: 1.6, opacity: 0.9, maxWidth: 900 }}
        >
          {description}
        </Focusable>
      )}

      {isThisDownloading && (
        <div style={{ marginTop: 20 }}>
          <DownloadProgress status={download!} />
        </div>
      )}

      {/* Cloud saves panel */}
      {installed && game?.cloud_saves && (
        <div style={{ marginTop: 28, padding: 18, background: "#1a1d23", borderRadius: 8 }}>
          <h2 style={{ marginTop: 0, fontSize: 20 }}>Cloud Saves</h2>
          {saves == null ? (
            <Spinner />
          ) : saves.supported === false ? (
            <div style={{ opacity: 0.7 }}>{saves.error || "Not supported."}</div>
          ) : saves.needs_path ? (
            <div style={{ color: "#fbbf24" }}>{saves.error}</div>
          ) : (
            <>
              <div style={{ display: "flex", gap: 24, fontSize: 14, opacity: 0.85 }}>
                <span>Status: {saves.status || "unknown"}</span>
                <span>Local: {fmtDate(saves.local_dt)}</span>
                <span>Cloud: {fmtDate(saves.remote_dt)}</span>
              </div>
              <Focusable style={{ display: "flex", gap: 12, marginTop: 14, flexWrap: "wrap" }}>
                <DialogButton disabled={busy} onClick={() => doSync("both")} style={{ width: 170 }}>
                  Sync now
                </DialogButton>
                <DialogButton disabled={busy} onClick={() => doSync("pull", false, true)} style={{ width: 200 }}>
                  <FaCloudDownloadAlt /> &nbsp;Force download
                </DialogButton>
                <DialogButton disabled={busy} onClick={() => doSync("push", true, false)} style={{ width: 200 }}>
                  <FaCloudUploadAlt /> &nbsp;Force upload
                </DialogButton>
              </Focusable>
            </>
          )}
        </div>
      )}

      <RawgAttribution />
    </Focusable>
  );
}

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}
