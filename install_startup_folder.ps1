$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$StartupDir = [Environment]::GetFolderPath("Startup")
$StartupBat = Join-Path $StartupDir "539-startup-auto-run.bat"
$Runner = Join-Path $ScriptDir "auto_update_monitor.ps1"

if (-not (Test-Path $Runner)) {
  throw "Runner was not found."
}

$Lines = @(
  "@echo off",
  "cd /d `"$ScriptDir`"",
  "powershell -NoProfile -WindowStyle Hidden -Command `"Start-Process powershell.exe -WindowStyle Hidden -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File `"`"$Runner`"`"'`""
)

try {
  Set-Content -Path $StartupBat -Value $Lines -Encoding ASCII
} catch {
  $AutoCommand = "powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$Runner`""
  New-Item -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" -Force | Out-Null
  Set-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" -Name "539PredictionAutoUpdate" -Value $AutoCommand
}

Write-Host "Startup folder launcher installed:"
Write-Host $StartupBat
