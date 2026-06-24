import { useEffect, useState } from "react";
import { DialogButton, Field, Focusable, TextField } from "@decky/ui";
import { authLoginUrl } from "../api";

export function AuthDialog({
  onSubmit,
  submitting,
}: {
  onSubmit: (code: string) => void | Promise<void>;
  submitting: boolean;
}) {
  const [url, setUrl] = useState<string>("");
  const [code, setCode] = useState<string>("");

  useEffect(() => {
    void authLoginUrl().then(setUrl);
  }, []);

  return (
    <Focusable style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <Field label="1. Open this URL in a browser and sign in:" focusable={false}>
        <code style={{ fontSize: 13, wordBreak: "break-all" }}>{url || "…"}</code>
      </Field>
      <div style={{ fontSize: 13, opacity: 0.75 }}>
        After signing in you'll see a JSON blob containing an{" "}
        <code>authorizationCode</code>. Paste it (or the whole JSON) below.
      </div>
      <TextField
        label="2. Authorization code"
        value={code}
        onChange={(e) => setCode(e.target.value)}
      />
      <DialogButton
        disabled={submitting || !code.trim()}
        onClick={() => onSubmit(code.trim())}
        style={{ width: 180 }}
      >
        {submitting ? "Signing in…" : "Sign in"}
      </DialogButton>
    </Focusable>
  );
}
