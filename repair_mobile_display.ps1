$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $Root
$LogDir = Join-Path $Root "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$LogPath = Join-Path $LogDir "mobile_display_repair.log"

function Write-RepairLog {
  param([string]$Message)
  $line = "$(Get-Date -Format s) $Message"
  Write-Host $line
  $line | Out-File -LiteralPath $LogPath -Encoding utf8 -Append
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

function Test-MobileHealth {
  try {
    $response = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:5390/health" -TimeoutSec 5
    return ($response.StatusCode -eq 200 -and $response.Content -like "*ok*")
  } catch {
    return $false
  }
}

function Refresh-MobileUrl {
  $output = & $Python ".\mobile_server.py" "--write-url" 2>&1
  $output | Out-File -LiteralPath $LogPath -Encoding utf8 -Append
  foreach ($line in $output) {
    $text = [string]$line
    if ($text.StartsWith("http://") -or $text.StartsWith("https://")) {
      return $text.Trim()
    }
  }
  return ""
}

Write-RepairLog "Mobile display repair started."
$Python = Find-Python

try {
  netsh advfirewall firewall add rule name="539 Mobile Control" dir=in action=allow protocol=TCP localport=5390 profile=private | Out-Null
  netsh advfirewall firewall add rule name="539 Mobile Control Public" dir=in action=allow protocol=TCP localport=5390 profile=public | Out-Null
  Write-RepairLog "Firewall allow rule refreshed."
} catch {
  Write-RepairLog "Firewall allow rule skipped."
}

$connection = Get-NetTCPConnection -LocalPort 5390 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($connection) {
  if (Test-MobileHealth) {
    Write-RepairLog "Mobile server is already healthy."
  } else {
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($connection.OwningProcess)" -ErrorAction SilentlyContinue
    if ($process -and $process.CommandLine -like "*mobile_server.py*") {
      Write-RepairLog "Restarting unhealthy mobile server."
      Stop-Process -Id $connection.OwningProcess -Force -ErrorAction SilentlyContinue
      Start-Sleep -Seconds 1
      Start-Process -FilePath $Python -ArgumentList "mobile_server.py" -WorkingDirectory $Root -WindowStyle Hidden
      Start-Sleep -Seconds 2
    } else {
      Write-RepairLog "Port 5390 is used by another process. Cannot replace it automatically."
    }
  }
} else {
  Write-RepairLog "Starting mobile server."
  Start-Process -FilePath $Python -ArgumentList "mobile_server.py" -WorkingDirectory $Root -WindowStyle Hidden
  Start-Sleep -Seconds 2
}

$url = [string](Refresh-MobileUrl)
$healthy = Test-MobileHealth
if ($healthy) {
  Write-RepairLog "Mobile server health check passed."
  Write-Host ""
  Write-Host "Mobile report URL:"
  Write-Host $url
  try {
    if ($url) {
      Start-Process $url
    }
  } catch {
    Write-RepairLog "Browser open skipped."
  }
} else {
  Write-RepairLog "Mobile server health check failed."
  Write-Host "Mobile server could not be verified."
}

Write-RepairLog "Mobile display repair finished."
