import { useEffect, useRef, useState } from "react";
import { DialogButton, Field, Focusable, TextField } from "@decky/ui";
import qrcode from "qrcode-generator";

import { authLoginUrl, authStartPairing, authStopPairing, authStatus } from "../api";

function makeQrDataUrl(text: string): string {
  // Byte mode, medium error correction; type 0 = auto-size for the payload.
  const qr = qrcode(0, "M");
  qr.addData(text);
  qr.make();
  return qr.createDataURL(6, 8); // cellSize, margin -> GIF data URL
}

/**
 * Game-Mode-friendly Epic sign-in. The default path is phone-assisted: the Deck
 * shows a QR pointing at a tiny LAN page served by the backend; the user logs in
 * on their phone and the code is sent back automatically. A collapsible manual
 * paste box remains for desktop mode. ``onSuccess`` fires once the backend
 * reports a logged-in session.
 */
export function AuthDialog({
  onSubmit,
  submitting,
  onSuccess,
}: {
  onSubmit: (code: string) => void | Promise<void>;
  submitting: boolean;
  onSuccess?: () => void;
}) {
  const [pairUrl, setPairUrl] = useState<string>("");
  const [pairErr, setPairErr] = useState<string>("");
  const [qr, setQr] = useState<string>("");
  const [loginUrl, setLoginUrl] = useState<string>("");
  const [code, setCode] = useState<string>("");
  const [showManual, setShowManual] = useState<boolean>(false);
  const succeeded = useRef(false);

  // Start the LAN pairing server and render the QR.
  useEffect(() => {
    let cancelled = false;
    void authStartPairing().then((res) => {
      if (cancelled) return;
      if (res.ok && res.url) {
        setPairUrl(res.url);
        try {
          setQr(makeQrDataUrl(res.url));
        } catch (e) {
          setPairErr(`QR render failed: ${e}`);
        }
      } else {
        setPairErr(res.error || "Could not start phone pairing.");
      }
    });
    void authLoginUrl().then((u) => !cancelled && setLoginUrl(u));
    return () => {
      cancelled = true;
      void authStopPairing();
    };
  }, []);

  // Poll for completion (phone may finish the login for us).
  useEffect(() => {
    const id = setInterval(async () => {
      const s = await authStatus();
      if (s.logged_in && !succeeded.current) {
        succeeded.current = true;
        clearInterval(id);
        void authStopPairing();
        onSuccess?.();
      }
    }, 2500);
    return () => clearInterval(id);
  }, [onSuccess]);

  return (
    <Focusable style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ fontSize: 14, opacity: 0.85 }}>
        Easiest in Game Mode: sign in from your <b>phone</b> — scan this, do
        everything on the phone, and the Deck signs in automatically.
      </div>

      <div style={{ display: "flex", gap: 16, alignItems: "center" }}>
        {qr ? (
          <img
            src={qr}
            alt="Sign-in QR"
            style={{ width: 180, height: 180, borderRadius: 8, background: "#fff", flexShrink: 0 }}
          />
        ) : (
          <div style={{ width: 180, height: 180, display: "flex", alignItems: "center", justifyContent: "center", opacity: 0.6 }}>
            {pairErr ? "—" : "Generating QR…"}
          </div>
        )}
        <div style={{ fontSize: 13, lineHeight: 1.6 }}>
          <div>1. Scan with your phone (same Wi-Fi).</div>
          <div>2. Tap <b>Open Epic login</b>, sign in.</div>
          <div>3. Copy the JSON Epic shows, paste it on the phone, tap <b>Send to Deck</b>.</div>
          {pairUrl ? (
            <div style={{ marginTop: 8, opacity: 0.7, wordBreak: "break-all" }}>
              or open on any device: <code>{pairUrl}</code>
            </div>
          ) : null}
        </div>
      </div>

      {pairErr ? (
        <div style={{ fontSize: 13, color: "#ff9a9a" }}>
          Phone pairing unavailable ({pairErr}). Use manual sign-in below.
        </div>
      ) : null}

      <DialogButton style={{ width: 220 }} onClick={() => setShowManual((v) => !v)}>
        {showManual ? "Hide manual sign-in" : "Manual sign-in (desktop)"}
      </DialogButton>

      {showManual ? (
        <Focusable style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <Field label="1. Open this URL in a browser and sign in:" focusable={false}>
            <code style={{ fontSize: 13, wordBreak: "break-all" }}>{loginUrl || "…"}</code>
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
      ) : null}
    </Focusable>
  );
}
