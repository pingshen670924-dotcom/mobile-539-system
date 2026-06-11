$ErrorActionPreference = "Continue"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$LogDir = Join-Path $ScriptDir "logs"
$RunLog = Join-Path $LogDir "auto_monitor.log"
$BundledPython = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$PythonCommand = "python"
if (-not (Get-Command $PythonCommand -ErrorAction SilentlyContinue)) {
  $PythonCommand = $BundledPython
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Get-ExpectedDrawDate {
  $Now = Get-Date
  $Candidate = $Now.Date
  if ($Now.TimeOfDay -lt [TimeSpan]::FromHours(21)) {
    $Candidate = $Candidate.AddDays(-1)
  }
  while ($Candidate.DayOfWeek -eq [DayOfWeek]::Sunday) {
    $Candidate = $Candidate.AddDays(-1)
  }
  return $Candidate.ToString("yyyy-MM-dd")
}

$LastCompletedDrawDate = ""
while ($true) {
  $ExpectedDrawDate = Get-ExpectedDrawDate
  if ($ExpectedDrawDate -ne $LastCompletedDrawDate) {
    "Monitor update started $(Get-Date -Format s), expected draw $ExpectedDrawDate" |
      Out-File -FilePath $RunLog -Encoding utf8 -Append
    & $PythonCommand (Join-Path $ScriptDir "update_539.py") --latest --require-fresh 2>&1 |
      Out-File -FilePath $RunLog -Encoding utf8 -Append
    if ($LASTEXITCODE -eq 0) {
      $LastCompletedDrawDate = $ExpectedDrawDate
      "Monitor update completed $(Get-Date -Format s)" | Out-File -FilePath $RunLog -Encoding utf8 -Append
    } else {
      "Monitor update failed; retrying in 15 minutes." | Out-File -FilePath $RunLog -Encoding utf8 -Append
    }
  }
  Start-Sleep -Seconds 900
}
