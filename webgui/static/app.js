"use strict";

const state = {
  games: [], settings: {}, auth: { logged_in: false },
  running: { running: false, app_name: null }, download: null, loginUrl: "#",
  selected: null, saves: {},
};

const $ = (id) => document.getElementById(id);

async function api(path, method = "GET", body) {
  const opts = { method, headers: { "Content-Type": "application/json" } };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const r = await fetch(path, opts);
  return r.status === 204 ? null : r.json();
}

function toast(msg) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.remove("show"), 2600);
}

function fmtBytes(n) {
  if (!n) return "0 B";
  const u = ["B", "KiB", "MiB", "GiB", "TiB"]; let i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return `${n.toFixed(i ? 1 : 0)} ${u[i]}`;
}

// ---- data ----
async function loadState() {
  const s = await api("/api/state");
  state.auth = s.auth; state.settings = s.settings; state.running = s.running;
  state.download = s.download; state.loginUrl = s.login_url; state.platform = s.platform;
  renderAuth();
}

async function loadLibrary(refresh = false) {
  const data = await api(`/api/library?refresh=${refresh ? 1 : 0}`);
  state.games = data.games || [];
  renderGrid();
}

// ---- render ----
function renderAuth() {
  $("authPill").textContent = state.auth.logged_in
    ? `Signed in: ${state.auth.user}` : "Not signed in";
  $("loginBtn").style.display = state.auth.logged_in ? "none" : "";
}

function renderOp() {
  const d = state.download;
  let txt = "";
  if (d && d.state === "downloading") txt = `⬇ ${d.title || d.app_name} ${Math.round(d.progress)}%`;
  else if (state.running.running) txt = `▶ ${state.running.app_name}`;
  $("opPill").textContent = txt;
}

function sortGames(list) {
  const mode = $("sort").value;
  const arr = [...list];
  if (mode === "installed") arr.sort((a, b) => (b.installed - a.installed) || a.title.localeCompare(b.title));
  else arr.sort((a, b) => a.title.localeCompare(b.title));
  return arr;
}

function renderGrid() {
  const q = $("search").value.toLowerCase();
  const filtered = state.games.filter((g) => !q || g.title.toLowerCase().includes(q));
  const grid = $("grid");
  grid.innerHTML = "";
  for (const g of sortGames(filtered)) {
    const card = document.createElement("div");
    card.className = "card";
    card.onclick = () => openDetail(g.app_name);
    const cover = g.cover
      ? `<img class="cover" src="${g.cover}" loading="lazy" />`
      : `<div class="nocover">${g.title}</div>`;
    const flags = [g.installed ? '<span class="chip">⬇</span>' : "",
                   g.cloud_saves ? '<span class="chip">☁</span>' : ""].join("");
    card.innerHTML = `${cover}
      <div class="flags">${flags}</div>
      <div class="title">${g.title}</div>`;
    grid.appendChild(card);
  }
  renderOp();
}

// ---- detail modal ----
async function openDetail(app) {
  state.selected = app;
  const g = state.games.find((x) => x.app_name === app);
  if (!g) return;
  $("detailOverlay").classList.add("show");
  state.saves[app] = null;
  renderDetail();
  if (g.installed && g.cloud_saves) {
    state.saves[app] = await api(`/api/saves/status?app=${encodeURIComponent(app)}`);
    renderDetail();
  }
}

function closeDetail() { $("detailOverlay").classList.remove("show"); state.selected = null; }

function renderDetail() {
  const app = state.selected;
  if (!app) return;
  const g = state.games.find((x) => x.app_name === app);
  const d = state.download && state.download.app_name === app ? state.download : null;
  const downloading = d && d.state === "downloading";
  const runningThis = state.running.running && state.running.app_name === app;
  const saves = state.saves[app];

  let actions = "";
  if (!g.installed && !downloading) actions += `<button class="primary" onclick="act('install')">Install</button>`;
  if (downloading) actions += `<button onclick="act('cancel')">Cancel download</button>`;
  if (g.installed && !runningThis) actions += `<button class="primary" onclick="act('play')">▶ Play</button>`;
  if (runningThis) actions += `<button onclick="act('stop')">■ Stop</button>`;
  if (g.installed) actions += `<button onclick="act('uninstall')">🗑 Uninstall</button>`;

  let progress = "";
  if (downloading) {
    progress = `<div class="progress"><div style="width:${d.progress}%"></div></div>
      <div class="muted">${Math.round(d.progress)}% · ${fmtBytes(d.download_speed)}/s · ${fmtBytes(d.downloaded_bytes)} / ${fmtBytes(d.dl_total_bytes)}</div>`;
  }

  let cloud = "";
  if (g.installed && g.cloud_saves) {
    let inner;
    if (saves == null) inner = `<div class="muted">Checking…</div>`;
    else if (saves.supported === false) inner = `<div class="muted">${saves.error || "Not supported"}</div>`;
    else if (saves.needs_path) inner = `<div style="color:#fbbf24">${saves.error}</div>`;
    else inner = `
      <div class="muted">Status: ${saves.status || "?"} · Local: ${fmtDate(saves.local_dt)} · Cloud: ${fmtDate(saves.remote_dt)}</div>
      <div class="row" style="margin-top:10px">
        <button class="primary" onclick="syncSaves('both')">Sync now</button>
        <button onclick="syncSaves('pull',false,true)">☁⬇ Force download</button>
        <button onclick="syncSaves('push',true,false)">☁⬆ Force upload</button>
      </div>`;
    cloud = `<div class="section"><h3>☁ Cloud Saves</h3>${inner}</div>`;
  } else if (g.cloud_saves) {
    cloud = `<div class="section muted">Cloud saves supported — install to sync.</div>`;
  }

  $("detailModal").innerHTML = `
    <div class="row" style="align-items:flex-start; gap:18px">
      ${g.cover ? `<img src="${g.cover}" style="width:170px;border-radius:8px" />` : ""}
      <div style="flex:1; min-width:240px">
        <div class="row"><h2>${g.title}</h2></div>
        <div class="muted">${app}</div>
        <div class="row" style="margin-top:16px">${actions}</div>
        ${progress}
        ${cloud}
      </div>
    </div>
    <div style="margin-top:18px"><button onclick="closeDetail()">Close</button></div>`;
}

function fmtDate(iso) { if (!iso) return "—"; try { return new Date(iso).toLocaleString(); } catch { return iso; } }

// ---- actions ----
window.act = async function (kind) {
  const app = state.selected;
  if (kind === "install") { const r = await api("/api/download/start", "POST", { app_name: app }); if (!r.ok) toast(r.error || "failed"); }
  if (kind === "cancel") await api("/api/download/cancel", "POST", { app_name: app });
  if (kind === "play") { const r = await api("/api/launch", "POST", { app_name: app }); if (!r.ok) toast(r.error || "failed"); }
  if (kind === "stop") await api("/api/stop", "POST", {});
  if (kind === "uninstall") {
    const r = await api("/api/uninstall", "POST", { app_name: app });
    if (r.ok) { const g = state.games.find((x) => x.app_name === app); if (g) g.installed = false; toast("Uninstalled"); renderGrid(); }
    else toast(r.error || "failed");
  }
  renderDetail();
};

window.syncSaves = async function (direction, up = false, down = false) {
  const app = state.selected;
  const r = await api("/api/saves/sync", "POST", { app_name: app, direction, force_up: up, force_down: down });
  toast(r.ok === false ? (r.error || "sync issue") : `Cloud: ${r.action || "up to date"}`);
  state.saves[app] = await api(`/api/saves/status?app=${encodeURIComponent(app)}`);
  renderDetail();
};
window.closeDetail = closeDetail;

// ---- SSE ----
function startEvents() {
  const es = new EventSource("/events");
  es.onmessage = (e) => {
    const { event, payload } = JSON.parse(e.data);
    if (event === "epic_download_progress") { state.download = payload; renderOp(); if (state.selected === payload.app_name) renderDetail(); }
    else if (event === "epic_download_state") {
      state.download = { ...(state.download || {}), ...payload };
      if (payload.state === "done") {
        const g = state.games.find((x) => x.app_name === payload.app_name); if (g) g.installed = true;
        toast("Download complete"); renderGrid();
      } else if (payload.state === "error") toast("Download error: " + (payload.error || ""));
      renderOp(); if (state.selected === payload.app_name) { openDetail(payload.app_name); }
    }
    else if (event === "epic_launch_state") {
      state.running = { running: !["exited", "error"].includes(payload.state), app_name: payload.app_name };
      if (payload.state === "syncing_down") toast("Syncing cloud save…");
      if (payload.state === "syncing_up") toast("Saving to cloud…");
      if (payload.state === "exited") toast("Game exited");
      renderOp(); if (state.selected === payload.app_name) renderDetail();
    }
  };
}

// ---- wiring ----
$("search").oninput = renderGrid;
$("sort").onchange = renderGrid;
$("refreshBtn").onclick = () => loadLibrary(true);
$("loginBtn").onclick = () => { $("loginUrl").textContent = state.loginUrl; $("loginUrl").href = state.loginUrl; $("loginOverlay").classList.add("show"); };
$("loginClose").onclick = () => $("loginOverlay").classList.remove("show");
$("authSubmit").onclick = async () => {
  const r = await api("/api/auth/finish", "POST", { code: $("authCode").value.trim() });
  if (r.ok) { toast("Signed in: " + (r.user || "")); $("loginOverlay").classList.remove("show"); await loadState(); await loadLibrary(true); }
  else toast("Sign-in failed: " + (r.error || ""));
};
$("settingsBtn").onclick = () => {
  $("setPath").value = state.settings.install_base_path || "";
  $("settingsOverlay").classList.add("show");
};
$("settingsClose").onclick = () => $("settingsOverlay").classList.remove("show");
$("settingsSave").onclick = async () => {
  state.settings = await api("/api/settings", "POST", { install_base_path: $("setPath").value.trim() });
  toast("Saved"); $("settingsOverlay").classList.remove("show"); loadLibrary(false);
};
$("logoutBtn").onclick = async () => { await api("/api/auth/logout", "POST", {}); $("settingsOverlay").classList.remove("show"); await loadState(); state.games = []; renderGrid(); };
[ "detailOverlay", "loginOverlay", "settingsOverlay" ].forEach((id) => {
  $(id).onclick = (e) => { if (e.target.id === id) $(id).classList.remove("show"); };
});

// ---- boot ----
(async function () {
  startEvents();
  await loadState();
  if (state.auth.logged_in) await loadLibrary(false);
})();
