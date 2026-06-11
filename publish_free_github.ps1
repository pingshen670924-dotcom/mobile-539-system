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
Ensure-Command "git" "Git.Git"
Ensure-Command "gh" "GitHub.cli"

if (-not (Test-GhAuthentication)) {
  Write-Host "A GitHub official login page will open. Approve the login once."
  gh auth login --web --git-protocol https
  if ($LASTEXITCODE -ne 0) {
    throw "GitHub login was not completed."
  }
}

$Owner = gh api user --jq .login
if (-not $Owner) {
  throw "The GitHub account name could not be detected."
}

$Repository = "$Owner/$RepoName"
$RepositoryExists = Test-GhRepository $Repository
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
$UrlName = ([char]0x624B) + ([char]0x6A5F) + ([char]0x7368) + ([char]0x7ACB) + ([char]0x7248) + ([char]0x7DB2) + ([char]0x5740) + ".txt"
Set-Content -Path (Join-Path $ScriptDir $UrlName) -Value $PageUrl -Encoding UTF8

Write-Host ""
Write-Host "Starting the cloud calculation and website deployment..."
gh workflow run daily-update.yml --repo $Repository
if ($LASTEXITCODE -ne 0) {
  throw "The cloud update workflow could not be started."
}

Start-Sleep -Seconds 5
$RunId = gh run list --repo $Repository --workflow daily-update.yml --limit 1 --json databaseId --jq ".[0].databaseId"
if ($RunId) {
  gh run watch $RunId --repo $Repository --exit-status
  if ($LASTEXITCODE -ne 0) {
    Start-Process "https://github.com/$Repository/actions"
    throw "GitHub Pages deployment failed."
  }
}

Write-Host ""
Write-Host "The free independent mobile website is online:"
Write-Host $PageUrl
Start-Process $PageUrl
