$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Installer = Join-Path $ScriptDir "install_app.ps1"

powershell -ExecutionPolicy Bypass -File $Installer
