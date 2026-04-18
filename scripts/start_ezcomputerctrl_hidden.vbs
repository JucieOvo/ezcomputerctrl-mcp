' 模块名称：start_ezcomputerctrl_hidden
' 功能描述：
'   作为 Windows 下的隐藏启动入口，负责以不可见窗口方式启动 PowerShell 守护脚本。
'   默认进入保活模式，使业务进程在异常退出后可由守护脚本自动拉起。
' 作者：JucieOvo

Dim shell, fso, scriptDir, command

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
command = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File " & Chr(34) & scriptDir & "\run_ezcomputerctrl_http.ps1" & Chr(34) & " -KeepAlive"

shell.Run command, 0, False

Set fso = Nothing
Set shell = Nothing
