$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Repair = Join-Path $ScriptDir "repair_current_tasks.ps1"
if (-not (Test-Path -LiteralPath $Repair)) {
  throw "Task repair script was not found."
}

& "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File $Repair
exit $LASTEXITCODE
