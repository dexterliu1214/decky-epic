import { ProgressBarWithInfo } from "@decky/ui";
import type { DownloadStatus } from "../types";
import { formatBytes, formatEta, formatSpeed } from "../util/format";

export function DownloadProgress({ status }: { status: DownloadStatus }) {
  const pct = Math.round(status.progress);
  return (
    <div style={{ width: "100%" }}>
      <ProgressBarWithInfo
        nProgress={status.progress}
        sOperationText={status.title || status.app_name}
        nTransitionSec={1}
      />
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, opacity: 0.8, marginTop: 4 }}>
        <span>{pct}%</span>
        <span>{formatSpeed(status.download_speed)}</span>
        <span>
          {formatBytes(status.downloaded_bytes)} / {formatBytes(status.dl_total_bytes)}
        </span>
        <span>ETA {formatEta(status.eta_seconds)}</span>
      </div>
    </div>
  );
}
