$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir
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
if (-not (Test-GhRepository "$Owner/$RepoName")) {
  git init
  git checkout -b main
  git config user.name "$Owner"
  git config user.email "$Owner@users.noreply.github.com"
  git add .
  git commit -m "Create free independent mobile 539 system"
  gh repo create $RepoName --public --source . --remote origin --push
} else {
  if (-not (Test-Path ".git")) {
    git init
    git remote add origin "https://github.com/$Owner/$RepoName.git"
    git fetch origin main
    git checkout -b main
    git reset origin/main
  } else {
    git fetch origin main
    git reset origin/main
  }
  git config user.name "$Owner"
  git config user.email "$Owner@users.noreply.github.com"
  git add .
  git diff --cached --quiet
  if ($LASTEXITCODE -ne 0) {
    git commit -m "Update free independent mobile 539 system"
  }
  git push -u origin main
}

try {
  gh api "repos/$Owner/$RepoName/pages" -X POST -f build_type=workflow | Out-Null
} catch {
  Write-Host "GitHub Pages already exists or will be enabled by the workflow."
}

$PageUrl = "https://$Owner.github.io/$RepoName/"
$UrlName = ([char]0x624B) + ([char]0x6A5F) + ([char]0x7368) + ([char]0x7ACB) + ([char]0x7248) + ([char]0x7DB2) + ([char]0x5740) + ".txt"
Set-Content -Path (Join-Path $ScriptDir $UrlName) -Value $PageUrl -Encoding UTF8

Write-Host ""
Write-Host "Starting the first cloud calculation and website deployment..."
gh workflow run daily-update.yml --repo "$Owner/$RepoName"
Start-Sleep -Seconds 5
$RunId = gh run list --repo "$Owner/$RepoName" --workflow daily-update.yml --limit 1 --json databaseId --jq ".[0].databaseId"
if ($RunId) {
  gh run watch $RunId --repo "$Owner/$RepoName" --exit-status
  if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "The first deployment did not finish successfully."
    Write-Host "Opening the GitHub Actions page so the error can be inspected."
    Start-Process "https://github.com/$Owner/$RepoName/actions"
    throw "GitHub Pages deployment failed."
  }
}

Write-Host ""
Write-Host "The free independent mobile website is online:"
Write-Host $PageUrl
Start-Process $PageUrl
