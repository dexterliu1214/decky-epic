import { useEffect, useState } from "react";
import { DialogButton, Dropdown, Field, Focusable, Navigation, TextField } from "@decky/ui";
import { toaster } from "@decky/api";

import { AuthDialog } from "../components/AuthDialog";
import { listProtonBuilds } from "../api";
import { useAuth } from "../hooks/useAuth";
import { useSettings } from "../hooks/useSettings";
import { LIBRARY_ROUTE } from "../routes";
import type { ProtonBuild } from "../types";

export function SettingsPage() {
  const { status, finish, logout, refresh } = useAuth();
  const { settings, save } = useSettings();
  const [submitting, setSubmitting] = useState(false);
  const [protons, setProtons] = useState<ProtonBuild[]>([]);
  const [rawgKey, setRawgKey] = useState("");
  const [installPath, setInstallPath] = useState("");

  useEffect(() => {
    void listProtonBuilds().then(setProtons);
  }, []);

  useEffect(() => {
    if (settings) {
      setRawgKey(settings.rawg_api_key || "");
      setInstallPath(settings.install_base_path || "");
    }
  }, [settings]);

  const onAuth = async (code: string) => {
    setSubmitting(true);
    try {
      const res = await finish(code);
      if (res.ok) toaster.toast({ title: "Signed in", body: res.user || "" });
      else toaster.toast({ title: "Sign-in failed", body: res.error || "" });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div style={{ marginTop: 40, padding: "0 28px 28px", height: "100%", overflowY: "scroll" }}>
      <DialogButton style={{ width: 120, marginBottom: 16 }} onClick={() => Navigation.Navigate(LIBRARY_ROUTE)}>
        ← Library
      </DialogButton>
      <h1 style={{ marginTop: 0 }}>Settings</h1>

      <section style={{ marginBottom: 28 }}>
        <h2 style={{ fontSize: 20 }}>Epic Account</h2>
        {status?.logged_in ? (
          <Focusable style={{ display: "flex", gap: 12, alignItems: "center" }}>
            <span>Signed in as <b>{status.user}</b></span>
            <DialogButton style={{ width: 140 }} onClick={() => logout()}>Sign out</DialogButton>
          </Focusable>
        ) : (
          <AuthDialog
            onSubmit={onAuth}
            submitting={submitting}
            onSuccess={() => {
              toaster.toast({ title: "Signed in", body: "Epic account linked from your phone" });
              void refresh();
            }}
          />
        )}
      </section>

      <section style={{ marginBottom: 28 }}>
        <h2 style={{ fontSize: 20 }}>Metacritic (RAWG)</h2>
        <TextField
          label="RAWG API key"
          value={rawgKey}
          onChange={(e) => setRawgKey(e.target.value)}
        />
        <div style={{ fontSize: 12, opacity: 0.7, margin: "4px 0 8px" }}>
          Get a free key at rawg.io/apidocs. Required for critic scores &amp; sorting.
        </div>
        <DialogButton style={{ width: 160 }} onClick={() => save({ rawg_api_key: rawgKey.trim() })}>
          Save key
        </DialogButton>
      </section>

      <section style={{ marginBottom: 28 }}>
        <h2 style={{ fontSize: 20 }}>Install location</h2>
        <TextField label="Base install path" value={installPath} onChange={(e) => setInstallPath(e.target.value)} />
        <DialogButton style={{ width: 160, marginTop: 8 }} onClick={() => save({ install_base_path: installPath.trim() })}>
          Save path
        </DialogButton>
      </section>

      <section style={{ marginBottom: 28 }}>
        <h2 style={{ fontSize: 20 }}>Proton</h2>
        {protons.length === 0 ? (
          <div style={{ opacity: 0.7 }}>No Proton builds found. Install Proton / GE-Proton via Steam.</div>
        ) : (
          <Field label="Preferred Proton build">
            <Dropdown
              rgOptions={[
                { data: "", label: "Auto (newest)" },
                ...protons.map((p) => ({ data: p.name, label: p.name })),
              ]}
              selectedOption={settings?.preferred_proton ?? ""}
              onChange={(o) => save({ preferred_proton: o.data as string })}
            />
          </Field>
        )}
      </section>
    </div>
  );
}
