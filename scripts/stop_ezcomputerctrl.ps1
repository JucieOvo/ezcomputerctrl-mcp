<#
模块名称：stop_ezcomputerctrl
功能描述：
    停止当前 EZComputerCtrl 运行实例。
    本脚本会先写入停止信号，阻止守护进程继续重启业务进程，
    再依次结束业务进程与守护进程，最后清理运行期文件。
作者：JucieOvo
#>

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$repoRoot = Split-Path -Parent $scriptDir
$runtimeDir = Join-Path $repoRoot ".runtime"
$pidFile = Join-Path $runtimeDir "ezcomputerctrl.pid"
$guardianPidFile = Join-Path $runtimeDir "ezcomputerctrl.guardian.pid"
$stopSignalFile = Join-Path $runtimeDir "ezcomputerctrl.stop"

function Remove-RuntimeFile {
    <#
    功能描述：
        在文件存在时执行删除，避免重复清理时报错。

    :param Path: 待清理文件路径。
    #>

    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    if (Test-Path $Path) {
        Remove-Item $Path -Force
    }
}

function Get-RecordedPid {
    <#
    功能描述：
        从 PID 文件中读取记录值；若文件内容非法，则清理该文件并返回 $null。

    :param Path: PID 文件路径。
    :return: 有效 PID 整数或 $null。
    #>

    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    if (-not (Test-Path $Path)) {
        return $null
    }

    $rawPid = (Get-Content $Path -Raw).Trim()
    if (-not ($rawPid -match '^[0-9]+$')) {
        Remove-RuntimeFile -Path $Path
        return $null
    }

    return [int]$rawPid
}

function Stop-RecordedProcess {
    <#
    功能描述：
        按 PID 文件记录结束进程。若进程已退出，则仅报告真实状态，不伪造成功结果。

    :param Path: PID 文件路径。
    :param Label: 进程展示名称，用于输出日志。
    #>

    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [string]$Label
    )

    $targetPid = Get-RecordedPid -Path $Path
    if ($null -eq $targetPid) {
        Write-Host "$Label is not running."
        return
    }

    try {
        Stop-Process -Id $targetPid -Force -ErrorAction Stop
        Write-Host "$Label stopped. PID=$targetPid"
    }
    catch {
        Write-Host "$Label process not found. PID=$targetPid"
    }
}

if (-not (Test-Path $runtimeDir)) {
    Write-Host "EZComputerCtrl is not running. Runtime directory not found."
    exit 0
}

New-Item -ItemType File -Path $stopSignalFile -Force | Out-Null
Stop-RecordedProcess -Path $pidFile -Label "EZComputerCtrl service"
Start-Sleep -Milliseconds 500
Stop-RecordedProcess -Path $guardianPidFile -Label "EZComputerCtrl guardian"

Remove-RuntimeFile -Path $pidFile
Remove-RuntimeFile -Path $guardianPidFile
Remove-RuntimeFile -Path $stopSignalFile
