@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$p=Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'; if(!(Test-Path $p)){ $p='python' }; & $p '.\system_file_check.py'; Start-Process '.\reports\file_integrity_report.md'"
pause
