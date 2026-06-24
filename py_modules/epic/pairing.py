"""LAN pairing server for phone-assisted Epic login.

Signing in to Epic on a Steam Deck in Game Mode is painful: there's no easy
browser and pasting a 32-char code with the on-screen keyboard is miserable.
This server lets the whole login happen on a phone instead:

    Deck panel shows a QR  ->  phone opens this page  ->  phone logs in to Epic
    ->  phone pastes the JSON blob here  ->  we exchange the code  ->  Deck panel
    polls auth_status and flips to "signed in".

Nothing is typed or browsed on the Deck. The page URL carries a random token;
requests without the matching token are rejected so a random LAN host can't
drive the flow.

Pure stdlib (http.server) — no extra dependencies are vendored.
"""
from __future__ import annotations

import hmac
import json
import logging
import secrets
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Optional
from urllib.parse import parse_qs, urlparse

_log = logging.getLogger("decky-epic.pairing")

# Fixed-ish port so the QR target is predictable; we walk forward if it's taken.
_DEFAULT_PORT = 9988
_PORT_TRIES = 8

# submit(payload:str) -> {"ok": bool, "user": str|None, "error": str|None}
SubmitFn = Callable[[str], dict]


def _lan_ip() -> str:
    """Best-effort primary LAN IPv4 of this host (no traffic actually sent)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def _page(login_url: str) -> bytes:
    """The mobile companion page. Reads its own ?t= token and POSTs the pasted
    blob to /submit. Kept dependency-free and self-contained."""
    html = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>decky-epic · Sign in</title>
<style>
  :root { color-scheme: dark; }
  body { font-family: system-ui, sans-serif; background:#1a1d23; color:#e6e6e6;
         margin:0; padding:24px; max-width:560px; }
  h1 { font-size:20px; margin:0 0 4px; }
  p { line-height:1.5; opacity:.85; }
  ol { line-height:1.8; padding-left:20px; }
  a.btn, button { display:inline-block; background:#2a6df4; color:#fff; border:0;
         border-radius:8px; padding:12px 18px; font-size:16px; font-weight:600;
         text-decoration:none; cursor:pointer; }
  textarea { width:100%; min-height:110px; box-sizing:border-box; margin-top:8px;
         background:#11141a; color:#e6e6e6; border:1px solid #333; border-radius:8px;
         padding:10px; font-size:15px; }
  #msg { margin-top:14px; padding:12px; border-radius:8px; font-weight:600; display:none; }
  .ok { background:#16331f; color:#7be08a; }
  .err { background:#3a1a1a; color:#ff9a9a; }
  .step { margin:18px 0; }
</style></head>
<body>
  <h1>Sign in to Epic</h1>
  <p>Do this on your phone — nothing needs to be typed on the Deck.</p>

  <div class="step">
    <ol>
      <li>Tap <b>Open Epic login</b> below and sign in.</li>
      <li>Epic shows a block of JSON. <b>Select all &amp; copy</b> it.</li>
      <li>Come back here, <b>paste</b> it, and tap <b>Send to Deck</b>.</li>
    </ol>
  </div>

  <div class="step">
    <a class="btn" href="__LOGIN_URL__" target="_blank" rel="noopener">Open Epic login ↗</a>
  </div>

  <div class="step">
    <textarea id="blob" placeholder='Paste the JSON here, e.g. {"authorizationCode":"..."}'></textarea>
    <div style="margin-top:10px;"><button id="send">Send to Deck</button></div>
  </div>

  <div id="msg"></div>

<script>
  var token = new URLSearchParams(location.search).get('t') || '';
  var btn = document.getElementById('send');
  var msg = document.getElementById('msg');
  function show(cls, text){ msg.className = cls; msg.textContent = text; msg.style.display = 'block'; }
  btn.addEventListener('click', function(){
    var blob = document.getElementById('blob').value.trim();
    if(!blob){ show('err','Paste the JSON (or just the code) first.'); return; }
    btn.disabled = true; show('', 'Sending…');
    fetch('/submit?t=' + encodeURIComponent(token), {
      method:'POST', headers:{'Content-Type':'text/plain'}, body: blob
    }).then(function(r){ return r.json(); }).then(function(j){
      if(j.ok){ show('ok', 'Signed in as ' + (j.user || 'your account') + '. You can close this and return to the Deck.'); }
      else { show('err', 'Failed: ' + (j.error || 'unknown error') + '. The code may have expired — try logging in again.'); btn.disabled = false; }
    }).catch(function(e){ show('err', 'Network error: ' + e); btn.disabled = false; });
  });
</script>
</body></html>"""
    return html.replace("__LOGIN_URL__", login_url).encode("utf-8")


class _Handler(BaseHTTPRequestHandler):
    # Silence the default stderr request logging; route to our logger at debug.
    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        _log.debug("pairing http: " + fmt, *args)

    @property
    def _srv(self) -> "PairingServer":
        return self.server._pairing  # type: ignore[attr-defined]

    def _token_ok(self) -> bool:
        q = parse_qs(urlparse(self.path).query)
        tok = (q.get("t") or [""])[0]
        return bool(tok) and hmac.compare_digest(tok, self._srv.token or "")

    def _send_json(self, code: int, obj: dict) -> None:
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path not in ("/", "/index.html"):
            self.send_error(404)
            return
        if not self._token_ok():
            self.send_error(403, "invalid or missing token")
            return
        body = _page(self._srv.login_url)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        if urlparse(self.path).path != "/submit":
            self.send_error(404)
            return
        if not self._token_ok():
            self._send_json(403, {"ok": False, "error": "invalid or missing token"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            payload = self.rfile.read(length).decode("utf-8", "replace").strip()
        except Exception as e:
            self._send_json(400, {"ok": False, "error": f"bad request: {e}"})
            return
        try:
            result = self._srv.submit(payload)
        except Exception as e:
            _log.exception("pairing submit failed")
            self._send_json(500, {"ok": False, "error": f"{e}"})
            return
        self._send_json(200, result)


class PairingServer:
    """Owns the threaded HTTP server. ``start()`` is idempotent — if already
    serving it just returns the live connection info (with a fresh token)."""

    def __init__(self, submit: SubmitFn, login_url: str) -> None:
        self.submit = submit
        self.login_url = login_url
        self.token: Optional[str] = None
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def start(self) -> dict:
        with self._lock:
            self.token = secrets.token_urlsafe(16)
            if self._httpd is None:
                self._httpd = self._bind()
                self._httpd._pairing = self  # type: ignore[attr-defined]
                self._thread = threading.Thread(
                    target=self._httpd.serve_forever,
                    name="decky-epic-pairing",
                    daemon=True,
                )
                self._thread.start()
            host = _lan_ip()
            port = self._httpd.server_address[1]
            url = f"http://{host}:{port}/?t={self.token}"
            _log.info("pairing server ready at %s", url)
            return {"url": url, "host": host, "port": port, "token": self.token}

    def _bind(self) -> ThreadingHTTPServer:
        last: Exception | None = None
        for i in range(_PORT_TRIES):
            port = _DEFAULT_PORT + i
            try:
                httpd = ThreadingHTTPServer(("0.0.0.0", port), _Handler)
                httpd.daemon_threads = True
                return httpd
            except OSError as e:
                last = e
        raise RuntimeError(f"could not bind pairing port: {last}")

    def stop(self) -> None:
        with self._lock:
            self.token = None
            if self._httpd is not None:
                try:
                    self._httpd.shutdown()
                    self._httpd.server_close()
                except Exception:
                    pass
                self._httpd = None
                self._thread = None
                _log.info("pairing server stopped")
