# Runs elevated. Installs WSL2 + Ubuntu for the GA5 Q7 LXD container work.
$log = "C:\Users\24f20\Desktop\IITM-Subjects\TDS\ga5\wsl-install.log"
Start-Transcript -Path $log -Force

Write-Output "=== enabling features ==="
dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart
dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart

Write-Output "=== wsl --install ==="
wsl.exe --install --no-launch
Write-Output "wsl exit code: $LASTEXITCODE"

Write-Output "=== status ==="
wsl.exe --status
wsl.exe -l -v

Stop-Transcript
Write-Output ""
Write-Output "DONE. A REBOOT is required. This window closes in 20 seconds."
Start-Sleep -Seconds 20
