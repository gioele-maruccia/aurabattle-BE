#!/usr/bin/env pwsh
# Job Roles Data Infrastructure - Deploy Script
# Deploy della tabella DynamoDB per ruoli lavorativi

param(
    [string]$Environment = "dev",
    [string]$Region = "eu-south-1"
)

Write-Host "[DEPLOY] Starting Deploy for Job Roles Data Infrastructure..." -ForegroundColor Cyan
Write-Host "Environment: $Environment" -ForegroundColor Yellow
Write-Host "Region: $Region" -ForegroundColor Yellow
Write-Host ""

# Step 1: Clean build artifacts
Write-Host "[CLEAN] Step 1: Cleaning build artifacts..." -ForegroundColor Green
if (Test-Path .aws-sam) {
    Remove-Item -Recurse -Force .aws-sam
    Write-Host "   [OK] Removed .aws-sam directory" -ForegroundColor Gray
}

# Step 2: Validate template
Write-Host "[VALIDATE] Step 2: Validating template..." -ForegroundColor Green
$validateResult = sam validate --template-file template.yaml --region $Region --lint 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "   [ERROR] Template validation failed!" -ForegroundColor Red
    Write-Host $validateResult -ForegroundColor Red
    exit 1
}
Write-Host "   [OK] Template is valid" -ForegroundColor Gray

# Step 3: Build
Write-Host "[BUILD] Step 3: Building..." -ForegroundColor Green
sam build --template-file template.yaml
if ($LASTEXITCODE -ne 0) {
    Write-Host "   [ERROR] Build failed!" -ForegroundColor Red
    exit 1
}
Write-Host "   [OK] Build completed" -ForegroundColor Gray

# Step 4: Deploy
Write-Host "[DEPLOY] Step 4: Deploying to AWS..." -ForegroundColor Green
sam deploy `
    --template-file .aws-sam/build/template.yaml `
    --stack-name "$Environment-job-roles-data" `
    --region $Region `
    --capabilities CAPABILITY_IAM `
    --no-fail-on-empty-changeset `
    --parameter-overrides `
        Environment=$Environment `
        BillingMode=PAY_PER_REQUEST

if ($LASTEXITCODE -ne 0) {
    Write-Host "   [ERROR] Deploy failed!" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "[SUCCESS] Deploy completed successfully!" -ForegroundColor Green
Write-Host "Stack: $Environment-job-roles-data" -ForegroundColor Cyan
Write-Host ""
