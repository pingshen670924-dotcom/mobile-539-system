$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$ReportDir = Join-Path $Root "reports"
$StatusPath = Join-Path $ReportDir "old_startup_admin_cleanup_status.json"
New-Item -ItemType Directory -Force -Path $ReportDir | Out-Null

$oldTaskNames = @(
  "539 Startup Full Run",
  "539 Mobile Control Server",
  "TW539_One_Click_Report",
  "TW539_Research_Platform",
  "539 Daily Latest Result Update 2105",
  "539 Daily Latest Result Update 2135",
  "539 Daily Latest Result Update 2205",
  "539 Daily Latest Result Update 2235",
  "539 Daily Latest Result Update 2305",
  "539 Daily Latest Result Update 2335"
)

$startup = [Environment]::GetFolderPath("Startup")
$oneClickName = "539" + (-join (@(0x4e00, 0x9375, 0x5168, 0x81ea, 0x52d5, 0x555f, 0x52d5) | ForEach-Object { [char]$_ })) + ".bat"
$oldStartupFiles = @(
  "539-startup-auto-run.bat",
  "TW539_Auto_Run.vbs"
)

$results = [ordered]@{
  cleaned_at = (Get-Date -Format s)
  kept = @(
    (Join-Path "C:\Users\MSI\Documents\Codex\539PredictionSystem" $oneClickName),
    (Join-Path $startup "TW539_Current_One_Click_Startup.bat"),
    "539 Daily Latest Result Update",
    "TW539 Current Daily Update 2105",
    "TW539 Current Daily Update 2135",
    "TW539 Current Daily Update 2205",
    "TW539 Current Daily Update 2235",
    "TW539 Current Daily Update 2305",
    "TW539 Current Daily Update 2335"
  )
  removed_tasks = @()
  failed_tasks = @()
  removed_startup_files = @()
  failed_startup_files = @()
}

foreach ($fileName in $oldStartupFiles) {
  $path = Join-Path $startup $fileName
  if (-not (Test-Path -LiteralPath $path)) {
    continue
  }
  try {
    Remove-Item -LiteralPath $path -Force -ErrorAction Stop
    $results.removed_startup_files += $path
  } catch {
    $results.failed_startup_files += [ordered]@{ path = $path; error = $_.Exception.Message }
  }
}

foreach ($taskName in $oldTaskNames) {
  $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
  if (-not $task) {
    continue
  }
  try {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction Stop
    $results.removed_tasks += $taskName
  } catch {
    try {
      schtasks.exe /Delete /TN $taskName /F | Out-Null
      if ($LASTEXITCODE -eq 0) {
        $results.removed_tasks += $taskName
      } else {
        $results.failed_tasks += [ordered]@{ task = $taskName; error = "schtasks_delete_failed_$LASTEXITCODE" }
      }
    } catch {
      $results.failed_tasks += [ordered]@{ task = $taskName; error = $_.Exception.Message }
    }
  }
}

$results | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $StatusPath -Encoding UTF8
Write-Host "Old startup cleanup finished."
Write-Host $StatusPath
