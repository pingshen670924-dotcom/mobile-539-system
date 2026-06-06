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

  $TriggerTimes = @("21:05", "21:35", "22:05", "22:35", "23:05", "23:35")
  foreach ($TimeText in $TriggerTimes) {
    $TaskName = "539 Daily Latest Result Update " + $TimeText.Replace(":", "")
    $TaskCommand = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$Runner`""
    & schtasks.exe /Create /TN $TaskName /SC DAILY /ST $TimeText /TR $TaskCommand /F | Out-Host
    if ($LASTEXITCODE -ne 0) {
      throw "Failed to install daily task at $TimeText."
    }
  }

  Write-Host "Scheduled tasks installed: 539 Daily Latest Result Update"
  Write-Host "Daily triggers: 21:05, 21:35, 22:05, 22:35, 23:05, 23:35"
  Write-Host "This task runs independently from the Codex offline sandbox."
  exit 0
} catch {
  Write-Host $_
  exit 1
}
