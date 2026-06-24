# decky-epic

A [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) plugin for the
Steam Deck that downloads and plays **Epic Games Store** titles — with **Epic
cloud-save sync as the headline feature**, a Steam-like browsing UI, and
Metacritic-style sorting.

It uses [`legendary`](https://github.com/legendary-gl/legendary) as the Epic
engine (vendored into `py_modules`), reuses Steam's installed Proton builds to
run games, and pulls critic scores from [RAWG](https://rawg.io) (cached locally).

> Critic-score data provided by RAWG.io.

## Status

MVP implemented and building. On-device (Steam Deck) verification is the
remaining step — see *Testing on a Steam Deck* below.

- **M0** Scaffold (build + empty plugin loads) ✅
- **M1** Vendor legendary + backend boot ✅
- **M2** Epic auth (SSO + paste authorization code) ✅ *(impl)*
- **M3** Library list + RAWG Metacritic scores/sort ✅ *(impl)*
- **M4** Download with Steam-like progress ✅ *(impl)*
- **M5** Proton discovery + launch ✅ *(impl)*
- **M6** Cloud saves around launch (top priority) ✅ *(impl)*
- **M7** Polish + package — packaging scripts done; final on-device pass pending

## Windows GUI (desktop app)

A full graphical version runs on Windows over the **same backend** (`main.Plugin`
+ real legendary). It serves a Steam-like web UI — cover-art grid, Metacritic
sort/search, install with live progress, native game launch, and cloud-save
sync — as a local app:

```powershell
pwsh -File scripts/run_gui.ps1
```

This creates the dev venv (real legendary), installs `fastapi`/`uvicorn` on first
run, starts the server, and opens `http://127.0.0.1:8777`. Sign in (paste the
Epic `authorizationCode`), add a RAWG key in Settings, then browse/install/play.
On Windows games launch natively (no Proton) and cloud saves resolve via
`%LOCALAPPDATA%`, so the cloud-save round-trip is fully usable here.

Files: `webgui/server.py` (FastAPI + SSE), `webgui/static/{index.html,app.js}`.

## Validating on Windows (no Steam Deck needed)

Decky only runs on Linux, but the backend is plain Python + legendary, which
runs natively on Windows. A one-shot script validates everything verifiable
locally — legendary API conformance, RAWG logic, the real `Plugin` RPC
lifecycle, and the frontend build/type-check:

```powershell
pwsh -File scripts/verify_windows.ps1
```

It creates a dev venv (`.venv`) with the real legendary on first run. You can
also drive the backend interactively against your own Epic account on Windows
(download + cloud-save round-trips resolve via `%LOCALAPPDATA%`, no Proton):

```powershell
.venv\Scripts\python.exe scripts\devtools\dev_harness.py login <authorizationCode>
.venv\Scripts\python.exe scripts\devtools\dev_harness.py library
.venv\Scripts\python.exe scripts\devtools\dev_harness.py download <AppName>
.venv\Scripts\python.exe scripts\devtools\dev_harness.py sync <AppName> both
.venv\Scripts\python.exe scripts\devtools\dev_harness.py rawg <RAWG_KEY> "Hades" "Control"
```

## Testing on a Steam Deck

1. `bash scripts/vendor_backend.sh` — (re)vendor the Linux backend deps (already done once).
2. `pnpm install && pnpm run build`
3. `DECK_HOST=deck@<deck-ip> bash scripts/deploy_to_deck.sh`
4. On the Deck: `cd ~/homebrew/plugins/decky-epic && python3 scripts/smoke_backend.py`
   to confirm the vendored backend + Proton discovery work.
5. Open Decky → Epic → Settings: sign in (paste the Epic `authorizationCode`),
   add a RAWG API key. Then browse the Library, install a small game, and
   Play it — saves download before launch and upload after exit.

## Development

Requires Node 18+, pnpm 9, and Python 3.9+ (for vendoring backend deps).

```bash
pnpm install
pnpm run build      # produces dist/ ; the decky CLI packages dist + main.py + py_modules
```

Deploy to a Steam Deck running Decky in Developer Mode by copying the built
output into `~/homebrew/plugins/decky-epic` (see the Decky docs).
