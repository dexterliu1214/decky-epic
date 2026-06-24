import { Focusable } from "@decky/ui";
import { FaCloud, FaDownload } from "react-icons/fa";
import type { GameSummary } from "../types";
import { MetacriticBadge } from "./MetacriticBadge";

export function GameCard({
  game,
  score,
  onActivate,
  width = 150,
}: {
  game: GameSummary;
  score: number | null | undefined;
  onActivate: () => void;
  width?: number;
}) {
  const height = Math.round(width * 1.33);
  return (
    <Focusable
      onActivate={onActivate}
      onOKButton={onActivate}
      style={{
        width,
        borderRadius: 6,
        overflow: "hidden",
        position: "relative",
        background: "#1a1d23",
        boxShadow: "0 2px 8px rgba(0,0,0,0.4)",
      }}
    >
      <div style={{ width, height, position: "relative" }}>
        {game.cover ? (
          <img
            src={game.cover}
            style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }}
          />
        ) : (
          <div
            style={{
              width: "100%",
              height: "100%",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              padding: 8,
              textAlign: "center",
              fontSize: 13,
            }}
          >
            {game.title}
          </div>
        )}
        <div style={{ position: "absolute", top: 6, left: 6 }}>
          <MetacriticBadge score={score} />
        </div>
        <div style={{ position: "absolute", top: 6, right: 6, display: "flex", gap: 4 }}>
          {game.installed && <FaDownload size={14} title="Installed" />}
          {game.cloud_saves && <FaCloud size={14} title="Cloud saves supported" />}
        </div>
      </div>
      <div
        style={{
          padding: "4px 6px",
          fontSize: 12,
          whiteSpace: "nowrap",
          overflow: "hidden",
          textOverflow: "ellipsis",
        }}
        title={game.title}
      >
        {game.title}
      </div>
    </Focusable>
  );
}
