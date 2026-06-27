import {
  ButtonItem,
  PanelSection,
  PanelSectionRow,
  Navigation,
  staticClasses,
} from "@decky/ui";
import { definePlugin, routerHook } from "@decky/api";
import { FaGamepad } from "react-icons/fa";

import { LibraryPage } from "./pages/LibraryPage";
import { GameDetailPage } from "./pages/GameDetailPage";
import { SettingsPage } from "./pages/SettingsPage";
import { GAME_ROUTE, LIBRARY_ROUTE, SETTINGS_ROUTE } from "./routes";
import { subscribe } from "./api";
import { syncShortcutForInstall } from "./steam";
import { useAuth } from "./hooks/useAuth";
import { useOps } from "./hooks/useOps";

function QuickAccessPanel() {
  const { status } = useAuth();
  const { download, launch } = useOps();

  const go = (route: string) => {
    Navigation.CloseSideMenus();
    Navigation.Navigate(route);
  };

  return (
    <>
      <PanelSection title="Epic">
        <PanelSectionRow>
          <div style={{ fontSize: 13, opacity: 0.85 }}>
            {status?.logged_in ? `Signed in as ${status.user}` : "Not signed in"}
          </div>
        </PanelSectionRow>
        {download && download.state === "downloading" && (
          <PanelSectionRow>
            <div style={{ fontSize: 13 }}>
              Downloading {download.title || download.app_name}: {Math.round(download.progress)}%
            </div>
          </PanelSectionRow>
        )}
        {launch && launch.state !== "exited" && (
          <PanelSectionRow>
            <div style={{ fontSize: 13 }}>Game: {launch.state.replace("_", " ")}</div>
          </PanelSectionRow>
        )}
      </PanelSection>
      <PanelSection>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => go(LIBRARY_ROUTE)}>
            Open Library
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => go(SETTINGS_ROUTE)}>
            Settings
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>
    </>
  );
}

export default definePlugin(() => {
  routerHook.addRoute(LIBRARY_ROUTE, () => <LibraryPage />, { exact: true });
  routerHook.addRoute(GAME_ROUTE, () => <GameDetailPage />, { exact: true });
  routerHook.addRoute(SETTINGS_ROUTE, () => <SettingsPage />, { exact: true });

  // Auto-register a Steam shortcut when a game finishes installing, so it shows
  // in the Steam library immediately (and launches in Game Mode). Lives at the
  // plugin level so it fires regardless of whether the QAM panel is open.
  const offInstall = subscribe<{ app_name: string; state: string }>("epic_download_state", (p) => {
    if (p.state === "done" && p.app_name) void syncShortcutForInstall(p.app_name);
  });

  return {
    name: "decky-epic",
    titleView: <div className={staticClasses.Title}>Epic</div>,
    content: <QuickAccessPanel />,
    icon: <FaGamepad />,
    onDismount() {
      offInstall();
      routerHook.removeRoute(LIBRARY_ROUTE);
      routerHook.removeRoute(GAME_ROUTE);
      routerHook.removeRoute(SETTINGS_ROUTE);
    },
  };
});
