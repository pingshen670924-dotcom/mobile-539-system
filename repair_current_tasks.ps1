$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "run_539_once.ps1"
$MainRunner = Join-Path $ScriptDir "main_one_click.ps1"
$PostDrawMonitor = Join-Path $ScriptDir "post_draw_mobile_sync.ps1"
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
        ('$CurrentSync = "' + $PostDrawMonitor + '"'),
        'if (Test-Path -LiteralPath $CurrentSync) {',
        '  & "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File $CurrentSync -MaxMinutes 240 -IntervalSeconds 45',
        '  exit $LASTEXITCODE',
        '}',
        '',
        'exit 0'
      ) -join [Environment]::NewLine
      Set-Content -LiteralPath $path -Value $content -Encoding UTF8
      $result.status = "ok"
      $result.message = "legacy_task_forwarded_to_current_post_draw_sync"
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
      'import runpy',
      'import sys',
      '',
      ('CURRENT = r"' + $MobileServer + '"'),
      'if __name__ == "__main__":',
      '    sys.argv = [CURRENT] + sys.argv[1:]',
      '    runpy.run_path(CURRENT, run_name="__main__")'
    ) -join [Environment]::NewLine
    Set-Content -LiteralPath $legacyMobilePath -Value $py -Encoding ASCII
    $mobileResult.status = "ok"
    $mobileResult.message = "legacy_mobile_server_forwarded_to_current_system"
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

function Install-StartupFolderEntry {
  $result = [ordered]@{
    status = "pending"
    path = ""
    message = ""
  }
  try {
    $startupDir = [Environment]::GetFolderPath("Startup")
    if (-not $startupDir) {
      throw "Startup folder was not found."
    }
    New-Item -ItemType Directory -Force -Path $startupDir | Out-Null
    $startupFile = Join-Path $startupDir "TW539_Current_One_Click_Startup.bat"
    $bat = @(
      "@echo off",
      "cd /d `"$ScriptDir`"",
      "`"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe`" -NoProfile -ExecutionPolicy Bypass -File `"$MainRunner`""
    ) -join [Environment]::NewLine
    Set-Content -LiteralPath $startupFile -Value $bat -Encoding ASCII
    $result.status = "ok"
    $result.path = $startupFile
    $result.message = "startup_folder_entry_installed"
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
  mobile_server = $MobileServer
  tasks = @()
  mobile = $null
  startup_folder = $null
  obsolete_task_cleanup = @()
  legacy_forwarders = @()
}

if (-not (Test-Path -LiteralPath $Runner)) {
  throw "run_539_once.ps1 was not found."
}
if (-not (Test-Path -LiteralPath $PostDrawMonitor)) {
  throw "post_draw_mobile_sync.ps1 was not found."
}
if (-not (Test-Path -LiteralPath $MobileServer)) {
  throw "mobile_server.py was not found."
}

$PowerShell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$Python = Find-Python
$RunArgs = '-NoProfile -ExecutionPolicy Bypass -File "' + $Runner + '"'
$MainArgs = '-NoProfile -ExecutionPolicy Bypass -File "' + $MainRunner + '"'
$PostDrawArgs = '-NoProfile -ExecutionPolicy Bypass -File "' + $PostDrawMonitor + '" -MaxMinutes 240 -IntervalSeconds 45'
$DailyAction = New-CurrentAction -Execute $PowerShell -Argument $PostDrawArgs
$StartupAction = New-CurrentAction -Execute $PowerShell -Argument $MainArgs
$MobileAction = New-CurrentAction -Execute $Python -Argument ('"' + $MobileServer + '"')

$obsoleteTasks = @(
  "539 Daily Latest Result Update 2105",
  "539 Daily Latest Result Update 2135",
  "539 Daily Latest Result Update 2205",
  "539 Daily Latest Result Update 2235",
  "539 Daily Latest Result Update 2305",
  "539 Daily Latest Result Update 2335",
  "TW539 Current Daily Update 2105",
  "TW539 Current Daily Update 2135",
  "TW539 Current Daily Update 2205",
  "TW539 Current Daily Update 2235",
  "TW539 Current Daily Update 2305",
  "TW539 Current Daily Update 2335",
  "TW539_AUTO_DAILY_RUNNER",
  "TW539_One_Click_Report",
  "TW539_Research_Platform"
)
foreach ($obsoleteTask in $obsoleteTasks) {
  $status.obsolete_task_cleanup += Remove-ObsoleteTask -TaskName $obsoleteTask
}
$status.legacy_forwarders = Install-LegacyForwarders

$dailyTimes = @("20:35", "20:40", "20:45", "20:50", "20:55", "21:00", "21:10", "21:20", "21:30", "21:45", "22:00", "22:30", "23:00", "23:30", "00:10")
$dailyTriggers = @()
foreach ($timeText in $dailyTimes) {
  $dailyTriggers += New-ScheduledTaskTrigger -Daily -At $timeText
}
$status.tasks += Register-TaskWithFallback -TaskName "539 Daily Latest Result Update" -FallbackName "TW539 Current Daily Full Update" -Action $DailyAction -Triggers $dailyTriggers -Description "Start current TW539 post-draw immediate sync monitor, then rebuild desktop and phone report after fresh draw."

$singleTimes = @{
  "539 Daily Latest Result Update 2035" = "20:35"
  "539 Daily Latest Result Update 2045" = "20:45"
  "539 Daily Latest Result Update 2100" = "21:00"
  "539 Daily Latest Result Update 2115" = "21:15"
  "539 Daily Latest Result Update 2130" = "21:30"
  "539 Daily Latest Result Update 2200" = "22:00"
  "539 Daily Latest Result Update 2300" = "23:00"
}
foreach ($name in $singleTimes.Keys) {
  $trigger = New-ScheduledTaskTrigger -Daily -At $singleTimes[$name]
  $fallbackName = "TW" + $name.Replace("539 Daily Latest Result Update", "539 Current Daily Update")
  $status.tasks += Register-TaskWithFallback -TaskName $name -FallbackName $fallbackName -Action $DailyAction -Triggers @($trigger) -Description "Fallback current TW539 post-draw immediate phone sync monitor."
}

$startupTrigger = New-ScheduledTaskTrigger -AtLogOn
$status.tasks += Register-TaskWithFallback -TaskName "539 Startup Full Run" -FallbackName "TW539 Current Startup Full Run" -Action $StartupAction -Triggers @($startupTrigger) -Description "Run current TW539 full one click flow when Windows user logs on."
$status.tasks += Register-TaskWithFallback -TaskName "539 Mobile Control Server" -FallbackName "TW539 Current Mobile Server" -Action $MobileAction -Triggers @($startupTrigger) -Description "Run current TW539 phone report server."

$status.mobile = Restart-CurrentMobileServer -PythonPath $Python
$status.startup_folder = Install-StartupFolderEntry

try {
  & $Python $MobileServer "--write-url" | Out-Null
} catch {
}

$status | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $StatusPath -Encoding UTF8
$status.mobile | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $PhoneStatusPath -Encoding UTF8

$failed = @($status.tasks | Where-Object { $_.status -ne "ok" })
if ($status.startup_folder.status -eq "ok") {
  $failed = @($failed | Where-Object { $_.task -notin @("539 Startup Full Run", "539 Mobile Control Server") })
}
if ($status.mobile.status -ne "ok") {
  $failed += $status.mobile
}
if ($status.startup_folder.status -ne "ok") {
  $failed += $status.startup_folder
}
if ($failed.Count -gt 0) {
  Write-Host "Task repair finished with warnings."
  Write-Host $StatusPath
  exit 1
}

Write-Host "Task repair finished."
Write-Host $StatusPath
exit 0
