$ErrorActionPreference = "Stop"

$StartupDir = [Environment]::GetFolderPath("Startup")
$StartupBat = Join-Path $StartupDir "539-startup-auto-run.bat"

if (Test-Path $StartupBat) {
  Remove-Item -Path $StartupBat -Force
  Write-Host "Startup folder launcher removed:"
  Write-Host $StartupBat
} else {
  Write-Host "Startup folder launcher was not installed."
}
