# Silent install into a temporary directory, run the installed desktop smoke, then uninstall and
# verify the program is removed. User data under the data directory is expected to remain.
$ErrorActionPreference = 'Stop'
$assets = Join-Path $PSScriptRoot '../dist/release'
$installers = @(Get-ChildItem -LiteralPath $assets -Filter '*_setup.exe')
if ($installers.Count -ne 1) { throw 'Expected exactly one staged installer' }
$installDirectory = Join-Path $env:LOCALAPPDATA ('rka3000-ci-install-' + [guid]::NewGuid())
$installer = Start-Process -FilePath $installers[0].FullName -ArgumentList @('/S', "/D=$installDirectory") -Wait -PassThru -WindowStyle Hidden
if ($installer.ExitCode -ne 0) { throw "NSIS install failed: $($installer.ExitCode)" }
if (-not (Test-Path -LiteralPath (Join-Path $installDirectory 'rka3000-backend.exe'))) { throw 'Installed backend missing' }
if (-not (Test-Path -LiteralPath (Join-Path $installDirectory 'notices/THIRD_PARTY_NOTICES.md'))) { throw 'Installed notices missing' }
& (Join-Path $PSScriptRoot 'smoke_desktop.ps1') -Executable (Join-Path $installDirectory 'rka3000-desktop.exe')
$uninstaller = Join-Path $installDirectory 'uninstall.exe'
$uninstall = Start-Process -FilePath $uninstaller -ArgumentList @('/S', "_?=$installDirectory") -Wait -PassThru -WindowStyle Hidden
if ($uninstall.ExitCode -ne 0) { throw "NSIS uninstall failed: $($uninstall.ExitCode)" }
if (Test-Path -LiteralPath (Join-Path $installDirectory 'rka3000-desktop.exe')) { throw 'Application still exists after uninstall' }
Write-Output 'NSIS install, installed desktop smoke and uninstall passed.'
