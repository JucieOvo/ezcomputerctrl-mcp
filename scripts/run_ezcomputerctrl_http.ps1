$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$repoRoot = Split-Path -Parent $scriptDir
$runtimeDir = Join-Path $repoRoot ".runtime"
$pidFile = Join-Path $runtimeDir "ezcomputerctrl.pid"
$envFile = Join-Path $runtimeDir "ezcomputerctrl.env.ps1"

if (-not (Test-Path $runtimeDir)) {
    New-Item -ItemType Directory -Path $runtimeDir | Out-Null
}

if (Test-Path $envFile) {
    . $envFile
}

if (-not $env:EZCTRL_TRANSPORT) {
    $env:EZCTRL_TRANSPORT = "streamable-http"
}

if (-not $env:EZCTRL_SERVER_HOST) {
    $env:EZCTRL_SERVER_HOST = "127.0.0.1"
}

if (-not $env:EZCTRL_SERVER_PORT) {
    $env:EZCTRL_SERVER_PORT = "8765"
}

$srcDir = Join-Path $repoRoot "src"
if (Test-Path $srcDir) {
    if ([string]::IsNullOrWhiteSpace($env:PYTHONPATH)) {
        $env:PYTHONPATH = $srcDir
    }
    else {
        $env:PYTHONPATH = "$srcDir;$($env:PYTHONPATH)"
    }
}

if (Test-Path $pidFile) {
    $oldPid = (Get-Content $pidFile -Raw).Trim()
    if ($oldPid -match '^[0-9]+$') {
        try {
            Get-Process -Id $oldPid -ErrorAction Stop | Out-Null
            Write-Host "EZComputerCtrl is already running. PID=$oldPid"
            exit 1
        }
        catch {
            Remove-Item $pidFile -Force
        }
    }
    else {
        Remove-Item $pidFile -Force
    }
}

$pythonw = Get-Command "pythonw.exe" -ErrorAction SilentlyContinue
$python = Get-Command "python.exe" -ErrorAction SilentlyContinue

if ($pythonw) {
    $pythonPath = $pythonw.Source
    $windowStyle = "Normal"
}
elseif ($python) {
    $pythonPath = $python.Source
    $windowStyle = "Hidden"
}
else {
    throw "python.exe not found in PATH"
}

$process = Start-Process -FilePath $pythonPath -ArgumentList "-m", "ezcomputerctrl" -WorkingDirectory $repoRoot -WindowStyle $windowStyle -PassThru

$process.Id.ToString() | Out-File -FilePath $pidFile -Encoding ascii -NoNewline

Write-Host "EZComputerCtrl started. PID=$($process.Id) URL=http://$($env:EZCTRL_SERVER_HOST):$($env:EZCTRL_SERVER_PORT)/mcp"
