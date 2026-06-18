param([switch]$NoPause)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

function Test-Admin {
  $Identity = [Security.Principal.WindowsIdentity]::GetCurrent()
  $Principal = New-Object Security.Principal.WindowsPrincipal($Identity)
  return $Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-Admin)) {
  $ArgsText = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
  Start-Process -FilePath "powershell.exe" -ArgumentList $ArgsText -Verb RunAs
  exit 0
}

$LogDir = Join-Path $ScriptDir "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$LogPath = Join-Path $LogDir "network_permission_repair.log"

function Write-Log {
  param([string]$Text)
  $Line = "$(Get-Date -Format s) $Text"
  Write-Host $Line
  $Line | Out-File -FilePath $LogPath -Encoding utf8 -Append
}

function Add-AllowRule {
  param(
    [string]$RuleName,
    [string]$ProgramPath
  )
  if (-not (Test-Path $ProgramPath)) {
    Write-Log "Skipped missing program: $ProgramPath"
    return
  }
  $Existing = Get-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue
  if ($Existing) {
    Write-Log "Rule already exists: $RuleName"
    return
  }
  New-NetFirewallRule `
    -DisplayName $RuleName `
    -Direction Outbound `
    -Program $ProgramPath `
    -Action Allow `
    -Profile Any `
    -Enabled True | Out-Null
  Write-Log "Added outbound allow rule: $RuleName"
}

$PythonPaths = @(
  (Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe")
)
$PythonCommand = Get-Command python -ErrorAction SilentlyContinue
if ($PythonCommand) {
  $PythonPaths += $PythonCommand.Source
}

foreach ($PythonPath in ($PythonPaths | Select-Object -Unique)) {
  Add-AllowRule "539 Allow Python Outbound $([IO.Path]::GetFileName($PythonPath))" $PythonPath
}

Add-AllowRule "539 Allow Windows PowerShell Outbound" "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
Add-AllowRule "539 Allow Windows curl Outbound" "$env:SystemRoot\System32\curl.exe"

Write-Log "Network permission repair finished."
Write-Log "Next step is automatic: running network diagnostic again."
& (Join-Path $ScriptDir "network_permission_diagnostic.ps1")

Write-Host ""
Write-Host "Finished. You can now run 點我一鍵啟動539主系統.bat again."
if (-not $NoPause) {
  pause
}
