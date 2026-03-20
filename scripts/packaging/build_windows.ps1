param(
    [string]$PythonExe = "python",
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Root = Split-Path -Parent $Root
Set-Location $Root

if ($Clean) {
    Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue
}

& $PythonExe -m pip install --upgrade pip
& $PythonExe -m pip install -e ".[dev]"
& $PythonExe -m pip install pyinstaller
& $PythonExe -m PyInstaller --noconfirm --clean scripts/packaging/rka_desktop.spec

$BundleDir = Join-Path $Root "dist/RKA3000Desktop"
Copy-Item -Force (Join-Path $Root ".env.example") (Join-Path $BundleDir ".env.example")

& powershell -NoProfile -ExecutionPolicy Bypass -File scripts/packaging/verify_windows_bundle.ps1
