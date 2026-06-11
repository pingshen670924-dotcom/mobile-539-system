$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BundledPython = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$PythonCommand = "python"
if (-not (Get-Command $PythonCommand -ErrorAction SilentlyContinue)) {
  $PythonCommand = $BundledPython
}

netsh advfirewall firewall delete rule name="539 Mobile Control" | Out-Null
netsh advfirewall firewall add rule name="539 Mobile Control" dir=in action=allow protocol=TCP localport=5390 profile=private | Out-Null

$Action = New-ScheduledTaskAction -Execute $PythonCommand -Argument "`"$ScriptDir\mobile_server.py`"" -WorkingDirectory $ScriptDir
$Trigger = New-ScheduledTaskTrigger -AtLogOn
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName "539 Mobile Control Server" -Action $Action -Trigger $Trigger -Settings $Settings -Description "Run the 539 private Wi-Fi mobile control server." -Force | Out-Null

Start-Process -FilePath $PythonCommand -ArgumentList "`"$ScriptDir\mobile_server.py`"" -WorkingDirectory $ScriptDir -WindowStyle Hidden
Start-Sleep -Seconds 2

$Token = Get-Content (Join-Path $ScriptDir "data\mobile_access_token.txt")
$Address = Get-NetIPAddress -AddressFamily IPv4 |
  Where-Object { $_.IPAddress -notlike "127.*" -and $_.PrefixOrigin -ne "WellKnown" } |
  Select-Object -First 1 -ExpandProperty IPAddress
$MobileName = ([char]0x624B) + ([char]0x6A5F) + ([char]0x64CD) + ([char]0x4F5C) + ([char]0x7DB2) + ([char]0x5740) + ".txt"
$MobileUrl = "http://${Address}:5390/?token=${Token}"
Set-Content -Path (Join-Path $ScriptDir $MobileName) -Value $MobileUrl -Encoding UTF8

Write-Host "Mobile control enabled."
Write-Host "Connect the phone and computer to the same Wi-Fi."
Write-Host "Open:"
Write-Host $MobileUrl
pause
