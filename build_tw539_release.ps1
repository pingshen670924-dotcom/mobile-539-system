param(
  [string]$Version = "",
  [string]$DateText = (Get-Date -Format "yyyyMMdd"),
  [switch]$Recalculate
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

function TextFromCodes {
  param([int[]]$Codes)
  return -join ($Codes | ForEach-Object { [char]$_ })
}

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

function Run-Step {
  param([string]$Label, [string[]]$Arguments)
  Write-Host "== $Label =="
  Push-Location $SourceCore
  try {
    & $Python @Arguments
    if ($LASTEXITCODE -ne 0) {
      throw "$Label failed."
    }
  } finally {
    Pop-Location
  }
}

function Run-Optional-Step {
  param([string]$Label, [string[]]$Arguments)
  Write-Host "== $Label =="
  Push-Location $SourceCore
  try {
    & $Python @Arguments
    if ($LASTEXITCODE -ne 0) {
      Write-Warning "$Label finished with warnings. Health check will decide whether prediction can be published."
    }
  } catch {
    Write-Warning "$Label failed: $($_.Exception.Message). Health check will decide whether prediction can be published."
  } finally {
    Pop-Location
  }
}

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$NameMiddle = TextFromCodes @(0x9810,0x6e2c,0x7cfb,0x7d71)
$EditionPrefix = TextFromCodes @(0x7b2c)
$EditionSuffix = TextFromCodes @(0x7248)
$OneClick = TextFromCodes @(0x4e00,0x9375,0x7248)
$LauncherName = "539" + (TextFromCodes @(0x4e00,0x9375,0x5168,0x81ea,0x52d5,0x555f,0x52d5)) + ".bat"
$ReleasePrefix = "TW539${NameMiddle}_"

if (-not $Version) {
  $versionNumbers = @()
  $versionRegex = [regex]::Escape($EditionPrefix) + "(\d{2})" + [regex]::Escape($EditionSuffix)
  Get-ChildItem -LiteralPath $Root -Force | Where-Object { $_.Name -like "$ReleasePrefix$DateText*" } | ForEach-Object {
    if ($_.Name -match $versionRegex) {
      $versionNumbers += [int]$Matches[1]
    }
  }
  $nextVersion = 1
  if ($versionNumbers.Count -gt 0) {
    $nextVersion = ($versionNumbers | Measure-Object -Maximum).Maximum + 1
  }
  $Version = "{0:00}" -f $nextVersion
}

$SourceCore = $Root

$ReleaseName = "TW539${NameMiddle}_${DateText}_${EditionPrefix}${Version}${EditionSuffix}_${OneClick}"
$ReleaseDir = Join-Path $Root $ReleaseName
$ZipPath = Join-Path $Root ($ReleaseName + ".zip")
if (Test-Path -LiteralPath $ReleaseDir) {
  throw "Release folder already exists: $ReleaseDir"
}
if (Test-Path -LiteralPath $ZipPath) {
  throw "Release zip already exists: $ZipPath"
}

$Python = Find-Python
Run-Step "Compile check" @("-m", "py_compile", ".\update_539.py", ".\analyze_539.py", ".\battle_report.py", ".\health_check.py", ".\pages_build.py", ".\industrial_engine.py", ".\model_competition.py", ".\system_file_check.py", ".\mobile_server.py")
if ($Recalculate) {
  Run-Optional-Step "Update latest draw before recalculation" @(".\update_539.py", "--latest")
  Run-Step "Recalculate analysis" @(".\analyze_539.py")
  Run-Step "Model competition" @(".\model_competition.py")
  Run-Step "Health check" @(".\health_check.py")
  Run-Step "Battle report" @(".\battle_report.py")
  Run-Step "Mobile site" @(".\pages_build.py")
} else {
  Write-Host "== Package current calculated outputs =="
  Run-Step "Battle report" @(".\battle_report.py")
  Run-Step "Mobile site" @(".\pages_build.py")
}
Run-Step "Mobile phone link" @(".\mobile_server.py", "--write-url")
Run-Step "File integrity" @(".\system_file_check.py")

New-Item -ItemType Directory -Path $ReleaseDir | Out-Null
$Launcher = @(
  "@echo off",
  "chcp 65001 >nul",
  "cd /d `"%~dp0TW539Core`"",
  "`"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe`" -NoProfile -ExecutionPolicy Bypass -File `"%CD%\main_one_click.ps1`"",
  "set `"REPORT=%~dp0TW539Core\reports\latest_battle_report.html`"",
  "if exist `"%REPORT%`" start `"`" `"%REPORT%`""
) -join [Environment]::NewLine
Set-Content -LiteralPath (Join-Path $ReleaseDir $LauncherName) -Value $Launcher -Encoding ASCII

$Core = Join-Path $ReleaseDir "TW539Core"
New-Item -ItemType Directory -Path $Core | Out-Null
$SkipRootNames = @("logs", "__pycache__", "backups", ".git", ".agents", ".codex")
Get-ChildItem -LiteralPath $SourceCore -Force | Where-Object {
  $_.Name -notin $SkipRootNames -and
  -not ($_.Name -like "$ReleasePrefix*") -and
  $_.Extension -ne ".zip"
} | ForEach-Object {
  Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $Core $_.Name) -Recurse -Force
}
$LogSource = Join-Path $SourceCore "logs"
$LogTarget = Join-Path $Core "logs"
New-Item -ItemType Directory -Path $LogTarget | Out-Null
if (Test-Path -LiteralPath $LogSource) {
  Get-ChildItem -LiteralPath $LogSource -File | Where-Object { $_.Extension -ne ".lock" } | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $LogTarget $_.Name) -Force
  }
}

$ReportName = "539" + (TextFromCodes @(0x6700,0x65b0,0x5f37,0x5316,0x6230,0x5831)) + ".html"
$CoreReport = Join-Path (Join-Path $Core "reports") $ReportName
if (Test-Path -LiteralPath $CoreReport) {
  Copy-Item -LiteralPath $CoreReport -Destination (Join-Path $ReleaseDir $ReportName) -Force
}

$MobileEntryName = (TextFromCodes @(0x6253,0x958b,0x6700,0x65b0,0x624b,0x6a5f,0x7248)) + ".html"
$VersionPath = Join-Path $Core "site\version.json"
$MobileVersion = Get-Date -Format "yyyyMMddHHmmss"
if (Test-Path -LiteralPath $VersionPath) {
  try {
    $MobileVersion = (Get-Content -LiteralPath $VersionPath -Raw -Encoding UTF8 | ConvertFrom-Json).version
  } catch {
    $MobileVersion = Get-Date -Format "yyyyMMddHHmmss"
  }
}
$PackageMobileUrl = "TW539Core/site/clear-cache.html?v=$MobileVersion&t=$MobileVersion"
$PackageMobileEntry = @"
<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta http-equiv="Cache-Control" content="no-store, no-cache, must-revalidate, max-age=0">
  <meta http-equiv="Pragma" content="no-cache">
  <meta http-equiv="Expires" content="0">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>&#25171;&#38283;&#26368;&#26032;&#25163;&#27231;&#29256;</title>
  <meta http-equiv="refresh" content="0; url=$PackageMobileUrl">
</head>
<body>
  <p>&#27491;&#22312;&#25171;&#38283;&#26368;&#26032;&#25163;&#27231;&#29256;...</p>
  <p><a href="$PackageMobileUrl">&#33509;&#27794;&#26377;&#33258;&#21205;&#36339;&#36681;&#65292;&#35531;&#40670;&#36889;&#35041;</a></p>
</body>
</html>
"@
Set-Content -LiteralPath (Join-Path $ReleaseDir $MobileEntryName) -Value $PackageMobileEntry -Encoding UTF8

$ReleaseSiteAlias = Join-Path $ReleaseDir "site"
New-Item -ItemType Directory -Force -Path $ReleaseSiteAlias | Out-Null
$AliasMobileUrl = "../TW539Core/site/clear-cache.html?v=$MobileVersion&t=$MobileVersion"
$AliasIndexUrl = "../TW539Core/site/index.html?v=$MobileVersion&t=$MobileVersion"
$AliasHtml = @"
<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta http-equiv="Cache-Control" content="no-store, no-cache, must-revalidate, max-age=0">
  <meta http-equiv="Pragma" content="no-cache">
  <meta http-equiv="Expires" content="0">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>&#25163;&#27231;&#29256;&#36339;&#36681;</title>
  <meta http-equiv="refresh" content="0; url=$AliasMobileUrl">
</head>
<body>
  <p>&#27491;&#22312;&#25171;&#38283;&#26368;&#26032;&#25163;&#27231;&#29256;...</p>
  <p><a href="$AliasMobileUrl">&#33509;&#27794;&#26377;&#33258;&#21205;&#36339;&#36681;&#65292;&#35531;&#40670;&#36889;&#35041;</a></p>
</body>
</html>
"@
$AliasIndexHtml = $AliasHtml.Replace($AliasMobileUrl, $AliasIndexUrl)
Set-Content -LiteralPath (Join-Path $ReleaseSiteAlias "clear-cache.html") -Value $AliasHtml -Encoding UTF8
Set-Content -LiteralPath (Join-Path $ReleaseSiteAlias "index.html") -Value $AliasIndexHtml -Encoding UTF8

Compress-Archive -Path (Join-Path $ReleaseDir "*") -DestinationPath $ZipPath -Force
Write-Host "Source core: $SourceCore"
Write-Host "Release folder: $ReleaseDir"
Write-Host "Release zip: $ZipPath"
