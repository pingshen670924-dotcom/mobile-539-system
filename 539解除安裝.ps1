$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Uninstaller = Join-Path $ScriptDir "uninstall_app.ps1"

powershell -ExecutionPolicy Bypass -File $Uninstaller
