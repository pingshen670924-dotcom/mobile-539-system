$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

$LogDir = Join-Path $ScriptDir "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$RunLog = Join-Path $LogDir "one_click.log"
$MutexName = "Global\539PredictionSystemOneClick"
$Mutex = New-Object System.Threading.Mutex($false, $MutexName)
$HasMutex = $false

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

function Run-PowerShell-Step {
  param(
    [string]$Label,
    [string]$ScriptPath,
    [string[]]$Arguments = @(),
    [bool]$Required = $false
  )
  "$(Get-Date -Format s) $Label" | Out-File -FilePath $RunLog -Encoding utf8 -Append
  if (-not (Test-Path $ScriptPath)) {
    "$Label skipped because the script was not found." | Out-File -FilePath $RunLog -Encoding utf8 -Append
    return
  }
  & "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File $ScriptPath @Arguments 2>&1 | Tee-Object -FilePath $RunLog -Append
  if ($LASTEXITCODE -ne 0 -and $Required) {
    throw "$Label failed."
  }
  if ($LASTEXITCODE -ne 0) {
    "$Label finished with warnings." | Out-File -FilePath $RunLog -Encoding utf8 -Append
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

function Start-MobileReportServer {
  "Refresh phone report link" | Out-File -FilePath $RunLog -Encoding utf8 -Append
  try {
    & $Python ".\mobile_server.py" "--write-url" 2>&1 | Tee-Object -FilePath $RunLog -Append
  } catch {
    "Phone report link refresh warning." | Out-File -FilePath $RunLog -Encoding utf8 -Append
  }

  try {
    netsh advfirewall firewall add rule name="539 Mobile Control" dir=in action=allow protocol=TCP localport=5390 profile=private *> $null
  } catch {
    "Phone firewall rule refresh skipped." | Out-File -FilePath $RunLog -Encoding utf8 -Append
  }

  $listening = $null
  try {
    $listening = Get-NetTCPConnection -LocalPort 5390 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
  } catch {
  }
  if (-not $listening) {
    try {
      Start-Process -FilePath $Python -ArgumentList "`"$ScriptDir\mobile_server.py`"" -WorkingDirectory $ScriptDir -WindowStyle Hidden
      Start-Sleep -Seconds 2
      "Phone report server started." | Out-File -FilePath $RunLog -Encoding utf8 -Append
    } catch {
      "Phone report server could not be started automatically." | Out-File -FilePath $RunLog -Encoding utf8 -Append
    }
  }

  try {
    & $Python ".\mobile_server.py" "--write-url" 2>&1 | Tee-Object -FilePath $RunLog -Append
  } catch {
    "Phone report final link refresh warning." | Out-File -FilePath $RunLog -Encoding utf8 -Append
  }
}

try {
  "==== 539 run started $(Get-Date -Format s) ====" | Out-File -FilePath $RunLog -Encoding utf8 -Append
  $HasMutex = $Mutex.WaitOne(0)
  if (-not $HasMutex) {
    "Another full run is already running. This run is skipped to protect the database." | Out-File -FilePath $RunLog -Encoding utf8 -Append
    exit 0
  }
  $Python = Find-Python
  Run-PowerShell-Step "Repair current scheduled tasks and phone service" (Join-Path $ScriptDir "repair_current_tasks.ps1") @() $false
  Run-PowerShell-Step "Cleanup obsolete runtime folders" (Join-Path $ScriptDir "cleanup_obsolete_runtime.ps1") @() $false
  "$(Get-Date -Format s) Network permission repair skipped during one-click run." | Out-File -FilePath $RunLog -Encoding utf8 -Append
  Run-PowerShell-Step "Network permission diagnostic" (Join-Path $ScriptDir "network_permission_diagnostic.ps1") @() $false
  Run-Step "Compile check" @("-m", "py_compile", ".\update_539.py", ".\analyze_539.py", ".\battle_report.py", ".\health_check.py", ".\dashboard.py", ".\pages_build.py", ".\industrial_engine.py", ".\aerospace_engine.py", ".\research_kpi.py", ".\daily_integrity_audit.py", ".\line_push.py")
  "Update latest draw and rebuild all outputs" | Out-File -FilePath $RunLog -Encoding utf8 -Append
  & $Python ".\update_539.py" --latest --retry-until-fresh-minutes 90 --retry-interval-seconds 45 2>&1 | Tee-Object -FilePath $RunLog -Append
  if ($LASTEXITCODE -ne 0) {
    "Main update returned a warning or failure. Continue rebuilding local reports so the user always gets an opened battle report." | Out-File -FilePath $RunLog -Encoding utf8 -Append
  }
  Run-Step "Rebuild battle report" @(".\battle_report.py")
  Run-Step "Model competition" @(".\model_competition.py") $false
  Run-Step "Rebuild dashboard" @(".\dashboard.py") $false
  Run-Step "Health check" @(".\health_check.py") $false
  Run-Step "Daily integrity audit" @(".\daily_integrity_audit.py")
  Run-Step "Rebuild battle report after audit" @(".\battle_report.py")
  Run-Step "Build phone site files" @(".\pages_build.py") $false
  Start-MobileReportServer
    "$(Get-Date -Format s) Publish phone cloud site" | Out-File -FilePath $RunLog -Encoding utf8 -Append
  $PublishScript = Join-Path $ScriptDir "publish_free_github.ps1"
  $PublishOut = Join-Path $LogDir "publish_free_github.out.log"
  $PublishErr = Join-Path $LogDir "publish_free_github.err.log"
  Remove-Item -LiteralPath $PublishOut,$PublishErr -Force -ErrorAction SilentlyContinue
  $PublishProcess = Start-Process -FilePath "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $PublishScript) -WorkingDirectory $ScriptDir -Wait -PassThru -NoNewWindow -RedirectStandardOutput $PublishOut -RedirectStandardError $PublishErr
  if (Test-Path -LiteralPath $PublishOut) { Get-Content -LiteralPath $PublishOut -Encoding UTF8 | Out-File -FilePath $RunLog -Encoding utf8 -Append }
  if (Test-Path -LiteralPath $PublishErr) { Get-Content -LiteralPath $PublishErr -Encoding UTF8 | Out-File -FilePath $RunLog -Encoding utf8 -Append }
  if ($PublishProcess.ExitCode -ne 0) { throw "Publish phone cloud site failed." }
  Run-Step "Verify phone cloud sync" @(".\verify_mobile_sync.py")
  Run-Step "Push LINE report" @(".\line_push.py") $false
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
} finally {
  if ($HasMutex) {
    $Mutex.ReleaseMutex()
  }
  $Mutex.Dispose()
}


