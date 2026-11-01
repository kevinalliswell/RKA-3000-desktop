# Starts the packaged desktop in an isolated user profile, waits for the window and the bundled
# backend, closes the window normally and verifies no backend process is left behind.
param([Parameter(Mandatory = $true)][string]$Executable)
$ErrorActionPreference = 'Stop'
$executablePath = (Resolve-Path -LiteralPath $Executable).Path
$profileDirectory = Join-Path ([System.IO.Path]::GetTempPath()) ('rka3000-desktop-' + [guid]::NewGuid())
New-Item -ItemType Directory -Path $profileDirectory | Out-Null
$dataDirectory = Join-Path $profileDirectory 'RKA3000'
$baseline = @(Get-Process -Name rka3000-backend -ErrorAction SilentlyContinue | ForEach-Object Id)
$start = [System.Diagnostics.ProcessStartInfo]::new($executablePath)
$start.UseShellExecute = $false
$start.RedirectStandardOutput = $true
$start.RedirectStandardError = $true
$start.WorkingDirectory = $profileDirectory
$start.Environment['USERPROFILE'] = $profileDirectory
$start.Environment['LOCALAPPDATA'] = $profileDirectory
$start.Environment['RKA3000_DATA_DIR'] = $dataDirectory
$start.Environment['RUST_BACKTRACE'] = '1'
$start.Environment.Remove('RKA3000_PYTHON') | Out-Null
$desktop = [System.Diagnostics.Process]::Start($start)
$stdout = $desktop.StandardOutput.ReadToEndAsync()
$stderr = $desktop.StandardError.ReadToEndAsync()
try {
    $deadline = (Get-Date).AddSeconds(60)
    do {
        Start-Sleep -Milliseconds 250
        $desktop.Refresh()
        if ($desktop.HasExited) { throw "Desktop exited during startup: $($desktop.ExitCode)" }
    } until ($desktop.MainWindowHandle -ne 0 -or (Get-Date) -gt $deadline)
    if ($desktop.MainWindowHandle -eq 0) { throw 'No desktop window appeared within 60 seconds' }
    do {
        Start-Sleep -Milliseconds 250
        $desktop.Refresh()
        if ($desktop.HasExited) { throw "Desktop exited during setup: $($desktop.ExitCode)" }
        $sidecars = @(Get-Process -Name rka3000-backend -ErrorAction SilentlyContinue | Where-Object { $_.Id -notin $baseline })
    } until ($sidecars.Count -gt 0 -or (Get-Date) -gt $deadline)
    if ($sidecars.Count -eq 0) { throw 'Packaged Python backend did not start' }
    Start-Sleep -Seconds 3
    $desktop.Refresh()
    if ($desktop.HasExited) { throw "Desktop exited after backend launch: $($desktop.ExitCode)" }
    if (-not (Test-Path -LiteralPath (Join-Path $dataDirectory 'logs/backend.log'))) { throw 'backend.log was not created in the data directory' }
    if (-not $desktop.CloseMainWindow()) { throw 'Could not request normal window close' }
    if (-not $desktop.WaitForExit(30000)) { throw 'Desktop did not exit after window close' }
    if ($desktop.ExitCode -ne 0) { throw "Desktop exit code: $($desktop.ExitCode)" }
    foreach ($sidecar in $sidecars) {
        if (-not $sidecar.WaitForExit(15000)) { throw "Orphaned Python backend process: $($sidecar.Id)" }
    }
    $log = Get-Content -LiteralPath (Join-Path $dataDirectory 'logs/backend.log') -Raw
    if ($log -notmatch 'backend exited cleanly') { throw 'backend.log does not record a clean exit' }
    Write-Output 'Desktop smoke: window, bundled backend, graceful close and backend exit passed.'
} finally {
    if (-not $desktop.HasExited) { & taskkill /PID $desktop.Id /T /F | Out-Null }
    $desktop.WaitForExit()
    Write-Output $stdout.GetAwaiter().GetResult()
    Write-Output $stderr.GetAwaiter().GetResult()
    Get-ChildItem -LiteralPath $profileDirectory -Recurse -Filter '*.log' -ErrorAction SilentlyContinue | ForEach-Object { Write-Output "--- $($_.FullName)"; Get-Content -LiteralPath $_.FullName }
    $desktop.Dispose()
    Write-Output "Smoke profile: $profileDirectory"
}
