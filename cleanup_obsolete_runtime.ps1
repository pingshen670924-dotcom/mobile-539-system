$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$LogDir = Join-Path $Root "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$LogPath = Join-Path $LogDir "cleanup_obsolete_runtime.log"

function Write-CleanupLog {
  param([string]$Text)
  $Line = "$(Get-Date -Format s) $Text"
  Write-Host $Line
  $Line | Out-File -LiteralPath $LogPath -Encoding UTF8 -Append
}

function TextFromCodes {
  param([int[]]$Codes)
  return -join ($Codes | ForEach-Object { [char]$_ })
}

$FreeMobileFolder = TextFromCodes @(0x514d,0x8cbb,0x624b,0x6a5f,0x7368,0x7acb,0x7248)
$OldButtonFolder = (TextFromCodes @(0x5c01,0x5b58)) + "_" + (TextFromCodes @(0x820a,0x7684,0x4e00,0x9375,0x6309,0x9215))
$SingleLauncher = "539" + (TextFromCodes @(0x4e00,0x9375,0x5168,0x81ea,0x52d5,0x555f,0x52d5)) + ".bat"

$ObsoleteNames = @(
  "__pycache__",
  "cleanup_archive_20260615_094319",
  "cleanup_archive_20260615_094339",
  "cleanup_archive_20260615_094440",
  "cleanup_archive_20260615_094636",
  "539-mobile-cloud-deploy",
  $FreeMobileFolder,
  $OldButtonFolder
)

$Removed = @()
$Skipped = @()
foreach ($Name in $ObsoleteNames) {
  $Path = Join-Path $Root $Name
  if (-not (Test-Path -LiteralPath $Path)) {
    continue
  }
  try {
    $Resolved = (Resolve-Path -LiteralPath $Path).Path
    if (-not $Resolved.StartsWith($Root, [System.StringComparison]::OrdinalIgnoreCase)) {
      throw "Refuse outside root: $Resolved"
    }
    Remove-Item -LiteralPath $Resolved -Recurse -Force -ErrorAction Stop
    $Removed += $Name
    Write-CleanupLog "Removed obsolete folder: $Name"
  } catch {
    $Skipped += $Name
    Write-CleanupLog "Skipped obsolete folder: $Name / $($_.Exception.Message)"
  }
}

$ReleasePrefix = "TW539" + (TextFromCodes @(0x9810,0x6e2c,0x7cfb,0x7d71)) + "_"
$ReleaseItems = Get-ChildItem -LiteralPath $Root -Force -ErrorAction SilentlyContinue |
  Where-Object { $_.Name -like "$ReleasePrefix*" }
$KeptReleaseBase = ""
if ($ReleaseItems.Count -gt 0) {
  $LatestReleaseItem = $ReleaseItems | Sort-Object LastWriteTime -Descending | Select-Object -First 1
  $KeptReleaseBase = $LatestReleaseItem.Name -replace "\.zip$", ""
  foreach ($Item in $ReleaseItems) {
    $ItemBase = $Item.Name -replace "\.zip$", ""
    if ($ItemBase -eq $KeptReleaseBase) {
      continue
    }
    try {
      $Resolved = (Resolve-Path -LiteralPath $Item.FullName).Path
      if (-not $Resolved.StartsWith($Root, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refuse outside root: $Resolved"
      }
      Remove-Item -LiteralPath $Resolved -Recurse -Force -ErrorAction Stop
      $Removed += $Item.Name
      Write-CleanupLog "Removed old release item: $($Item.Name)"
    } catch {
      $Skipped += $Item.Name
      Write-CleanupLog "Skipped old release item: $($Item.Name) / $($_.Exception.Message)"
    }
  }
}

$Report = [ordered]@{
  cleaned_at = (Get-Date).ToString("s")
  root = $Root
  removed = $Removed
  skipped = $Skipped
  kept_single_launcher = $SingleLauncher
  kept_release_base = $KeptReleaseBase
  status = if ($Skipped.Count -eq 0) { "ok" } else { "partial" }
}
$ReportPath = Join-Path $Root "reports\cleanup_obsolete_runtime.json"
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $ReportPath) | Out-Null
$Report | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $ReportPath -Encoding UTF8
if ($Skipped.Count -gt 0) {
  exit 2
}
exit 0
