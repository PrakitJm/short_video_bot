# Windows side: keep WSL (Ubuntu) running so the autovideo services stay up — even if something terminates
# the distro (wsl --shutdown / --terminate, a closing app), it is started again within ~15 seconds.
# Install:  powershell -ExecutionPolicy Bypass -File \\wsl$\Ubuntu\home\aunny\projects\short_video_bot\scripts\install_windows_keepalive.ps1
# Turn off: Stop-ScheduledTask AutoVideo-KeepWSL; Unregister-ScheduledTask AutoVideo-KeepWSL -Confirm:$false
#           (to just restart WSL once: Stop-ScheduledTask AutoVideo-KeepWSL; wsl --shutdown; Start-ScheduledTask AutoVideo-KeepWSL)
$dir = Join-Path $env:LOCALAPPDATA "autovideo"
New-Item -ItemType Directory -Force -Path $dir | Out-Null
# The loop lives on the Windows disk: while WSL is down, \\wsl$ paths do not exist.
$loop = Join-Path $dir "keepwsl.ps1"
Set-Content -Path $loop -Encoding UTF8 -Value @'
while ($true) {
    & "$env:WINDIR\System32\wsl.exe" -d Ubuntu --exec /bin/sleep infinity
    Start-Sleep -Seconds 15
}
'@
$a = New-ScheduledTaskAction -Execute "$env:WINDIR\System32\conhost.exe" `
     -Argument "--headless $env:WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$loop`""
$t = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$s = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
     -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName "AutoVideo-KeepWSL" -Description "Keeps WSL (Ubuntu) running for autovideo; restarts it if it is shut down." `
     -Action $a -Trigger $t -Settings $s -Force | Out-Null
Start-ScheduledTask -TaskName "AutoVideo-KeepWSL"
(Get-ScheduledTask -TaskName "AutoVideo-KeepWSL").State
