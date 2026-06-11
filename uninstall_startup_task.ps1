$ErrorActionPreference = "Stop"

$TaskName = "539 Startup Full Run"
$Task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($Task) {
  Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
  Write-Host "Startup task removed: 539 Startup Full Run"
} else {
  Write-Host "Startup task was not installed."
}
