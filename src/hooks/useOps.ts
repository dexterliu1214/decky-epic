import { useEffect, useState } from "react";
import { downloadStatus, isRunning, subscribe } from "../api";
import type { DownloadStatus, LaunchStateEvent } from "../types";

/** Live download + launch state, driven by backend events. */
export function useOps() {
  const [download, setDownload] = useState<DownloadStatus | null>(null);
  const [launch, setLaunch] = useState<LaunchStateEvent | null>(null);

  useEffect(() => {
    // Seed from current backend state (covers navigating in mid-operation).
    void downloadStatus().then((d) => d && setDownload(d));
    void isRunning().then((r) => {
      if (r.running && r.app_name) setLaunch({ app_name: r.app_name, state: "running" });
    });

    const offProg = subscribe<DownloadStatus>("epic_download_progress", (p) => setDownload(p));
    const offState = subscribe<DownloadStatus>("epic_download_state", (p) =>
      setDownload((prev) => (prev && prev.app_name === p.app_name ? { ...prev, ...p } : prev ?? (p as DownloadStatus))),
    );
    const offLaunch = subscribe<LaunchStateEvent>("epic_launch_state", (p) => {
      setLaunch(p);
      if (p.state === "exited" || p.state === "error") {
        // clear after a short delay handled by consumer; keep last state here
      }
    });
    return () => {
      offProg();
      offState();
      offLaunch();
    };
  }, []);

  return { download, launch };
}
