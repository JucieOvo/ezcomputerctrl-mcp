Dim shell, fso, scriptDir, command

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
command = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File """ & scriptDir & "\run_ezcomputerctrl_http.ps1"""

shell.Run command, 0, False

Set fso = Nothing
Set shell = Nothing
