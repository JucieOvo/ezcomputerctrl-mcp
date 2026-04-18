$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$repoRoot = Split-Path -Parent $scriptDir
$runtimeDir = Join-Path $repoRoot ".runtime"
$pidFile = Join-Path $runtimeDir "ezcomputerctrl.pid"

if (-not (Test-Path $pidFile)) {
    Write-Host "EZComputerCtrl is not running. PID file not found."
    exit 0
}

$targetPid = (Get-Content $pidFile -Raw).Trim()

if (-not ($targetPid -match '^[0-9]+$')) {
    Remove-Item $pidFile -Force
    Write-Host "Invalid PID file removed."
    exit 0
}

try {
    Stop-Process -Id $targetPid -Force -ErrorAction Stop
    Write-Host "EZComputerCtrl stopped. PID=$targetPid"
}
catch {
    Write-Host "Process not found. Cleaning stale PID file."
}

if (Test-Path $pidFile) {
    Remove-Item $pidFile -Force
}
