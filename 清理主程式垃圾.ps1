$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$Archive = Join-Path $Root ("cleanup_archive_" + $Stamp)
New-Item -ItemType Directory -Path $Archive -Force | Out-Null

$Moved = @()
$FoldersToArchive = Get-ChildItem -LiteralPath $Root -Directory -Force | Where-Object {
    $_.Name -like "*輸出*" -or
    $_.Name -like "*20260605*" -or
    $_.Name -eq "__pycache__" -or
    ($_.Name -match "[^\x00-\x7F]" -and $_.Name.Length -le 5)
}

foreach ($Item in $FoldersToArchive) {
    Move-Item -LiteralPath $Item.FullName -Destination (Join-Path $Archive $Item.Name)
    $Moved += $Item.Name
}

$Removed = @()
$Cache = Join-Path $Root "__pycache__"
if (Test-Path -LiteralPath $Cache) {
    Move-Item -LiteralPath $Cache -Destination (Join-Path $Archive "__pycache__")
    $Moved += "__pycache__"
}

$Report = [ordered]@{
    cleaned_at = (Get-Date).ToString("s")
    root = $Root
    archive = $Archive
    moved_folders = $Moved
    removed_generated_cache = $Removed
    kept_runtime_folders = @("data", "reports", "site", "backups", "logs")
    note = "Old package/output folders were isolated. No database, report history, mobile site, or startup file was deleted. Archive folder uses ASCII name to avoid Windows path encoding errors."
}

$ReportPath = Join-Path $Root "cleanup_report.json"
$Report | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $ReportPath -Encoding UTF8
Write-Host "Main system cleanup completed."
Write-Host "Archive: $Archive"
Write-Host "Report: $ReportPath"
