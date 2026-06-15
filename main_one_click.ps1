$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

$LogDir = Join-Path $ScriptDir "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$RunLog = Join-Path $LogDir "main_one_click.log"
$MutexName = "Global\539PredictionSystemOneClick"
$Mutex = New-Object System.Threading.Mutex($false, $MutexName)
$HasMutex = $false

function Write-Step {
  param([string]$Message)
  $line = "$(Get-Date -Format s) $Message"
  Write-Host $line
  $line | Out-File -FilePath $RunLog -Encoding utf8 -Append
}

function Find-Python {
  $bundled = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
  if (Test-Path $bundled) {
    return $bundled
  }
  $cmd = Get-Command python -ErrorAction SilentlyContinue
  if ($cmd) {
    return $cmd.Source
  }
  throw "Python executable was not found."
}

function Run-Step {
  param(
    [string]$Label,
    [string[]]$Arguments,
    [bool]$Required = $true
  )
  Write-Step $Label
  & $Python @Arguments 2>&1 | Tee-Object -FilePath $RunLog -Append
  if ($LASTEXITCODE -ne 0 -and $Required) {
    throw "$Label failed."
  }
  if ($LASTEXITCODE -ne 0) {
    Write-Step "$Label finished with warnings."
  }
}

function Run-PowerShell-Step {
  param(
    [string]$Label,
    [string]$ScriptPath,
    [bool]$Required = $false
  )
  Write-Step $Label
  if (-not (Test-Path $ScriptPath)) {
    Write-Step "$Label skipped because the script was not found."
    return
  }
  & "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File $ScriptPath 2>&1 | Tee-Object -FilePath $RunLog -Append
  if ($LASTEXITCODE -ne 0 -and $Required) {
    throw "$Label failed."
  }
  if ($LASTEXITCODE -ne 0) {
    Write-Step "$Label finished with warnings."
  }
}

function Remove-GeneratedCaches {
  Get-ChildItem -Path $ScriptDir -Directory -Recurse -Force -Filter "__pycache__" -ErrorAction SilentlyContinue | ForEach-Object {
    try {
      Remove-Item -LiteralPath $_.FullName -Recurse -Force
    } catch {
      Write-Step "Generated cache cleanup skipped."
    }
  }
}

function Open-BattleReport {
  $reportName = "539" + [char]0x6700 + [char]0x65B0 + [char]0x5F37 + [char]0x5316 + [char]0x6230 + [char]0x5831 + ".html"
  $reportPath = Join-Path (Join-Path $ScriptDir "reports") $reportName
  if (Test-Path $reportPath) {
    try {
      Start-Process $reportPath
      Write-Step "Battle report opened."
    } catch {
      Write-Step "Report was created, but automatic open was blocked."
      Write-Step $reportPath
    }
    return $true
  }
  Write-Step "Battle report file does not exist yet."
  return $false
}

try {
  "==== main one click started $(Get-Date -Format s) ====" | Out-File -FilePath $RunLog -Encoding utf8 -Append
  $HasMutex = $Mutex.WaitOne(0)
  if (-not $HasMutex) {
    Write-Step "Another full run is already running. This run is skipped to protect the database."
    Open-BattleReport | Out-Null
    exit 0
  }
  $Python = Find-Python
  Run-Step "Compile check" @("-m", "py_compile", ".\update_539.py", ".\analyze_539.py", ".\battle_report.py", ".\health_check.py", ".\dashboard.py", ".\pages_build.py", ".\industrial_engine.py", ".\aerospace_engine.py", ".\research_kpi.py", ".\daily_integrity_audit.py", ".\line_push.py")
  Run-Step "Update latest draw" @(".\update_539.py", "--latest")
  Run-Step "Rebuild battle report" @(".\battle_report.py")
  Run-Step "Rebuild dashboard" @(".\dashboard.py") $false
  Run-Step "Health check" @(".\health_check.py") $false
  Run-Step "Daily integrity audit" @(".\daily_integrity_audit.py") $false
  Run-Step "Rebuild battle report after audit" @(".\battle_report.py") $false
  Run-Step "Build phone site files" @(".\pages_build.py") $false
  Run-PowerShell-Step "Publish phone cloud site" (Join-Path $ScriptDir "publish_free_github.ps1") $false
  Run-Step "Push LINE report" @(".\line_push.py") $false
  Run-Step "File encoding check" @(".\system_file_check.py") $false
  Remove-GeneratedCaches

  Open-BattleReport | Out-Null
  Write-Step "Main one click finished."
  "==== main one click finished $(Get-Date -Format s) ====" | Out-File -FilePath $RunLog -Encoding utf8 -Append
} catch {
  $_ | Out-File -FilePath $RunLog -Encoding utf8 -Append
  Write-Step "Main one click encountered a problem, opening the latest available battle report instead of stopping."
  Open-BattleReport | Out-Null
  exit 0
} finally {
  if ($HasMutex) {
    $Mutex.ReleaseMutex()
  }
  $Mutex.Dispose()
}
