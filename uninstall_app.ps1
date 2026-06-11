$ErrorActionPreference = "Stop"

$AppName = "539 Prediction System"
$ChineseAppName = "539" + [char]0x9810 + [char]0x6E2C + [char]0x7CFB + [char]0x7D71
$InstallRoot = Join-Path ([Environment]::GetFolderPath("MyDocuments")) "Codex\539PredictionSystem"
$LegacyInstallRoot = Join-Path $env:LOCALAPPDATA "Programs\539PredictionSystem"
$DesktopShortcut = Join-Path ([Environment]::GetFolderPath("Desktop")) "539 Prediction System.lnk"
$ChineseDesktopShortcut = Join-Path ([Environment]::GetFolderPath("Desktop")) ($ChineseAppName + ".lnk")
$StartMenuDir = Join-Path ([Environment]::GetFolderPath("Programs")) $AppName
$ChineseStartMenuDir = Join-Path ([Environment]::GetFolderPath("Programs")) $ChineseAppName
$StartupBat = Join-Path ([Environment]::GetFolderPath("Startup")) "539-startup-auto-run.bat"
Remove-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" -Name "539PredictionAutoUpdate" -ErrorAction SilentlyContinue

if (Test-Path $DesktopShortcut) {
  Remove-Item -Path $DesktopShortcut -Force
}

if (Test-Path $ChineseDesktopShortcut) {
  Remove-Item -Path $ChineseDesktopShortcut -Force
}

if (Test-Path $StartMenuDir) {
  Remove-Item -Path $StartMenuDir -Recurse -Force
}

if (Test-Path $ChineseStartMenuDir) {
  Remove-Item -Path $ChineseStartMenuDir -Recurse -Force
}

if (Test-Path $StartupBat) {
  Remove-Item -Path $StartupBat -Force
}

if (Test-Path $InstallRoot) {
  Remove-Item -Path $InstallRoot -Recurse -Force
}

if (Test-Path $LegacyInstallRoot) {
  try {
    Remove-Item -Path $LegacyInstallRoot -Recurse -Force
  } catch {
    Write-Host "Legacy install folder could not be removed."
  }
}

Write-Host "539 Prediction System was uninstalled."
