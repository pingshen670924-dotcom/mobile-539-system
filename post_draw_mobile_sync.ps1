param(
  [int]$MaxMinutes = 240,
  [int]$IntervalSeconds = 45
)

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $ScriptDir

$LogDir = Join-Path $ScriptDir "logs"
$ReportDir = Join-Path $ScriptDir "reports"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
New-Item -ItemType Directory -Force -Path $ReportDir | Out-Null

$LogPath = Join-Path $LogDir "post_draw_mobile_sync.log"
$StatusPath = Join-Path $ReportDir "post_draw_mobile_sync_status.json"
$MutexName = "Global\TW539PostDrawImmediateMobileSync"
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

function Write-SyncLog {
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

function Read-AnalysisFreshness {
  $analysisPath = Join-Path $ReportDir "latest_analysis.json"
  if (-not (Test-Path -LiteralPath $analysisPath)) {
    return [ordered]@{
      status = "missing"
      latest_date = $null
      expected_latest_date = $null
      latest_period = $null
    }
  }
  try {
    $analysis = Get-Content -LiteralPath $analysisPath -Encoding UTF8 -Raw | ConvertFrom-Json
    $freshness = $analysis.data_freshness
    return [ordered]@{
      status = [string]$freshness.status
      latest_date = [string]$freshness.latest_date
      expected_latest_date = [string]$freshness.expected_latest_date
      latest_period = $analysis.latest_draw.period
      generated_at = $analysis.generated_at
    }
  } catch {
    return [ordered]@{
      status = "unreadable"
      latest_date = $null
      expected_latest_date = $null
      latest_period = $null
      error = $_.Exception.Message
    }
  }
}

function Run-PythonStep {
  param(
    [string]$Label,
    [string[]]$Arguments,
    [bool]$Required = $false
  )
  Write-SyncLog $Label
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

function Run-PowerShellStep {
  param(
    [string]$Label,
    [string]$ScriptPath
  )
  $result = [ordered]@{
    label = $Label
    exit_code = 0
    finished_at = (Get-Date -Format s)
  }
  if (-not (Test-Path -LiteralPath $ScriptPath)) {
    $result.exit_code = 2
    $result.message = "script_not_found"
    return $result
  }
  Write-SyncLog $Label
  & "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File $ScriptPath 2>&1 | Tee-Object -FilePath $LogPath -Append | Out-Null
  $result.exit_code = $LASTEXITCODE
  $result.finished_at = (Get-Date -Format s)
  return $result
}

function Ensure-MobileServer {
  $mobileServer = Join-Path $ScriptDir "mobile_server.py"
  $result = [ordered]@{
    label = "ensure_mobile_server"
    status = "pending"
    stopped_stale_processes = @()
    started = $false
  }
  try {
    $currentListening = $false
    $listeners = @(Get-NetTCPConnection -LocalPort 5390 -State Listen -ErrorAction SilentlyContinue)
    foreach ($listener in $listeners) {
      $pidValue = [int]$listener.OwningProcess
      if ($pidValue -le 0) {
        continue
      }
      $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$pidValue" -ErrorAction SilentlyContinue
      $commandLine = ""
      if ($proc) {
        $commandLine = [string]$proc.CommandLine
      }
      if ($commandLine -match "mobile_server\.py" -and $commandLine -notlike "*$ScriptDir*") {
        try {
          Stop-Process -Id $pidValue -Force -ErrorAction Stop
          $result.stopped_stale_processes += $pidValue
        } catch {
        }
      } elseif ($commandLine -match "mobile_server\.py") {
        $currentListening = $true
      }
    }
    if (-not $currentListening) {
      Start-Process -FilePath $Python -ArgumentList ('"' + $mobileServer + '"') -WorkingDirectory $ScriptDir -WindowStyle Hidden
      Start-Sleep -Seconds 2
      $result.started = $true
    }
    $result.status = "ok"
  } catch {
    $result.status = "failed"
    $result.error = $_.Exception.Message
  }
  return $result
}

function Start-CloudPublish {
  $publishScript = Join-Path $ScriptDir "publish_free_github.ps1"
  $result = [ordered]@{
    label = "start_cloud_phone_publish"
    status = "pending"
    started = $false
    finished_at = (Get-Date -Format s)
  }
  if (-not (Test-Path -LiteralPath $publishScript)) {
    $result.status = "skipped"
    $result.message = "publish_script_not_found"
    return $result
  }
  try {
    & "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File $publishScript *> $null
    $result.started = $true
    if ($LASTEXITCODE -eq 0) {
      $result.status = "ok"
      $result.message = "cloud_publish_finished"
    } else {
      $result.status = "failed"
      $result.error = "cloud_publish_exit_code_$LASTEXITCODE"
    }
  } catch {
    $result.status = "failed"
    $result.error = $_.Exception.Message
  }
  return $result
}

function Complete-FreshSync {
  $steps = @()
  $steps += Run-PythonStep "Rebuild battle report after fresh draw" @(".\battle_report.py") $true
  $steps += Run-PythonStep "Rebuild model competition" @(".\model_competition.py") $false
  $steps += Run-PythonStep "Health check" @(".\health_check.py") $false
  $steps += Run-PythonStep "Daily integrity audit" @(".\daily_integrity_audit.py") $false
  $steps += Run-PythonStep "Rebuild battle report after audit" @(".\battle_report.py") $true
  $steps += Run-PythonStep "Rebuild phone site files" @(".\pages_build.py") $false
  $steps += Ensure-MobileServer
  $steps += Run-PythonStep "Refresh phone live URL" @(".\mobile_server.py", "--write-url") $false
  $steps += Start-CloudPublish
  $steps += Run-PythonStep "Push LINE report" @(".\line_push.py") $false
  $steps += Run-PythonStep "File integrity and encoding check" @(".\system_file_check.py") $false
  return $steps
}

$State = [ordered]@{
  status = "starting"
  started_at = (Get-Date -Format s)
  updated_at = (Get-Date -Format s)
  draw_time = "20:33"
  completion_deadline = "20:45"
  rule = "20:33開獎後立即追最新資料；20:45前完成開獎匯入、命中結算、重新運算、回測、戰報與手機版同步。"
  root = $ScriptDir
  max_minutes = $MaxMinutes
  interval_seconds = $IntervalSeconds
  attempts = 0
  freshness = $null
  steps = @()
}

try {
  $HasMutex = $Mutex.WaitOne(0)
  if (-not $HasMutex) {
    $State.status = "duplicate_ignored"
    $State.message = "another post-draw sync is already running"
    Save-Status $State
    exit 0
  }

  $Python = Find-Python
  $deadline = (Get-Date).AddMinutes($MaxMinutes)
  $State.status = "watching_for_fresh_draw"
  Save-Status $State

  while ((Get-Date) -lt $deadline) {
    $State.attempts += 1
    $State.status = "updating_latest_draw"
    Save-Status $State

    $updateResult = Run-PythonStep "Post-draw latest draw update attempt $($State.attempts)" @(
      ".\update_539.py",
      "--latest",
      "--require-fresh",
      "--retry-until-fresh-minutes",
      "2",
      "--retry-interval-seconds",
      [string]$IntervalSeconds
    ) $false
    $State.steps += $updateResult
    $State.freshness = Read-AnalysisFreshness
    Save-Status $State

    if ($updateResult.exit_code -eq 0 -and $State.freshness.status -eq "fresh") {
      $State.status = "fresh_draw_imported_rebuilding_outputs"
      Save-Status $State
      $State.steps += Complete-FreshSync
      $State.freshness = Read-AnalysisFreshness
      $State.status = "fresh_synced_to_desktop_and_phone"
      $State.finished_at = (Get-Date -Format s)
      Save-Status $State
      Write-SyncLog "Fresh draw synced to desktop and phone."
      exit 0
    }

    $State.status = "fresh_draw_not_available_yet_retrying"
    Save-Status $State
    $remainingSeconds = [Math]::Max([int]($deadline - (Get-Date)).TotalSeconds, 0)
    if ($remainingSeconds -le 0) {
      break
    }
    Start-Sleep -Seconds ([Math]::Min([Math]::Max($IntervalSeconds, 30), $remainingSeconds))
  }

  $State.status = "timed_out_waiting_for_fresh_draw"
  $State.finished_at = (Get-Date -Format s)
  Save-Status $State
  Write-SyncLog "Post-draw sync timed out before fresh draw was imported."
  exit 1
} catch {
  $State.status = "failed"
  $State.error = $_.Exception.Message
  $State.finished_at = (Get-Date -Format s)
  Save-Status $State
  Write-SyncLog "Post-draw sync failed: $($_.Exception.Message)"
  exit 1
} finally {
  if ($HasMutex) {
    $Mutex.ReleaseMutex()
  }
  $Mutex.Dispose()
}
