<#
.SYNOPSIS
    QuizX Safe Client Update Script for SQL Server 2025 Express
.DESCRIPTION
    Performs pre-flight checks, verifies environment, creates native SQL Server backup,
    inspects pending migrations, applies migrations, and runs Django checks.
.EXAMPLE
    .\update_quizx.ps1
    .\update_quizx.ps1 -SkipBackup
#>

param (
    [switch]$SkipBackup
)

$ErrorActionPreference = "Stop"

Write-Host "=====================================================" -ForegroundColor Cyan
Write-Host " QUIZX PRODUCTION UPDATE WORKFLOW" -ForegroundColor Cyan
Write-Host "=====================================================" -ForegroundColor Cyan

# 1. Check Python
try {
    $pyVersion = python --version 2>&1
    Write-Host "[OK] Python detected: $pyVersion" -ForegroundColor Green
} catch {
    Write-Host "[ERROR] Python is not installed or not in PATH!" -ForegroundColor Red
    exit 1
}

# 2. Check .env
if (!(Test-Path ".env")) {
    Write-Host "[ERROR] .env file not found in $(Get-Location)!" -ForegroundColor Red
    Write-Host "Tip: Copy .env.example to .env and configure your database parameters." -ForegroundColor Yellow
    exit 1
}
Write-Host "[OK] Environment file (.env) found." -ForegroundColor Green

# 3. Invoke Python update orchestrator
$pyArgs = @("update_quizx.py")
if ($SkipBackup) {
    $pyArgs += "--skip-backup"
}

python @pyArgs
$exitCode = $LASTEXITCODE

if ($exitCode -eq 0) {
    Write-Host "`n[SUCCESS] QuizX update completed safely." -ForegroundColor Green
} else {
    Write-Host "`n[FAILED] QuizX update failed with exit code $exitCode." -ForegroundColor Red
}

exit $exitCode
