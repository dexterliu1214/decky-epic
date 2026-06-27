import { useEffect, useRef, type CSSProperties } from "react";
import { Focusable } from "@decky/ui";
import { FaCloud, FaDownload, FaThumbsUp } from "react-icons/fa";
import type { GameSummary, SteamReview } from "../types";
import { MetacriticBadge } from "./MetacriticBadge";

// Steam's review tiers, colour-coded the way the store does (blue = positive).
function steamColor(pct: number): string {
  if (pct >= 80) return "#66c0f4"; // positive (Steam blue)
  if (pct >= 40) return "#b9a074"; // mixed
  return "#a34c25"; // negative
}

// Dark rounded backing so the white/blue icons stay legible on light covers.
const badgeStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  width: 20,
  height: 20,
  borderRadius: 5,
  background: "rgba(0,0,0,0.65)",
  color: "#fff",
};

export function GameCard({
  game,
  score,
  steamReview,
  onActivate,
  onFocus,
  autoFocus = false,
  width = 150,
}: {
  game: GameSummary;
  score: number | null | undefined;
  steamReview?: SteamReview;
  onActivate: () => void;
  onFocus?: () => void;
  autoFocus?: boolean;
  width?: number;
}) {
  const steamPct = steamReview?.positive_pct;
  const height = Math.round(width * 1.33);
  const ref = useRef<HTMLDivElement>(null);

  // Restore gamepad focus to the card the user came back from (also scrolls it
  // into view). Runs once on mount for the single card flagged by the parent.
  useEffect(() => {
    if (autoFocus) ref.current?.focus();
  }, [autoFocus]);

  return (
    <Focusable
      ref={ref}
      onActivate={onActivate}
      onOKButton={onActivate}
      onFocus={onFocus}
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
        <div style={{ position: "absolute", top: 6, left: 6, display: "flex", flexDirection: "column", gap: 4 }}>
          <MetacriticBadge score={score} />
          {steamPct != null && (
            <span
              style={{
                ...badgeStyle,
                width: "auto",
                padding: "0 6px",
                gap: 4,
                fontSize: 11,
                fontWeight: 600,
                color: steamColor(steamPct),
              }}
              title={`Steam: ${steamReview?.review_desc || ""}${
                steamReview?.total_reviews ? ` (${steamReview.total_reviews.toLocaleString()})` : ""
              }`}
            >
              <FaThumbsUp size={10} /> {steamPct}%
            </span>
          )}
        </div>
        <div style={{ position: "absolute", top: 6, right: 6, display: "flex", gap: 4 }}>
          {game.installed && (
            <span style={badgeStyle} title="Installed">
              <FaDownload size={12} />
            </span>
          )}
          {game.cloud_saves && (
            <span style={{ ...badgeStyle, color: "#4aa3ff" }} title="Cloud saves supported">
              <FaCloud size={12} />
            </span>
          )}
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
