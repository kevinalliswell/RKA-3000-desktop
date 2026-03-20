$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Root = Split-Path -Parent $Root
Set-Location $Root

$BundleDir = Join-Path $Root "dist/RKA3000Desktop"
$ExePath = Join-Path $BundleDir "RKA3000Desktop.exe"
$EnvExample = Join-Path $BundleDir ".env.example"

if (-not (Test-Path $BundleDir)) {
    throw "Bundle output directory not found: $BundleDir"
}

if (-not (Test-Path $ExePath)) {
    throw "Executable not found: $ExePath"
}

if (-not (Test-Path $EnvExample)) {
    throw ".env.example not found: $EnvExample"
}

Write-Host "Windows bundle verification passed."
