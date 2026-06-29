$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $ScriptDir

$LogDir = Join-Path $ScriptDir "logs"
$ReportDir = Join-Path $ScriptDir "reports"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
New-Item -ItemType Directory -Force -Path $ReportDir | Out-Null

$LogPath = Join-Path $LogDir "daily_midnight_recompute.log"
$StatusPath = Join-Path $ReportDir "daily_midnight_recompute_status.json"
$MutexName = "Global\TW539DailyMidnightRecompute"
$Mutex = New-Object System.Threading.Mutex($false, $MutexName)
$HasMutex = $false

function Find-Python {
  $bundled = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
  if (Test-Path -LiteralPath $bundled) {
    return $bundled
  }
  $cmd = Get-Command python -ErrorAction SilentlyContinue
  if ($cmd) {
    return $cmd.Source
  }
  throw "Python executable was not found."
}

function Write-RecomputeLog {
  param([string]$Message)
  $line = "$(Get-Date -Format s) $Message"
  Write-Host $line
  $line | Out-File -FilePath $LogPath -Encoding utf8 -Append
}

function Save-Status {
  param([object]$State)
  $State["updated_at"] = (Get-Date -Format s)
  $State | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $StatusPath -Encoding UTF8
}

function Run-PythonStep {
  param(
    [string]$Label,
    [string[]]$Arguments,
    [bool]$Required = $true
  )
  Write-RecomputeLog $Label
  & $Python @Arguments 2>&1 | Tee-Object -FilePath $LogPath -Append | Out-Null
  $code = $LASTEXITCODE
  $result = [ordered]@{
    label = $Label
    exit_code = $code
    required = $Required
    finished_at = (Get-Date -Format s)
  }
  if ($code -ne 0 -and $Required) {
    throw "$Label failed with exit code $code."
  }
  return $result
}

function Start-CloudPublish {
  $publishScript = Join-Path $ScriptDir "publish_free_github.ps1"
  $result = [ordered]@{
    label = "publish_phone_cloud_site"
    status = "skipped"
    finished_at = (Get-Date -Format s)
  }
  if (-not (Test-Path -LiteralPath $publishScript)) {
    $result.message = "publish_script_not_found"
    return $result
  }
  try {
    & "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File $publishScript 2>&1 | Tee-Object -FilePath $LogPath -Append | Out-Null
    $result.exit_code = $LASTEXITCODE
    $result.status = if ($LASTEXITCODE -eq 0) { "ok" } else { "warning" }
  } catch {
    $result.status = "failed"
    $result.error = $_.Exception.Message
  }
  $result.finished_at = (Get-Date -Format s)
  return $result
}

$State = [ordered]@{
  status = "starting"
  rule = "每日00:00完整重算、完整回測、完整重建戰報與手機版"
  started_at = (Get-Date -Format s)
  updated_at = (Get-Date -Format s)
  root = $ScriptDir
  steps = @()
}

try {
  $HasMutex = $Mutex.WaitOne(0)
  if (-not $HasMutex) {
    $State.status = "duplicate_ignored"
    $State.message = "another midnight recompute is already running"
    Save-Status $State
    exit 0
  }

  $Python = Find-Python
  $State.status = "running"
  Save-Status $State

  $State.steps += Run-PythonStep "Compile check" @("-m", "py_compile", ".\update_539.py", ".\analyze_539.py", ".\battle_report.py", ".\industrial_engine.py", ".\daily_integrity_audit.py", ".\pages_build.py")
  $State.steps += Run-PythonStep "Midnight latest draw update and full recalculation" @(".\update_539.py", "--latest", "--require-fresh")
  $State.steps += Run-PythonStep "Model competition rebuild" @(".\model_competition.py") $false
  $State.steps += Run-PythonStep "Health check" @(".\health_check.py") $false
  $State.steps += Run-PythonStep "Daily integrity audit" @(".\daily_integrity_audit.py")
  $State.steps += Run-PythonStep "Final battle report rebuild" @(".\battle_report.py")
  $State.steps += Run-PythonStep "Phone site rebuild" @(".\pages_build.py")
  $State.steps += Run-PythonStep "Refresh phone live URL" @(".\mobile_server.py", "--write-url") $false
  $State.steps += Start-CloudPublish
  $State.steps += Run-PythonStep "Push LINE report" @(".\line_push.py") $false
  $State.steps += Run-PythonStep "File integrity and encoding check" @(".\system_file_check.py") $false

  $State.status = "completed"
  $State.finished_at = (Get-Date -Format s)
  Save-Status $State
  Write-RecomputeLog "Midnight recompute completed."
  exit 0
} catch {
  $State.status = "failed"
  $State.error = $_.Exception.Message
  $State.finished_at = (Get-Date -Format s)
  Save-Status $State
  Write-RecomputeLog "Midnight recompute failed: $($_.Exception.Message)"
  exit 1
} finally {
  if ($HasMutex) {
    $Mutex.ReleaseMutex()
  }
  $Mutex.Dispose()
}
