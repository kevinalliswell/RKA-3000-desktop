$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
Set-Location $repoRoot
$pythonBin = Join-Path $repoRoot ".venv/Scripts/python.exe"
if (!(Test-Path $pythonBin)) { throw "Create .venv and install the Python project before packaging." }
& $pythonBin -m PyInstaller --version
if ($LASTEXITCODE -ne 0) { throw "Install PyInstaller in .venv first." }
& $pythonBin -m PyInstaller --noconfirm --clean --onefile --name rka-backend --paths (Join-Path $repoRoot "src") --distpath (Join-Path $repoRoot "frontend/sidecar-dist") --workpath (Join-Path $repoRoot "build/tauri-backend") --specpath (Join-Path $repoRoot "build/tauri-backend") (Join-Path $repoRoot "src/rka_desktop/desktop_bridge.py")
if ($LASTEXITCODE -ne 0) { throw "Backend packaging failed." }
Set-Location (Join-Path $repoRoot "frontend")
npm ci
if ($LASTEXITCODE -ne 0) { throw "npm ci failed." }
npm run check
if ($LASTEXITCODE -ne 0) { throw "Frontend check failed." }
npm run tauri -- build --config src-tauri/tauri.release.windows.conf.json
if ($LASTEXITCODE -ne 0) { throw "Tauri build failed." }
