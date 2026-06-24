# One-shot Windows validation: everything verifiable without a Steam Deck.
#
#   pwsh -File scripts/verify_windows.ps1
#
# Sets up a dev venv with the real legendary (if missing), then runs:
#   1. legendary API conformance (backend vs. real legendary)
#   2. RAWG matching/cache logic (offline, mocked HTTP)
#   3. backend RPC harness (real Plugin lifecycle, no login required)
#   4. frontend build + strict type-check
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

$uv = "$env:USERPROFILE\.local\bin\uv.exe"
$py = ".venv\Scripts\python.exe"

if (-not (Test-Path $py)) {
  Write-Host ">> Creating dev venv with real legendary..."
  & $uv venv --python 3.14 .venv
  & $uv pip install --python $py "git+https://github.com/legendary-gl/legendary.git"
}

Write-Host "`n========== 1. legendary API conformance =========="
& $py scripts\devtools\verify_legendary_api.py

Write-Host "`n========== 2. RAWG logic (offline) =========="
& $py scripts\devtools\test_rawg_offline.py

Write-Host "`n========== 3. backend RPC harness =========="
& $py scripts\devtools\dev_harness.py validate

Write-Host "`n========== 4. frontend build + type-check =========="
pnpm run build
pnpm exec tsc --noEmit

Write-Host "`nALL WINDOWS VALIDATION PASSED" -ForegroundColor Green
