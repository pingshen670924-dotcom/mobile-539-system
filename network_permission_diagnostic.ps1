$ErrorActionPreference = "Continue"

$Targets = @(
  "api.taiwanlottery.com",
  "www.taiwanlottery.com",
  "www.google.com"
)

Write-Host "539 network permission diagnostic"
Write-Host "Run time: $(Get-Date -Format s)"
foreach ($Target in $Targets) {
  $Result = Test-NetConnection $Target -Port 443 -WarningAction SilentlyContinue
  Write-Host "$Target DNS=$($Result.NameResolutionSucceeded) TCP443=$($Result.TcpTestSucceeded)"
}

$CodexRule = netsh advfirewall firewall show rule name="codex_sandbox_offline_block_outbound"
if ($CodexRule -match "codex_sandbox_offline_block_outbound") {
  Write-Host "Codex offline sandbox rule is visible. Run the updater through Windows Task Scheduler outside Codex."
}

Write-Host "Diagnostic finished."
