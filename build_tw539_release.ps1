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
$LauncherName = "TW539" + (TextFromCodes @(0x4e00,0x9375,0x5168,0x81ea,0x52d5,0x555f,0x52d5)) + ".bat"
$CoreFolderName = TextFromCodes @(0x7cfb,0x7d71,0x6838,0x5fc3)
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
$NestedRuntimeFolders = @("reports\reports", "reports\history\history", "data\data")
foreach ($relativeNested in $NestedRuntimeFolders) {
  $nestedPath = Join-Path $SourceCore $relativeNested
  if (Test-Path -LiteralPath $nestedPath) {
    $resolvedNested = (Resolve-Path -LiteralPath $nestedPath).Path
    if ($resolvedNested.StartsWith($SourceCore, [System.StringComparison]::OrdinalIgnoreCase)) {
      Remove-Item -LiteralPath $resolvedNested -Recurse -Force
    }
  }
}

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
  "cd /d `"%~dp0$CoreFolderName`"",
  "`"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe`" -NoProfile -ExecutionPolicy Bypass -File `"%CD%\main_one_click.ps1`"",
  "set `"REPORT=%~dp0$CoreFolderName\reports\latest_battle_report.html`"",
  "if exist `"%REPORT%`" start `"`" `"%REPORT%`""
) -join [Environment]::NewLine
Set-Content -LiteralPath (Join-Path $ReleaseDir $LauncherName) -Value $Launcher -Encoding UTF8

$Core = Join-Path $ReleaseDir $CoreFolderName
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

Add-Type -AssemblyName System.IO.Compression.FileSystem
$PayloadRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("TW539Payload_" + [guid]::NewGuid().ToString("N"))
$PayloadZip = Join-Path ([System.IO.Path]::GetTempPath()) ("TW539Payload_" + [guid]::NewGuid().ToString("N") + ".zip")
New-Item -ItemType Directory -Path $PayloadRoot | Out-Null
try {
  Copy-Item -LiteralPath $Core -Destination (Join-Path $PayloadRoot $CoreFolderName) -Recurse -Force
  [System.IO.Compression.ZipFile]::CreateFromDirectory($PayloadRoot, $PayloadZip, [System.IO.Compression.CompressionLevel]::Optimal, $false, [System.Text.Encoding]::UTF8)
  $PayloadBase64 = [Convert]::ToBase64String([System.IO.File]::ReadAllBytes($PayloadZip))
  $PayloadLines = [regex]::Matches($PayloadBase64, ".{1,76}") | ForEach-Object { $_.Value }
  $ExtractCommand = '$ErrorActionPreference="Stop"; $root=$env:TW539_ROOT; $self=$env:TW539_SELF; $coreName=[string]::Concat([char]0x7cfb,[char]0x7d71,[char]0x6838,[char]0x5fc3); $core=Join-Path $root $coreName; if(-not (Test-Path -LiteralPath (Join-Path $core "main_one_click.ps1"))){ $marker="-----BEGIN_TW539_CORE_ZIP_BASE64-----"; $lines=[System.IO.File]::ReadAllLines($self,[System.Text.Encoding]::UTF8); $start=[Array]::IndexOf($lines,$marker); if($start -lt 0){ throw "Core payload missing." }; $payload=($lines[($start+1)..($lines.Length-1)] -join ""); $zip=Join-Path $root "tw539_core_payload.zip"; [System.IO.File]::WriteAllBytes($zip,[Convert]::FromBase64String($payload)); Expand-Archive -LiteralPath $zip -DestinationPath $root -Force; Remove-Item -LiteralPath $zip -Force }; $item=Get-Item -LiteralPath $core -Force; $item.Attributes=$item.Attributes -bor [System.IO.FileAttributes]::Hidden; Set-Location -LiteralPath $core; & ($env:SystemRoot + "\System32\WindowsPowerShell\v1.0\powershell.exe") -NoProfile -ExecutionPolicy Bypass -File (Join-Path $core "main_one_click.ps1")'
  $EncodedCommand = [Convert]::ToBase64String([System.Text.Encoding]::Unicode.GetBytes($ExtractCommand))
  $SelfExtractLauncher = @(
    "@echo off",
    "chcp 65001 >nul",
    "set `"TW539_SELF=%~f0`"",
    "set `"TW539_ROOT=%~dp0`"",
    "`"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe`" -NoProfile -ExecutionPolicy Bypass -EncodedCommand $EncodedCommand",
    "if errorlevel 1 pause",
    "exit /b",
    "-----BEGIN_TW539_CORE_ZIP_BASE64-----"
  ) + $PayloadLines
  Set-Content -LiteralPath (Join-Path $ReleaseDir $LauncherName) -Value ($SelfExtractLauncher -join [Environment]::NewLine) -Encoding ASCII
} finally {
  if (Test-Path -LiteralPath $PayloadRoot) {
    Remove-Item -LiteralPath $PayloadRoot -Recurse -Force
  }
  if (Test-Path -LiteralPath $PayloadZip) {
    Remove-Item -LiteralPath $PayloadZip -Force
  }
}
Remove-Item -LiteralPath $Core -Recurse -Force
[System.IO.Compression.ZipFile]::CreateFromDirectory($ReleaseDir, $ZipPath, [System.IO.Compression.CompressionLevel]::Optimal, $false, [System.Text.Encoding]::UTF8)
Write-Host "Source core: $SourceCore"
Write-Host "Release folder: $ReleaseDir"
Write-Host "Release zip: $ZipPath"
