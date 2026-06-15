$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$SettingsPath = Join-Path $ScriptDir "line_settings.json"
$HelpPath = Join-Path $ScriptDir "line_setup_help.html"

function Write-SetupHelp {
  $html = @"
<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <title>539 LINE 自動轉發設定</title>
  <style>
    body{font-family:"Microsoft JhengHei",Arial,sans-serif;line-height:1.7;margin:0;background:#f6f7fb;color:#111827}
    main{max-width:860px;margin:0 auto;padding:28px}
    section{background:white;border:1px solid #e5e7eb;border-radius:8px;padding:20px;margin:14px 0}
    h1{margin-top:0}.mark{background:#fef3c7;padding:2px 6px;border-radius:4px}
    a{color:#166534;font-weight:800}
  </style>
</head>
<body>
<main>
  <h1>539 LINE 自動轉發設定</h1>
  <section>
    <h2>你只需要拿到一串 Channel access token</h2>
    <p>這串 token 只能從你的 LINE 官方帳號後台產生。程式不能自己產生，因為這是你的 LINE 帳號權限。</p>
    <p><a href="https://developers.line.biz/console/">打開 LINE Developers Console</a></p>
  </section>
  <section>
    <h2>操作順序</h2>
    <ol>
      <li>登入 LINE Developers Console。</li>
      <li>選擇你的 Provider，沒有就建立一個。</li>
      <li>建立或進入 Messaging API channel。</li>
      <li>找到 <span class="mark">Messaging API</span> 頁籤。</li>
      <li>找到 <span class="mark">Channel access token</span>，按 Issue 或 Reissue。</li>
      <li>複製那一長串 token。</li>
      <li>回到黑色設定視窗，貼上 token，按 Enter。</li>
    </ol>
  </section>
  <section>
    <h2>接收方式</h2>
    <p>建議使用 broadcast。你只要把自己的 LINE 加入該官方帳號好友，每次戰報更新後就會收到訊息。</p>
  </section>
</main>
</body>
</html>
"@
  Set-Content -LiteralPath $HelpPath -Value $html -Encoding UTF8
}

function Sync-GitHubSecrets {
  param([string]$Token, [string]$Mode, [string]$ToId)
  if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    Write-Host "GitHub CLI was not found. Mobile cloud LINE secrets were not changed."
    return
  }
  gh auth status *> $null
  if ($LASTEXITCODE -ne 0) {
    Write-Host "GitHub CLI is not logged in. Mobile cloud LINE secrets were not changed."
    return
  }
  $Owner = gh api user --jq .login
  if (-not $Owner) {
    Write-Host "GitHub account name was not detected. Mobile cloud LINE secrets were not changed."
    return
  }
  $Repository = "$Owner/mobile-539-system"
  gh repo view $Repository *> $null
  if ($LASTEXITCODE -ne 0) {
    Write-Host "GitHub mobile repository was not found. Mobile cloud LINE secrets were not changed."
    return
  }
  $Token | gh secret set LINE_CHANNEL_ACCESS_TOKEN --repo $Repository | Out-Null
  if ($LASTEXITCODE -ne 0) {
    Write-Host "Failed to update LINE_CHANNEL_ACCESS_TOKEN on GitHub."
    return
  }
  $Mode | gh secret set LINE_DELIVERY_MODE --repo $Repository | Out-Null
  if ($LASTEXITCODE -ne 0) {
    Write-Host "Failed to update LINE_DELIVERY_MODE on GitHub."
    return
  }
  if ($Mode -eq "push" -and $ToId) {
    $ToId | gh secret set LINE_TO_ID --repo $Repository | Out-Null
    if ($LASTEXITCODE -ne 0) {
      Write-Host "Failed to update LINE_TO_ID on GitHub."
      return
    }
  }
  Write-Host "GitHub mobile cloud LINE secrets were updated."
}

function Test-LineTokenShape {
  param([string]$Token)
  $value = $Token.Trim()
  if ($value.StartsWith("@")) {
    return $false
  }
  if ($value.Length -lt 80) {
    return $false
  }
  if ($value -notmatch "^[A-Za-z0-9._\\-+/=]+$") {
    return $false
  }
  return $true
}

Write-Host "LINE battle report setup"
Write-Host "Recommended mode: broadcast"
Write-Host "Broadcast sends the report to all friends of your LINE Official Account."
Write-Host "Add your own LINE account as a friend of that Official Account."
Write-Host ""
Write-SetupHelp
Start-Process $HelpPath
Start-Process "https://developers.line.biz/console/"

$mode = Read-Host "Delivery mode [broadcast/push] (default: broadcast)"
if ([string]::IsNullOrWhiteSpace($mode)) {
  $mode = "broadcast"
}
$mode = $mode.Trim().ToLowerInvariant()
if ($mode -ne "broadcast" -and $mode -ne "push") {
  throw "Delivery mode must be broadcast or push."
}

$token = Read-Host "Paste LINE Messaging API channel access token"
if ([string]::IsNullOrWhiteSpace($token)) {
  Write-Host ""
  Write-Host "No token was pasted, so setup was not changed."
  Write-Host "The help page and LINE Developers Console were opened."
  Write-Host "After you copy the Channel access token, run this setup again and paste it."
  exit 0
}
if (-not (Test-LineTokenShape $token)) {
  Write-Host ""
  Write-Host "The value you pasted does not look like a Channel access token."
  Write-Host "If it starts with @, it is probably your LINE Official Account ID, not the API token."
  Write-Host "Open the help page, go to Messaging API, find Channel access token, press Issue or Reissue, then copy the long token."
  Start-Process $HelpPath
  exit 0
}

$toId = ""
if ($mode -eq "push") {
  $toId = Read-Host "Paste LINE userId/groupId/roomId"
  if ([string]::IsNullOrWhiteSpace($toId)) {
    throw "to_id is required in push mode."
  }
}

$payload = [ordered]@{
  delivery_mode = $mode
  channel_access_token = $token.Trim()
  to_id = $toId.Trim()
}

$json = $payload | ConvertTo-Json -Depth 5
Set-Content -LiteralPath $SettingsPath -Value $json -Encoding UTF8
Sync-GitHubSecrets -Token $token.Trim() -Mode $mode -ToId $toId.Trim()

Write-Host ""
Write-Host "LINE settings saved."
Write-Host "Running a test push now..."

$python = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if (-not (Test-Path $python)) {
  $python = "python"
}
& $python (Join-Path $ScriptDir "line_push.py")

Write-Host ""
Write-Host "Done. Check reports\line_push_status.json if the message was not received."
