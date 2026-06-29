$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "run_539_once.ps1"
$MainRunner = Join-Path $ScriptDir "main_one_click.ps1"
$PostDrawMonitor = Join-Path $ScriptDir "post_draw_mobile_sync.ps1"
$MidnightRecompute = Join-Path $ScriptDir "daily_midnight_recompute.ps1"
$MobileServer = Join-Path $ScriptDir "mobile_server.py"
$ReportsDir = Join-Path $ScriptDir "reports"
$StatusPath = Join-Path $ReportsDir "task_repair_status.json"
$PhoneStatusPath = Join-Path $ReportsDir "mobile_update_status.json"

New-Item -ItemType Directory -Force -Path $ReportsDir | Out-Null

function Find-Python {
  $bundled = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
  if (Test-Path -LiteralPath $bundled) {
    return $bundled
  }
  $cmd = Get-Command python -ErrorAction SilentlyContinue
  if ($cmd) {
    return $cmd.Source
  }
  return "python"
}

function New-CurrentAction {
  param(
    [string]$Execute,
    [string]$Argument
  )
  try {
    return New-ScheduledTaskAction -Execute $Execute -Argument $Argument -WorkingDirectory $ScriptDir
  } catch {
    return New-ScheduledTaskAction -Execute $Execute -Argument $Argument
  }
}

function Register-TaskSafe {
  param(
    [string]$TaskName,
    [Microsoft.Management.Infrastructure.CimInstance]$Action,
    [object[]]$Triggers,
    [string]$Description
  )
  $result = [ordered]@{
    task = $TaskName
    status = "pending"
    message = ""
  }
  try {
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Triggers -Settings $settings -Description $Description -Force -ErrorAction Stop | Out-Null
    $result.status = "ok"
    $result.message = "registered_to_current_system"
  } catch {
    $result.status = "failed"
    $result.message = $_.Exception.Message
  }
  return $result
}

function Register-TaskWithFallback {
  param(
    [string]$TaskName,
    [string]$FallbackName,
    [Microsoft.Management.Infrastructure.CimInstance]$Action,
    [object[]]$Triggers,
    [string]$Description
  )
  $primary = Register-TaskSafe -TaskName $TaskName -Action $Action -Triggers $Triggers -Description $Description
  if ($primary.status -eq "ok") {
    return $primary
  }
  $fallback = Register-TaskSafe -TaskName $FallbackName -Action $Action -Triggers $Triggers -Description $Description
  $combined = [ordered]@{
    task = $TaskName
    status = $fallback.status
    message = $fallback.message
    fallback_task = $FallbackName
    primary_status = $primary.status
    primary_message = $primary.message
  }
  if ($fallback.status -eq "ok") {
    $combined.message = "primary_locked_fallback_registered"
  }
  return $combined
}

function Remove-ObsoleteTask {
  param([string]$TaskName)
  $result = [ordered]@{
    task = $TaskName
    status = "not_found"
    message = ""
  }
  $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
  if (-not $task) {
    return $result
  }
  try {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction Stop
    $result.status = "removed"
    $result.message = "removed_by_register_scheduled_task"
    return $result
  } catch {
    $result.message = $_.Exception.Message
  }
  try {
    schtasks.exe /Delete /TN $TaskName /F 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) {
      $result.status = "removed"
      $result.message = "removed_by_schtasks"
    } else {
      $result.status = "failed"
      $result.message = "schtasks_delete_failed_$LASTEXITCODE"
    }
  } catch {
    $result.status = "failed"
    $result.message = $_.Exception.Message
  }
  return $result
}

function Install-LegacyForwarders {
  $results = @()
  $packageOutName = -join @([char]0x5C01, [char]0x5305, [char]0x8F38, [char]0x51FA)
  $codexRoot = Split-Path -Parent $ScriptDir
  $legacyStartupName = "539" + (-join @([char]0x4E3B, [char]0x7CFB, [char]0x7D71, [char]0x5F, [char]0x6392, [char]0x7A0B, [char]0x8207, [char]0x624B, [char]0x6A5F, [char]0x5165, [char]0x53E3, [char]0x4FEE, [char]0x6B63, [char]0x7248)) + "_20260611_095431"
  $legacyPaths = @(
    (Join-Path (Join-Path $ScriptDir $packageOutName) "539-aerospace-v36-assurance-20260606141635\run_539_once.ps1"),
    (Join-Path (Join-Path $codexRoot $legacyStartupName) "run_539_once.ps1")
  )
  foreach ($path in $legacyPaths) {
    $result = [ordered]@{
      path = $path
      status = "pending"
      message = ""
    }
    try {
      $parent = Split-Path -Parent $path
      New-Item -ItemType Directory -Force -Path $parent | Out-Null
      $content = @(
        '$ErrorActionPreference = "Continue"',
        '[Console]::OutputEncoding = [System.Text.Encoding]::UTF8',
        '$OutputEncoding = [System.Text.Encoding]::UTF8',
        '',
        '"Legacy TW539 task disabled. Current active tasks are TW539 2045 Deadline Post Draw Sync and TW539 0000 Midnight Full Recompute." | Out-Null',
        'exit 0'
      ) -join [Environment]::NewLine
      Set-Content -LiteralPath $path -Value $content -Encoding UTF8
      $result.status = "ok"
      $result.message = "legacy_task_disabled_noop"
    } catch {
      $result.status = "failed"
      $result.message = $_.Exception.Message
    }
    $results += $result
  }
  $legacyMobilePath = Join-Path $codexRoot "2026-06-01\539\outputs\539-mobile-fully-independent-pwa-v21-20260604\mobile_server.py"
  $mobileResult = [ordered]@{
    path = $legacyMobilePath
    status = "pending"
    message = ""
  }
  try {
    $parent = Split-Path -Parent $legacyMobilePath
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    $py = @(
      '"""Legacy TW539 mobile server task disabled.',
      'Current phone sync is rebuilt by the active post-draw and midnight tasks."""',
      '',
      'if __name__ == "__main__":',
      '    raise SystemExit(0)'
    ) -join [Environment]::NewLine
    Set-Content -LiteralPath $legacyMobilePath -Value $py -Encoding ASCII
    $mobileResult.status = "ok"
    $mobileResult.message = "legacy_mobile_server_disabled_noop"
  } catch {
    $mobileResult.status = "failed"
    $mobileResult.message = $_.Exception.Message
  }
  $results += $mobileResult
  return $results
}

function Restart-CurrentMobileServer {
  param([string]$PythonPath)
  $result = [ordered]@{
    status = "pending"
    stopped_processes = @()
    started = $false
    message = ""
  }
  try {
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
      if ($commandLine -match "mobile_server\.py") {
        try {
          Stop-Process -Id $pidValue -Force -ErrorAction Stop
          $result.stopped_processes += $pidValue
        } catch {
        }
      }
    }
    Start-Sleep -Milliseconds 800
    Start-Process -FilePath $PythonPath -ArgumentList ('"' + $MobileServer + '"') -WorkingDirectory $ScriptDir -WindowStyle Hidden
    Start-Sleep -Seconds 2
    $result.started = $true
    $result.status = "ok"
    $result.message = "current_mobile_server_started"
  } catch {
    $result.status = "failed"
    $result.message = $_.Exception.Message
  }
  return $result
}

function Remove-StartupFolderEntries {
  $result = [ordered]@{
    status = "ok"
    removed = @()
    failed = @()
    message = ""
  }
  try {
    $startupDir = [Environment]::GetFolderPath("Startup")
    if (-not $startupDir) {
      $result.message = "startup_folder_not_found"
      return $result
    }
    $patterns = @("TW539*.bat", "539*.bat", "*539*.lnk", "*TW539*.lnk")
    foreach ($pattern in $patterns) {
      Get-ChildItem -LiteralPath $startupDir -Filter $pattern -ErrorAction SilentlyContinue | ForEach-Object {
        try {
          Remove-Item -LiteralPath $_.FullName -Force -ErrorAction Stop
          $result.removed += $_.FullName
        } catch {
          $result.failed += [ordered]@{ path = $_.FullName; error = $_.Exception.Message }
        }
      }
    }
    if ($result.failed.Count -gt 0) {
      $result.status = "warning"
      $result.message = "some_startup_entries_could_not_be_removed"
    } else {
      $result.message = "startup_entries_removed_or_not_found"
    }
  } catch {
    $result.status = "failed"
    $result.message = $_.Exception.Message
  }
  return $result
}

$status = [ordered]@{
  repaired_at = (Get-Date -Format s)
  root = $ScriptDir
  runner = $Runner
  main_runner = $MainRunner
  post_draw_monitor = $PostDrawMonitor
  midnight_recompute = $MidnightRecompute
  mobile_server = $MobileServer
  tasks = @()
  mobile = $null
  startup_folder_cleanup = $null
  obsolete_task_cleanup = @()
  legacy_forwarders = @()
}

if (-not (Test-Path -LiteralPath $Runner)) {
  throw "run_539_once.ps1 was not found."
}
if (-not (Test-Path -LiteralPath $PostDrawMonitor)) {
  throw "post_draw_mobile_sync.ps1 was not found."
}
if (-not (Test-Path -LiteralPath $MidnightRecompute)) {
  throw "daily_midnight_recompute.ps1 was not found."
}
if (-not (Test-Path -LiteralPath $MobileServer)) {
  throw "mobile_server.py was not found."
}

$PowerShell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$Python = Find-Python
$RunArgs = '-NoProfile -ExecutionPolicy Bypass -File "' + $Runner + '"'
$MainArgs = '-NoProfile -ExecutionPolicy Bypass -File "' + $MainRunner + '"'
$PostDrawArgs = '-NoProfile -ExecutionPolicy Bypass -File "' + $PostDrawMonitor + '" -MaxMinutes 12 -IntervalSeconds 30'
$MidnightArgs = '-NoProfile -ExecutionPolicy Bypass -File "' + $MidnightRecompute + '"'
$DailyAction = New-CurrentAction -Execute $PowerShell -Argument $PostDrawArgs
$MidnightAction = New-CurrentAction -Execute $PowerShell -Argument $MidnightArgs
$StartupAction = New-CurrentAction -Execute $PowerShell -Argument $MainArgs
$MobileAction = New-CurrentAction -Execute $Python -Argument ('"' + $MobileServer + '"')

$obsoleteTasks = @(
  "539 Daily Latest Result Update 2105",
  "539 Daily Latest Result Update 2135",
  "539 Daily Latest Result Update 2205",
  "539 Daily Latest Result Update 2235",
  "539 Daily Latest Result Update 2305",
  "539 Daily Latest Result Update 2335",
  "539 Daily Latest Result Update 2035",
  "539 Daily Latest Result Update 2040",
  "539 Daily Latest Result Update 2045",
  "539 Daily Latest Result Update 2050",
  "539 Daily Latest Result Update 2055",
  "539 Daily Latest Result Update 2100",
  "539 Daily Latest Result Update 2115",
  "539 Daily Latest Result Update 2130",
  "539 Daily Latest Result Update 2200",
  "539 Daily Latest Result Update 2300",
  "TW539 Current Daily Update 2105",
  "TW539 Current Daily Update 2135",
  "TW539 Current Daily Update 2205",
  "TW539 Current Daily Update 2235",
  "TW539 Current Daily Update 2305",
  "TW539 Current Daily Update 2335",
  "TW539_AUTO_DAILY_RUNNER",
  "TW539_One_Click_Report",
  "TW539_Research_Platform",
  "539 Startup Full Run",
  "TW539 Current Startup Full Run",
  "539 Mobile Control Server",
  "TW539 Current Mobile Server",
  "TW539每日2045更新完成任務",
  "TW539每日0000完整重算任務",
  "TW539 2045 Deadline Post Draw Sync",
  "TW539 0000 Midnight Full Recompute"
)
foreach ($obsoleteTask in $obsoleteTasks) {
  $status.obsolete_task_cleanup += Remove-ObsoleteTask -TaskName $obsoleteTask
}
$status.legacy_forwarders = Install-LegacyForwarders

$dailyTimes = @("20:33")
$dailyTriggers = @()
foreach ($timeText in $dailyTimes) {
  $dailyTriggers += New-ScheduledTaskTrigger -Daily -At $timeText
}
$status.tasks += Register-TaskWithFallback -TaskName "TW539每日2045更新完成任務" -FallbackName "TW539 2045 Deadline Post Draw Sync" -Action $DailyAction -Triggers $dailyTriggers -Description "20:33 draw rule. Start at 20:33, retry every 30 seconds, import latest draw, recalculate models, rebuild desktop report, phone page, cloud page and LINE before the 20:45 deadline when official data is available."

$midnightTrigger = New-ScheduledTaskTrigger -Daily -At "00:00"
$status.tasks += Register-TaskWithFallback -TaskName "TW539每日0000完整重算任務" -FallbackName "TW539 0000 Midnight Full Recompute" -Action $MidnightAction -Triggers @($midnightTrigger) -Description "Run full midnight recalculation, backtesting, integrity audit, battle report rebuild and phone/cloud sync."

$status.mobile = Restart-CurrentMobileServer -PythonPath $Python
$status.startup_folder_cleanup = Remove-StartupFolderEntries

try {
  & $Python $MobileServer "--write-url" | Out-Null
} catch {
}

$status | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $StatusPath -Encoding UTF8
$status.mobile | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $PhoneStatusPath -Encoding UTF8

$failed = @($status.tasks | Where-Object { $_.status -ne "ok" })
if ($status.mobile.status -ne "ok") {
  $failed += $status.mobile
}
if ($status.startup_folder_cleanup.status -eq "failed") {
  $failed += $status.startup_folder_cleanup
}
if ($failed.Count -gt 0) {
  Write-Host "Task repair finished with warnings."
  Write-Host $StatusPath
  exit 1
}

Write-Host "Task repair finished."
Write-Host $StatusPath
exit 0
