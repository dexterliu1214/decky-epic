# Launch the Windows GUI desktop version (local web app over the real backend).
#
#   pwsh -File scripts/run_gui.ps1
#
# Creates the dev venv with real legendary if missing, installs the GUI server
# deps (fastapi + uvicorn) once, starts the server, and opens your browser.
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

$uv = "$env:USERPROFILE\.local\bin\uv.exe"
$py = ".venv\Scripts\python.exe"

if (-not (Test-Path $py)) {
  & $uv venv --python 3.14 .venv
  & $uv pip install --python $py "git+https://github.com/legendary-gl/legendary.git"
}

# Ensure GUI server deps are present.
& $py -c "import fastapi, uvicorn" 2>$null
if ($LASTEXITCODE -ne 0) {
  Write-Host ">> Installing GUI server deps (fastapi, uvicorn)..."
  & $uv pip install --python $py fastapi "uvicorn[standard]"
}

$port = if ($env:GUI_PORT) { $env:GUI_PORT } else { "8777" }
Start-Process "http://127.0.0.1:$port"
Write-Host ">> Starting decky-epic GUI on http://127.0.0.1:$port  (Ctrl+C to stop)"
& $py webgui\server.py
