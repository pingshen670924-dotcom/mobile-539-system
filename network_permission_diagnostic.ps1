$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir
$ReportDir = Join-Path $ScriptDir "reports"
New-Item -ItemType Directory -Force -Path $ReportDir | Out-Null
$TextPath = Join-Path $ReportDir "network_permission_diagnostic.txt"
$JsonPath = Join-Path $ReportDir "network_permission_diagnostic.json"
$Lines = New-Object System.Collections.Generic.List[string]
$Results = New-Object System.Collections.Generic.List[object]

function Add-Line {
  param([string]$Text)
  $Text = $Text.Replace([char]0xFFFD, "?")
  $Lines.Add($Text) | Out-Null
  Write-Host $Text
}

function Clean-Detail {
  param([string]$Text)
  if ($null -eq $Text) { return "" }
  return $Text.Replace([char]0xFFFD, "?")
}

function Find-Python {
  $Bundled = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
  if (Test-Path $Bundled) { return $Bundled }
  $Cmd = Get-Command python -ErrorAction SilentlyContinue
  if ($Cmd) { return $Cmd.Source }
  return $null
}

function Add-Result {
  param(
    [string]$Name,
    [bool]$Success,
    [string]$Detail
  )
  $Detail = Clean-Detail $Detail
  $Results.Add([pscustomobject]@{
    name = $Name
    success = $Success
    detail = $Detail
  }) | Out-Null
  $Status = if ($Success) { "PASS" } else { "FAIL" }
  Add-Line ("{0} {1}: {2}" -f $Status, $Name, $Detail)
}

$StartedAt = Get-Date -Format s
Add-Line "539 network permission diagnostic"
Add-Line "Run time: $StartedAt"
Add-Line "System user: $env:USERNAME"
Add-Line ""

$Targets = @(
  "api.taiwanlottery.com",
  "www.taiwanlottery.com",
  "github.com",
  "pingshen670924-dotcom.github.io"
)

foreach ($Target in $Targets) {
  try {
    $Result = Test-NetConnection $Target -Port 443 -WarningAction SilentlyContinue
    Add-Result "TCP 443 $Target" ([bool]$Result.TcpTestSucceeded) ("DNS=$($Result.NameResolutionSucceeded), TCP443=$($Result.TcpTestSucceeded)")
  } catch {
    Add-Result "TCP 443 $Target" $false $_.Exception.Message
  }
}

$LatestUrl = "https://api.taiwanlottery.com/TLCAPIWeB/Lottery/LatestResult"
$Python = Find-Python
if ($Python) {
  try {
    $Code = "import urllib.request; urllib.request.urlopen('$LatestUrl', timeout=20).read(32); print('ok')"
    $Out = & $Python -c $Code 2>&1
    Add-Result "Python HTTPS Taiwan Lottery" ($LASTEXITCODE -eq 0) (($Out | Out-String).Trim())
  } catch {
    Add-Result "Python HTTPS Taiwan Lottery" $false $_.Exception.Message
  }
} else {
  Add-Result "Python HTTPS Taiwan Lottery" $false "Python executable was not found."
}

try {
  $Response = Invoke-WebRequest -Uri $LatestUrl -UseBasicParsing -TimeoutSec 20
  Add-Result "PowerShell HTTPS Taiwan Lottery" $true ("HTTP " + $Response.StatusCode)
} catch {
  Add-Result "PowerShell HTTPS Taiwan Lottery" $false $_.Exception.Message
}

try {
  $Out = curl.exe -L --fail --silent --show-error --connect-timeout 20 --max-time 30 -I $LatestUrl 2>&1
  Add-Result "curl HTTPS Taiwan Lottery" ($LASTEXITCODE -eq 0) (($Out | Select-Object -First 3 | Out-String).Trim())
} catch {
  Add-Result "curl HTTPS Taiwan Lottery" $false $_.Exception.Message
}

try {
  $Rule = netsh advfirewall firewall show rule name="codex_sandbox_offline_block_outbound" 2>&1
  if (($Rule | Out-String) -match "codex_sandbox_offline_block_outbound") {
    Add-Result "Codex sandbox outbound block rule" $false "A Codex offline outbound block rule is visible. The installed Windows scheduled task can run outside this Codex sandbox, and the repair script can add normal firewall allow rules."
  } else {
    Add-Result "Codex sandbox outbound block rule" $true "No matching Codex outbound block rule was found."
  }
} catch {
  Add-Result "Codex sandbox outbound block rule" $false $_.Exception.Message
}

$Passed = @($Results | Where-Object { $_.success }).Count
$Failed = @($Results | Where-Object { -not $_.success }).Count
Add-Line ""
Add-Line "Summary: pass=$Passed fail=$Failed"
Add-Line "Automatic updater now uses three download paths: Python, PowerShell, curl."
Add-Line "If all three fail here, run: 539-repair-network.bat"
Add-Line "After repair finishes, run: 539-one-click.bat"

$Lines | Set-Content -LiteralPath $TextPath -Encoding UTF8
[pscustomobject]@{
  checked_at = $StartedAt
  passed = $Passed
  failed = $Failed
  results = $Results
} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $JsonPath -Encoding UTF8

Add-Line "Report saved: $TextPath"
