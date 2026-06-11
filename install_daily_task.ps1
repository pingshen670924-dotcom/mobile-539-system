$ErrorActionPreference = "Stop"

try {
  $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
  $Runner = Join-Path $ScriptDir "run_539_once.ps1"

  $CurrentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
  $Principal = New-Object Security.Principal.WindowsPrincipal($CurrentIdentity)
  if (-not $Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Administrator permission is required to install the independent update task."
  }

  if (-not (Test-Path $Runner)) {
    throw "Runner was not found."
  }

  $TaskName = "539 Daily Latest Result Update"
  $ActionArguments = '-NoProfile -ExecutionPolicy Bypass -File "' + $Runner + '"'
  $Action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument $ActionArguments `
    -WorkingDirectory $ScriptDir

  $TriggerTimes = @("21:05", "21:35", "22:05", "22:35", "23:05", "23:35")
  $Triggers = @(
    foreach ($TimeText in $TriggerTimes) {
      New-ScheduledTaskTrigger -Daily -At $TimeText
    }
  )
  $Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -MultipleInstances IgnoreNew

  Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Triggers `
    -Settings $Settings `
    -Description "Run 539 update and analysis after the daily draw." `
    -Force | Out-Null

  Write-Host "Scheduled task installed: $TaskName"
  Write-Host "Daily triggers: 21:05, 21:35, 22:05, 22:35, 23:05, 23:35"
  Write-Host "This task runs independently from the Codex offline sandbox."
  exit 0
} catch {
  Write-Host $_
  exit 1
}
