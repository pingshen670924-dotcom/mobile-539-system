$ErrorActionPreference = "Stop"

$AppName = "539 Prediction System"
$ChineseAppName = "539" + [char]0x9810 + [char]0x6E2C + [char]0x7CFB + [char]0x7D71
$InstallRoot = Join-Path ([Environment]::GetFolderPath("MyDocuments")) "Codex\539PredictionSystem"
$LegacyInstallRoot = Join-Path $env:LOCALAPPDATA "Programs\539PredictionSystem"
$SourceDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$DesktopDir = [Environment]::GetFolderPath("Desktop")
$StartMenuDir = Join-Path ([Environment]::GetFolderPath("Programs")) $AppName
$ChineseStartMenuDir = Join-Path ([Environment]::GetFolderPath("Programs")) $ChineseAppName
$StartupDir = [Environment]::GetFolderPath("Startup")
$StartupBat = Join-Path $StartupDir "539-startup-auto-run.bat"

function New-AppShortcut {
  param(
    [string]$ShortcutPath,
    [string]$TargetPath,
    [string]$WorkingDirectory,
    [string]$Description
  )
  try {
    $Shell = New-Object -ComObject WScript.Shell
    $Shortcut = $Shell.CreateShortcut($ShortcutPath)
    $Shortcut.TargetPath = $TargetPath
    $Shortcut.WorkingDirectory = $WorkingDirectory
    $Shortcut.Description = $Description
    $Shortcut.Save()
    return $true
  } catch {
    Write-Host "Shortcut could not be created: $ShortcutPath"
    Write-Host $_
    return $false
  }
}

if (-not (Test-Path (Join-Path $SourceDir "run_539_once.ps1"))) {
  throw "Installer must be run from the 539 application folder."
}

if ((Test-Path $LegacyInstallRoot) -and ($LegacyInstallRoot -ne $InstallRoot)) {
  try {
    Remove-Item -Path $LegacyInstallRoot -Recurse -Force
  } catch {
    Write-Host "Legacy install folder could not be removed. Continuing."
  }
}

New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null

$Items = Get-ChildItem -Path $SourceDir -Force | Where-Object {
  $_.Name -notin @("__pycache__")
}

foreach ($Item in $Items) {
  $Target = Join-Path $InstallRoot $Item.Name
  if ($Item.PSIsContainer) {
    Copy-Item -Path $Item.FullName -Destination $Target -Recurse -Force
  } else {
    Copy-Item -Path $Item.FullName -Destination $Target -Force
  }
}

New-Item -ItemType Directory -Force -Path $StartMenuDir | Out-Null
New-Item -ItemType Directory -Force -Path $ChineseStartMenuDir | Out-Null

$InstalledBat = Join-Path $InstallRoot "539-one-click.bat"
$InstalledStartBat = Join-Path $InstallRoot "START_539_SOFTWARE.bat"
$InstalledChineseStartBat = Join-Path $InstallRoot ($ChineseAppName + ".bat")
$DesktopShortcut = Join-Path $DesktopDir "539 Prediction System.lnk"
$ChineseDesktopShortcut = Join-Path $DesktopDir ($ChineseAppName + ".lnk")
$StartShortcut = Join-Path $StartMenuDir "539 Prediction System.lnk"
$ChineseStartShortcut = Join-Path $ChineseStartMenuDir ($ChineseAppName + ".lnk")
$UninstallShortcut = Join-Path $StartMenuDir "Uninstall 539 Prediction System.lnk"
$ChineseUninstallShortcut = Join-Path $ChineseStartMenuDir ("Uninstall " + $ChineseAppName + ".lnk")

$DesktopShortcutOk = New-AppShortcut -ShortcutPath $DesktopShortcut -TargetPath $InstalledBat -WorkingDirectory $InstallRoot -Description "Run 539 update, analysis, and report."
$ChineseDesktopShortcutOk = New-AppShortcut -ShortcutPath $ChineseDesktopShortcut -TargetPath $InstalledBat -WorkingDirectory $InstallRoot -Description "Run 539 update, analysis, and report."
$StartShortcutOk = New-AppShortcut -ShortcutPath $StartShortcut -TargetPath $InstalledBat -WorkingDirectory $InstallRoot -Description "Run 539 update, analysis, and report."
$ChineseStartShortcutOk = New-AppShortcut -ShortcutPath $ChineseStartShortcut -TargetPath $InstalledBat -WorkingDirectory $InstallRoot -Description "Run 539 update, analysis, and report."
$UninstallShortcutOk = New-AppShortcut -ShortcutPath $UninstallShortcut -TargetPath "powershell.exe" -WorkingDirectory $InstallRoot -Description "Uninstall 539 Prediction System."
$ChineseUninstallShortcutOk = New-AppShortcut -ShortcutPath $ChineseUninstallShortcut -TargetPath "powershell.exe" -WorkingDirectory $InstallRoot -Description "Uninstall 539 Prediction System."

$Shell = New-Object -ComObject WScript.Shell
try {
  $UninstallLink = $Shell.CreateShortcut($UninstallShortcut)
  $UninstallLink.Arguments = "-ExecutionPolicy Bypass -File `"$InstallRoot\uninstall_app.ps1`""
  $UninstallLink.Save()
} catch {
  Write-Host "Uninstall shortcut could not be completed: $UninstallShortcut"
}
try {
  $ChineseUninstallLink = $Shell.CreateShortcut($ChineseUninstallShortcut)
  $ChineseUninstallLink.Arguments = "-ExecutionPolicy Bypass -File `"$InstallRoot\uninstall_app.ps1`""
  $ChineseUninstallLink.Save()
} catch {
  Write-Host "Uninstall shortcut could not be completed: $ChineseUninstallShortcut"
}

$StartupLines = @(
  "@echo off",
  "cd /d `"$InstallRoot`"",
  "powershell -NoProfile -WindowStyle Hidden -Command `"Start-Process powershell.exe -WindowStyle Hidden -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File `"`"$InstallRoot\auto_update_monitor.ps1`"`"'`""
)
try {
  Set-Content -Path $StartupBat -Value $StartupLines -Encoding ASCII
} catch {
  Write-Host "Startup launcher could not be created: $StartupBat"
}
$AutoMonitor = Join-Path $InstallRoot "auto_update_monitor.ps1"
$AutoCommand = "powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$AutoMonitor`""
try {
  New-Item -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" -Force | Out-Null
  Set-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" -Name "539PredictionAutoUpdate" -Value $AutoCommand
} catch {
  Write-Host "Automatic update registry entry could not be created."
}

$StartLines = @(
  "@echo off",
  "cd /d `"$InstallRoot`"",
  "powershell -NoProfile -ExecutionPolicy Bypass -File `"$InstallRoot\run_539_once.ps1`"",
  "pause"
)
Set-Content -Path $InstalledStartBat -Value $StartLines -Encoding ASCII
Set-Content -Path $InstalledChineseStartBat -Value $StartLines -Encoding ASCII

Write-Host "Installed: $InstallRoot"
Write-Host "Main launcher: $InstalledStartBat"
Write-Host "Chinese launcher: $InstalledChineseStartBat"
Write-Host "Desktop shortcut created: $DesktopShortcutOk / $ChineseDesktopShortcutOk"
Write-Host "Start menu shortcut created: $StartShortcutOk / $ChineseStartShortcutOk"
Write-Host "Startup launcher path: $StartupBat"
