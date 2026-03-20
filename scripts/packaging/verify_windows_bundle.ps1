$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Root = Split-Path -Parent $Root
Set-Location $Root

$BundleDir = Join-Path $Root "dist/RKA3000Desktop"
$ExePath = Join-Path $BundleDir "RKA3000Desktop.exe"
$EnvExample = Join-Path $BundleDir ".env.example"

if (-not (Test-Path $BundleDir)) {
    throw "未找到打包输出目录: $BundleDir"
}

if (-not (Test-Path $ExePath)) {
    throw "未找到主程序: $ExePath"
}

if (-not (Test-Path $EnvExample)) {
    throw "未找到 .env.example: $EnvExample"
}

Write-Host "Windows bundle verification passed."
