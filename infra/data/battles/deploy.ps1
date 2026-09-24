#!/usr/bin/env pwsh
# Battles Data Infrastructure - Deploy Script
# Deploy della tabella DynamoDB per le battle

param(
    [string]$Environment = "dev-aurabattle",
    [string]$Region = "eu-south-1"
)

Write-Host "[DEPLOY] Starting Deploy for Battles Data Infrastructure..." -ForegroundColor Cyan
Write-Host "Environment: $Environment" -ForegroundColor Yellow
Write-Host "Region: $Region" -ForegroundColor Yellow
Write-Host ""

if (Test-Path .aws-sam) {
    Remove-Item -Recurse -Force .aws-sam
    Write-Host "   [OK] Removed .aws-sam directory" -ForegroundColor Gray
}

Write-Host "[VALIDATE] Validating template..." -ForegroundColor Green
$validateResult = sam validate --template-file template.yaml --region $Region --lint 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "   [ERROR] Template validation failed!" -ForegroundColor Red
    Write-Host $validateResult -ForegroundColor Red
    exit 1
}
Write-Host "   [OK] Template is valid" -ForegroundColor Gray

Write-Host "[BUILD] Building..." -ForegroundColor Green
sam build --template-file template.yaml
if ($LASTEXITCODE -ne 0) {
    Write-Host "   [ERROR] Build failed!" -ForegroundColor Red
    exit 1
}
Write-Host "   [OK] Build completed" -ForegroundColor Gray

Write-Host "[DEPLOY] Deploying to AWS..." -ForegroundColor Green
sam deploy `
    --template-file .aws-sam/build/template.yaml `
    --stack-name "$Environment-battles-data" `
    --region $Region `
    --capabilities CAPABILITY_IAM `
    --no-fail-on-empty-changeset `
    --tags Project=aurabattle Environment=$Environment `
    --parameter-overrides `
        Environment=$Environment

if ($LASTEXITCODE -ne 0) {
    Write-Host "   [ERROR] Deploy failed!" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "[SUCCESS] Deploy completed successfully!" -ForegroundColor Green
Write-Host "Stack: $Environment-battles-data" -ForegroundColor Cyan
Write-Host ""
