$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

$LogDir = Join-Path $ScriptDir "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$RunLog = Join-Path $LogDir "one_click.log"

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
  "$(Get-Date -Format s) $Label" | Out-File -FilePath $RunLog -Encoding utf8 -Append
  & $Python @Arguments 2>&1 | Tee-Object -FilePath $RunLog -Append
  if ($LASTEXITCODE -ne 0 -and $Required) {
    throw "$Label failed."
  }
}

function Remove-GeneratedCaches {
  Get-ChildItem -Path $ScriptDir -Directory -Recurse -Force -Filter "__pycache__" -ErrorAction SilentlyContinue | ForEach-Object {
    try {
      Remove-Item -LiteralPath $_.FullName -Recurse -Force
    } catch {
      "Generated cache cleanup skipped." | Out-File -FilePath $RunLog -Encoding utf8 -Append
    }
  }
}

try {
  "==== 539 run started $(Get-Date -Format s) ====" | Out-File -FilePath $RunLog -Encoding utf8 -Append
  $Python = Find-Python
  Run-Step "Compile check" @("-m", "py_compile", ".\update_539.py", ".\analyze_539.py", ".\battle_report.py", ".\health_check.py", ".\dashboard.py", ".\pages_build.py", ".\industrial_engine.py")
  $Updated = $false
  for ($Attempt = 1; $Attempt -le 4; $Attempt++) {
    "Update attempt $Attempt/4" | Out-File -FilePath $RunLog -Encoding utf8 -Append
    & $Python ".\update_539.py" --latest --require-fresh 2>&1 | Tee-Object -FilePath $RunLog -Append
    if ($LASTEXITCODE -eq 0) {
      $Updated = $true
      break
    }
    if ($Attempt -lt 4) {
      Start-Sleep -Seconds 600
    }
  }
  if (-not $Updated) {
    throw "Latest draw update remained stale after four attempts."
  }
  Run-Step "Rebuild battle report" @(".\battle_report.py")
  Run-Step "Rebuild dashboard" @(".\dashboard.py") $false
  Run-Step "Health check" @(".\health_check.py") $false
  Run-Step "Build phone site files" @(".\pages_build.py") $false
  Run-Step "File encoding check" @(".\system_file_check.py") $false
  Remove-GeneratedCaches
  $EnhancedName = "539" + [char]0x6700 + [char]0x65B0 + [char]0x5F37 + [char]0x5316 + [char]0x6230 + [char]0x5831 + ".html"
  $Report = Join-Path (Join-Path $ScriptDir "reports") $EnhancedName
  try {
    Start-Process $Report
  } catch {
    "Report was created, but automatic open was blocked." | Out-File -FilePath $RunLog -Encoding utf8 -Append
    $Report | Out-File -FilePath $RunLog -Encoding utf8 -Append
  }
  "==== 539 run finished $(Get-Date -Format s) ====" | Out-File -FilePath $RunLog -Encoding utf8 -Append
} catch {
  $_ | Out-File -FilePath $RunLog -Encoding utf8 -Append
  Write-Host "539 one-click run failed. Please check logs\one_click.log."
  exit 1
}
