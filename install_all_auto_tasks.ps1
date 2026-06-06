$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

$CurrentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
$Principal = New-Object Security.Principal.WindowsPrincipal($CurrentIdentity)
if (-not $Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  Start-Process powershell.exe -Verb RunAs -ArgumentList @(
    "-NoProfile",
    "-ExecutionPolicy",
    "Bypass",
    "-File",
    "`"$PSCommandPath`""
  )
  exit 0
}

Write-Host "Installing 539 startup task..."
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $ScriptDir "install_startup_task.ps1")
if ($LASTEXITCODE -ne 0 -or -not $?) {
  throw "Startup task installation failed."
}

Write-Host "Installing 539 daily post-draw task..."
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $ScriptDir "install_daily_task.ps1")
if ($LASTEXITCODE -ne 0 -or -not $?) {
  throw "Daily post-draw task installation failed."
}

Write-Host "All automatic tasks were installed."
