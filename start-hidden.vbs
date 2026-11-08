' cx-bridge 后台启动：无窗口、日志写 server.out.log / server.err.log
' 双击运行一次即可；开机自启用 install-autostart.ps1（或把本文件的快捷方式放进 shell:startup）
Dim sh, here, py
Set sh = CreateObject("WScript.Shell")
here = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
py = "python"
sh.CurrentDirectory = here
sh.Run "cmd /c """"" & py & """ server.py >> server.out.log 2>&1""", 0, False
