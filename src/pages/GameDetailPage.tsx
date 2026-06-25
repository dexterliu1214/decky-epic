import { useCallback, useEffect, useState } from "react";
import { DialogButton, Focusable, Navigation, Spinner } from "@decky/ui";
import { toaster } from "@decky/api";
import { FaCloud, FaCloudDownloadAlt, FaCloudUploadAlt, FaPlay, FaStop, FaTrash } from "react-icons/fa";

import { DownloadProgress } from "../components/DownloadProgress";
import { MetacriticBadge } from "../components/MetacriticBadge";
import { RawgAttribution } from "../components/RawgAttribution";
import {
  cancelDownload,
  savesStatus,
  startDownload,
  steamLaunchInfo,
  syncSaves,
  uninstallGame,
} from "../api";
import { launchAppViaSteam, removeShortcutForApp, terminateSteamGame, watchGameLifetime } from "../steam";
import { useOps } from "../hooks/useOps";
import { getCachedGame, getCachedScore } from "../state/libraryCache";
import { currentAppName, LIBRARY_ROUTE } from "../routes";
import type { SavesStatus } from "../types";

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

  // Refresh installed/saves when a download or game run finishes.
  useEffect(() => {
    if (download?.app_name === appName && download.state === "done") {
      setInstalled(true);
      void loadSaves();
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

  const title = game?.title ?? appName;

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
        void removeShortcutForApp(appName, info?.exe);
      } else toaster.toast({ title: "Uninstall failed", body: res.error || "" });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ marginTop: 40, padding: "0 28px 28px", height: "100%", overflowY: "scroll" }}>
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
            {installed && (
              <DialogButton disabled={busy} onClick={doUninstall} style={{ width: 180 }}>
                <FaTrash /> &nbsp;Uninstall
              </DialogButton>
            )}
          </Focusable>
        </div>
      </Focusable>

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
    </div>
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
