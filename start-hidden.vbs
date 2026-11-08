' cx-bridge 后台启动：无窗口、日志写 server.out.log / server.err.log
' 双击运行一次即可；开机自启用 install-autostart.ps1（或把本文件的快捷方式放进 shell:startup）
Dim sh, here, py
Set sh = CreateObject("WScript.Shell")
here = "C:\Users\10183\Desktop\ds\cx-bridge"
py = "C:\Users\10183\AppData\Local\Programs\Python\Python313\python.exe"
sh.CurrentDirectory = here
sh.Run "cmd /c """"" & py & """ server.py >> server.out.log 2>&1""", 0, False
