$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "run_539_once.ps1"

if (-not (Test-Path $Runner)) {
  throw "Runner was not found."
}

$Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-ExecutionPolicy Bypass -File `"$Runner`"" -WorkingDirectory $ScriptDir
$Trigger = New-ScheduledTaskTrigger -AtLogOn
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName "539 Startup Full Run" -Action $Action -Trigger $Trigger -Settings $Settings -Description "Run 539 full update, analysis, and dashboard when Windows user logs on." -Force | Out-Null

Write-Host "Startup task installed: 539 Startup Full Run"
