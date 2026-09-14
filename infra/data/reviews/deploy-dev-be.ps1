#!/usr/bin/env pwsh
# ============================================================
# Reviews Data Infrastructure - Deploy DEV-BE
# ============================================================

$ErrorActionPreference = "Stop"
$Environment = "dev-be"
$Region = "eu-south-1"

Write-Host "Deploying Reviews Data Infrastructure ($Environment)..." -ForegroundColor Cyan

try {
    Write-Host "Building SAM template..." -ForegroundColor Yellow
    sam build --config-env $Environment --config-file samconfig.toml

    Write-Host "Deploying to AWS ($Environment)..." -ForegroundColor Yellow
    sam deploy --config-env $Environment --config-file samconfig.toml --no-fail-on-empty-changeset

    Write-Host ""
    Write-Host "[SUCCESS] Reviews data deployment completato!" -ForegroundColor Green
    Write-Host "Stack: dev-be-reviews-data" -ForegroundColor Cyan
}
catch {
    Write-Host "Deployment failed: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
