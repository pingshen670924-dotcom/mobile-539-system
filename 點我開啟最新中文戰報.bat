@echo off
cd /d "%~dp0"
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -Command "$n='539'+[char]0x6700+[char]0x65B0+[char]0x5F37+[char]0x5316+[char]0x6230+[char]0x5831+'.html'; Start-Process (Join-Path (Join-Path '%~dp0' 'reports') $n)"
pause
