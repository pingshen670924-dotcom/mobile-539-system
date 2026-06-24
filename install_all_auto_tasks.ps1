$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

$Repair = Join-Path $ScriptDir "repair_current_tasks.ps1"
if (-not (Test-Path -LiteralPath $Repair)) {
  throw "Task repair script was not found."
}

& "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File $Repair
if ($LASTEXITCODE -ne 0) {
  throw "Automatic task repair finished with warnings."
}

Write-Host "All automatic tasks were repaired to the current system."
