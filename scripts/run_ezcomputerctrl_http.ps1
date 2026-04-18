<#
模块名称：run_ezcomputerctrl_http
功能描述：
    统一负责 EZComputerCtrl 的 Windows 启动逻辑。
    默认支持单次启动；当传入 -KeepAlive 时，当前 PowerShell 进程会转为守护进程，
    在业务进程退出后自动重新拉起，直到收到停止指令或当前会话结束。
作者：JucieOvo
#>

$ErrorActionPreference = "Stop"

$KeepAlive = $false
foreach ($argument in $args) {
    if ($argument -eq "-KeepAlive") {
        $KeepAlive = $true
    }
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$repoRoot = Split-Path -Parent $scriptDir
$runtimeDir = Join-Path $repoRoot ".runtime"
$pidFile = Join-Path $runtimeDir "ezcomputerctrl.pid"
$guardianPidFile = Join-Path $runtimeDir "ezcomputerctrl.guardian.pid"
$stopSignalFile = Join-Path $runtimeDir "ezcomputerctrl.stop"
$envFile = Join-Path $runtimeDir "ezcomputerctrl.env.ps1"
$restartDelaySeconds = 2

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

$python = Get-Command "python.exe" -ErrorAction SilentlyContinue
$pythonw = Get-Command "pythonw.exe" -ErrorAction SilentlyContinue

if ($python) {
    $pythonPath = $python.Source
    $windowStyle = "Hidden"
}
elseif ($pythonw) {
    $pythonPath = $pythonw.Source
    $windowStyle = "Normal"
}
else {
    throw "python.exe not found in PATH"
}

if (Test-Path $guardianPidFile) {
    $recordedGuardianPid = (Get-Content $guardianPidFile -Raw).Trim()
    if ($recordedGuardianPid -match '^[0-9]+$') {
        $guardianProcess = Get-Process -Id ([int]$recordedGuardianPid) -ErrorAction SilentlyContinue
        if ($guardianProcess) {
            if ([int]$recordedGuardianPid -ne $PID) {
                throw "EZComputerCtrl guardian is already running. PID=$recordedGuardianPid"
            }
        }
        else {
            Remove-Item $guardianPidFile -Force
        }
    }
    else {
        Remove-Item $guardianPidFile -Force
    }
}

if (Test-Path $pidFile) {
    $recordedServicePid = (Get-Content $pidFile -Raw).Trim()
    if ($recordedServicePid -match '^[0-9]+$') {
        $serviceProcess = Get-Process -Id ([int]$recordedServicePid) -ErrorAction SilentlyContinue
        if ($serviceProcess) {
            throw "EZComputerCtrl is already running. PID=$recordedServicePid"
        }
        else {
            Remove-Item $pidFile -Force
        }
    }
    else {
        Remove-Item $pidFile -Force
    }
}

if (-not $KeepAlive) {
    $process = Start-Process -FilePath $pythonPath -ArgumentList "-m", "ezcomputerctrl" -WorkingDirectory $repoRoot -WindowStyle $windowStyle -PassThru
    $process.Id.ToString() | Out-File -FilePath $pidFile -Encoding ascii -NoNewline
    Write-Host "EZComputerCtrl started. PID=$($process.Id) URL=http://$($env:EZCTRL_SERVER_HOST):$($env:EZCTRL_SERVER_PORT)/mcp"
    exit 0
}

if (Test-Path $stopSignalFile) {
    Remove-Item $stopSignalFile -Force
}

$PID.ToString() | Out-File -FilePath $guardianPidFile -Encoding ascii -NoNewline

while ($true) {
    if (Test-Path $stopSignalFile) {
        break
    }

    $process = Start-Process -FilePath $pythonPath -ArgumentList "-m", "ezcomputerctrl" -WorkingDirectory $repoRoot -WindowStyle $windowStyle -PassThru
    $process.Id.ToString() | Out-File -FilePath $pidFile -Encoding ascii -NoNewline
    Write-Host "EZComputerCtrl started under guardian. GuardianPID=$PID ServicePID=$($process.Id) URL=http://$($env:EZCTRL_SERVER_HOST):$($env:EZCTRL_SERVER_PORT)/mcp"

    try {
        Wait-Process -Id $process.Id -ErrorAction Stop
    }
    catch {
    }

    if (Test-Path $pidFile) {
        $currentRecordedPid = (Get-Content $pidFile -Raw).Trim()
        if (($currentRecordedPid -notmatch '^[0-9]+$') -or ([int]$currentRecordedPid -eq $process.Id)) {
            Remove-Item $pidFile -Force
        }
    }

    if (Test-Path $stopSignalFile) {
        break
    }

    Start-Sleep -Seconds $restartDelaySeconds
}

if (Test-Path $pidFile) {
    Remove-Item $pidFile -Force
}

if (Test-Path $guardianPidFile) {
    Remove-Item $guardianPidFile -Force
}
