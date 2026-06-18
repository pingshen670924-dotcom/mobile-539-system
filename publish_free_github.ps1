$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoName = "mobile-539-system"

function Refresh-Path {
  $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
  $user = [Environment]::GetEnvironmentVariable("Path", "User")
  $env:Path = $machine + ";" + $user
}

function Ensure-Command {
  param([string]$Name, [string]$PackageId)
  if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
      throw "Windows Package Manager is required."
    }
    winget install --id $PackageId -e --accept-package-agreements --accept-source-agreements
    Refresh-Path
  }
  if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
    throw "$Name could not be installed."
  }
}

function Test-GhAuthentication {
  $previousPreference = $ErrorActionPreference
  $ErrorActionPreference = "SilentlyContinue"
  gh auth status *> $null
  $authenticated = $LASTEXITCODE -eq 0
  $ErrorActionPreference = $previousPreference
  return $authenticated
}

function Test-GhRepository {
  param([string]$Repository)
  $previousPreference = $ErrorActionPreference
  $ErrorActionPreference = "SilentlyContinue"
  gh repo view $Repository --json name *> $null
  $exists = $LASTEXITCODE -eq 0
  $ErrorActionPreference = $previousPreference
  return $exists
}

function Confirm-TemporaryPath {
  param([string]$Path)
  $resolvedTemp = [System.IO.Path]::GetFullPath($env:TEMP).TrimEnd([char]92)
  $resolvedPath = [System.IO.Path]::GetFullPath($Path).TrimEnd([char]92)
  if (-not $resolvedPath.StartsWith($resolvedTemp, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "The publish stage must remain inside the user temporary directory."
  }
}

function Get-MobileVersion {
  $versionPath = Join-Path (Join-Path $ScriptDir "site") "version.json"
  if (Test-Path -LiteralPath $versionPath) {
    try {
      return (Get-Content -LiteralPath $versionPath -Raw -Encoding UTF8 | ConvertFrom-Json).version
    } catch {
    }
  }
  return Get-Date -Format "yyyyMMddHHmmss"
}

function Write-PublishStatus {
  param(
    [string]$Status,
    [string]$Message,
    [string]$Owner = "pingshen670924-dotcom",
    [bool]$PromoteToPrimary = $false
  )
  $mobileVersion = Get-MobileVersion
  $freshPageUrl = "https://$Owner.github.io/$RepoName/clear-cache.html?v=$mobileVersion&t=$([DateTimeOffset]::Now.ToUnixTimeSeconds())"
  $cloudUrlName = ([char]0x624B) + ([char]0x6A5F) + ([char]0x96F2) + ([char]0x7AEF) + ([char]0x7248) + ([char]0x7DB2) + ([char]0x5740) + ".txt"
  $primaryUrlName = ([char]0x624B) + ([char]0x6A5F) + ([char]0x7368) + ([char]0x7ACB) + ([char]0x7248) + ([char]0x7DB2) + ([char]0x5740) + ".txt"
  $statusName = ([char]0x624B) + ([char]0x6A5F) + ([char]0x96F2) + ([char]0x7AEF) + ([char]0x767C) + ([char]0x5E03) + ([char]0x72C0) + ([char]0x614B) + ".json"
  Set-Content -LiteralPath (Join-Path $ScriptDir $cloudUrlName) -Value $freshPageUrl -Encoding UTF8
  if ($PromoteToPrimary) {
    Set-Content -LiteralPath (Join-Path $ScriptDir $primaryUrlName) -Value $freshPageUrl -Encoding UTF8
  }
  $payload = @{
    status = $Status
    message = $Message
    written_at = (Get-Date -Format s)
    version = $mobileVersion
    url = $freshPageUrl
    repository = "$Owner/$RepoName"
  }
  $payload | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $ScriptDir $statusName) -Encoding UTF8
  return $freshPageUrl
}

function Clear-PublishStage {
  param([string]$Path)
  Confirm-TemporaryPath $Path
  Get-ChildItem -LiteralPath $Path -Force |
    Where-Object { $_.Name -ne ".git" } |
    Remove-Item -Recurse -Force
}

function Copy-PublishPayload {
  param([string]$From, [string]$To)
  Confirm-TemporaryPath $To
  New-Item -ItemType Directory -Path $To -Force | Out-Null

  Get-ChildItem -LiteralPath $From -Force -File |
    Where-Object { $_.Name -ne "crowd_consensus.py" } |
    ForEach-Object {
      Copy-Item -LiteralPath $_.FullName -Destination $To -Force
    }

  foreach ($directoryName in @(".github", "data", "reports", "site")) {
    $sourceDirectory = Join-Path $From $directoryName
    if (Test-Path $sourceDirectory) {
      Copy-Item -LiteralPath $sourceDirectory -Destination $To -Recurse -Force
    }
  }

  Get-ChildItem -LiteralPath $To -Recurse -Force -File -Filter "crowd_consensus*" |
    Remove-Item -Force
}

Write-Host "Preparing the free independent mobile 539 system..."
Write-PublishStatus "started" "Mobile cloud publish started." | Out-Null
Ensure-Command "git" "Git.Git"
Ensure-Command "gh" "GitHub.cli"

if (-not (Test-GhAuthentication)) {
  $fallbackUrl = Write-PublishStatus "blocked" "GitHub CLI is not authenticated or network access is blocked. Local phone report link was refreshed by mobile_server.py."
  Write-Host "GitHub cloud publish skipped because authentication or network access is not available."
  Write-Host "Cloud URL prepared for the next successful publish:"
  Write-Host $fallbackUrl
  exit 1
}

$Owner = gh api user --jq .login
if (-not $Owner) {
  Write-PublishStatus "blocked" "The GitHub account name could not be detected." | Out-Null
  throw "The GitHub account name could not be detected."
}

$Repository = "$Owner/$RepoName"
$RepositoryExists = Test-GhRepository $Repository
Write-PublishStatus "authenticated" "GitHub authentication passed." $Owner | Out-Null
$PublishStage = Join-Path $env:TEMP ("mobile-539-publish-" + [guid]::NewGuid().ToString("N"))
Confirm-TemporaryPath $PublishStage

try {
  if ($RepositoryExists) {
    gh repo clone $Repository $PublishStage
    if ($LASTEXITCODE -ne 0) {
      throw "The existing mobile repository could not be cloned."
    }
    Clear-PublishStage $PublishStage
  } else {
    New-Item -ItemType Directory -Path $PublishStage -Force | Out-Null
    git -C $PublishStage init
    git -C $PublishStage checkout -b main
  }

  Copy-PublishPayload $ScriptDir $PublishStage
  git -C $PublishStage config user.name $Owner
  git -C $PublishStage config user.email "$Owner@users.noreply.github.com"
  git -C $PublishStage add --all
  git -C $PublishStage diff --cached --quiet
  if ($LASTEXITCODE -ne 0) {
    git -C $PublishStage commit -m "Update free independent mobile 539 system"
  }

  if ($RepositoryExists) {
    git -C $PublishStage push origin main
  } else {
    gh repo create $RepoName --public --source $PublishStage --remote origin --push
  }
  if ($LASTEXITCODE -ne 0) {
    throw "The mobile website files could not be pushed to GitHub."
  }
} finally {
  if (Test-Path $PublishStage) {
    Confirm-TemporaryPath $PublishStage
    Remove-Item -LiteralPath $PublishStage -Recurse -Force -ErrorAction SilentlyContinue
  }
}

$previousPreference = $ErrorActionPreference
$ErrorActionPreference = "SilentlyContinue"
gh api "repos/$Repository/pages" -X POST -f build_type=workflow *> $null
$ErrorActionPreference = $previousPreference

$PageUrl = "https://$Owner.github.io/$RepoName/"
$VersionPath = Join-Path (Join-Path $ScriptDir "site") "version.json"
$MobileVersion = Get-Date -Format "yyyyMMddHHmmss"
if (Test-Path -LiteralPath $VersionPath) {
  try {
    $MobileVersion = (Get-Content -LiteralPath $VersionPath -Raw -Encoding UTF8 | ConvertFrom-Json).version
  } catch {
    $MobileVersion = Get-Date -Format "yyyyMMddHHmmss"
  }
}
$FreshPageUrl = $PageUrl + "clear-cache.html?v=$MobileVersion&t=$([DateTimeOffset]::Now.ToUnixTimeSeconds())"
$UrlName = ([char]0x624B) + ([char]0x6A5F) + ([char]0x96F2) + ([char]0x7AEF) + ([char]0x7248) + ([char]0x7DB2) + ([char]0x5740) + ".txt"
Set-Content -Path (Join-Path $ScriptDir $UrlName) -Value $FreshPageUrl -Encoding UTF8
Write-PublishStatus "pushed" "Mobile files were pushed to GitHub. Workflow is starting." $Owner | Out-Null

Write-Host ""
Write-Host "Starting the cloud calculation and website deployment..."
gh workflow run daily-update.yml --repo $Repository
if ($LASTEXITCODE -ne 0) {
  Write-PublishStatus "workflow_failed" "The cloud update workflow could not be started." $Owner | Out-Null
  throw "The cloud update workflow could not be started."
}

Start-Sleep -Seconds 5
$RunId = gh run list --repo $Repository --workflow daily-update.yml --limit 1 --json databaseId --jq ".[0].databaseId"
if ($RunId) {
  gh run watch $RunId --repo $Repository --exit-status
  if ($LASTEXITCODE -ne 0) {
    Start-Process "https://github.com/$Repository/actions"
    Write-PublishStatus "deploy_failed" "GitHub Pages deployment failed." $Owner | Out-Null
    throw "GitHub Pages deployment failed."
  }
}
Write-PublishStatus "published" "Mobile cloud site published successfully." $Owner $true | Out-Null

Write-Host ""
Write-Host "The free independent mobile website is online:"
Write-Host $FreshPageUrl
Start-Process $FreshPageUrl
