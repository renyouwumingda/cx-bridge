# 把 cx-bridge 加进「登录时自动启动」（当前用户，不需要管理员）
# 用法：powershell -ExecutionPolicy Bypass -File install-autostart.ps1
$here = "C:\Users\10183\Desktop\ds\cx-bridge"
$vbs = Join-Path $here "start-hidden.vbs"
$startup = [Environment]::GetFolderPath("Startup")
$lnk = Join-Path $startup "cx-bridge.lnk"

$ws = New-Object -ComObject WScript.Shell
$s = $ws.CreateShortcut($lnk)
$s.TargetPath = "wscript.exe"
$s.Arguments = '"' + $vbs + '"'
$s.WorkingDirectory = $here
$s.WindowStyle = 7
$s.Description = "cx-bridge local bridge (127.0.0.1:8790)"
$s.Save()
Write-Host "autostart installed: $lnk"

$online = $false
try {
    Invoke-RestMethod -Uri "http://127.0.0.1:8790/ping" -TimeoutSec 2 | Out-Null
    $online = $true
} catch {
    $online = $false
}

if ($online) {
    Write-Host "service already running"
} else {
    Write-Host "starting service..."
    Start-Process -FilePath "wscript.exe" -ArgumentList ('"' + $vbs + '"') -WindowStyle Hidden
    Start-Sleep -Seconds 3
}

try {
    $r = Invoke-RestMethod -Uri "http://127.0.0.1:8790/ping" -TimeoutSec 5
    Write-Host ("online: engine=" + $r.engine + " model=" + $r.model)
} catch {
    Write-Host "not online, check $here\server.err.log"
}
