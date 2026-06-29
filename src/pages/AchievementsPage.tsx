import { useEffect, useState } from "react";
import { DialogButton, Focusable, Navigation, ScrollPanelGroup, Spinner } from "@decky/ui";

import { gameAchievements } from "../api";
import { getCachedGame } from "../state/libraryCache";
import { currentAppName, gameRoute } from "../routes";
import type { AchievementsResult } from "../types";

export function AchievementsPage() {
  const appName = currentAppName();
  const game = getCachedGame(appName);
  const [data, setData] = useState<AchievementsResult | null>(null);

  useEffect(() => {
    if (!appName) return;
    let cancelled = false;
    void gameAchievements(appName)
      .then((r) => {
        if (!cancelled) setData(r);
      })
      .catch(() => {
        if (!cancelled) setData({ total: 0, unlocked: 0, achievements: [] });
      });
    return () => {
      cancelled = true;
    };
  }, [appName]);

  if (!appName) {
    return <div style={{ marginTop: 60, padding: 28 }}>No game selected.</div>;
  }

  const title = game?.title ?? appName;

  return (
    // ScrollPanelGroup is Steam's native scroll container — the right stick and
    // focus-driven scrolling both work inside it (a plain div won't scroll).
    <ScrollPanelGroup {...({ focusable: false, style: { height: "100%" } } as any)}>
    <Focusable flow-children="vertical" style={{ marginTop: 40, padding: "0 28px 28px" }}>
      <DialogButton
        style={{ width: 120, marginBottom: 16 }}
        onClick={() => Navigation.Navigate(gameRoute(appName))}
      >
        ← Back
      </DialogButton>

      <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 18 }}>
        <h1 style={{ margin: 0, fontSize: 26 }}>{title}</h1>
        {data && data.total > 0 && (
          <span style={{ opacity: 0.7, fontSize: 15 }}>
            {data.unlocked} / {data.total} achievements
          </span>
        )}
      </div>

      {data == null ? (
        <Spinner />
      ) : data.achievements.length === 0 ? (
        <div style={{ opacity: 0.7 }}>No achievements for this game.</div>
      ) : (
        <Focusable style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {data.achievements.map((a) => (
            <Focusable
              key={a.name}
              onActivate={() => undefined}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 14,
                padding: "10px 14px",
                background: "#1a1d23",
                borderRadius: 8,
                opacity: a.unlocked ? 1 : 0.55,
              }}
            >
              {a.icon ? (
                <img
                  src={a.icon}
                  style={{
                    width: 48,
                    height: 48,
                    borderRadius: 6,
                    flexShrink: 0,
                    filter: a.unlocked ? "none" : "grayscale(1)",
                  }}
                />
              ) : (
                <div style={{ width: 48, height: 48, borderRadius: 6, background: "#2a2e36", flexShrink: 0 }} />
              )}
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 15, fontWeight: 600 }}>
                  {a.hidden ? "Hidden achievement" : a.title}
                </div>
                <div style={{ fontSize: 13, opacity: 0.8 }}>
                  {a.hidden ? "Unlock to reveal." : a.description}
                </div>
                {a.unlocked && a.unlock_date && (
                  <div style={{ fontSize: 12, opacity: 0.6, marginTop: 2 }}>
                    Unlocked {fmtDate(a.unlock_date)}
                  </div>
                )}
              </div>
              <div style={{ textAlign: "right", flexShrink: 0 }}>
                {a.xp != null && <div style={{ fontSize: 13, opacity: 0.8 }}>{a.xp} XP</div>}
                {a.rarity != null && (
                  <div style={{ fontSize: 12, opacity: 0.55 }}>{a.rarity}% have this</div>
                )}
              </div>
            </Focusable>
          ))}
        </Focusable>
      )}
    </Focusable>
    </ScrollPanelGroup>
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
