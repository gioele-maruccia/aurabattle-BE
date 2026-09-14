#!/usr/bin/env pwsh
<#
.DESCRIPTION
    Deploys the Reviews DynamoDB table infrastructure to AWS (Production)
.EXAMPLE
    .\deploy-prod.ps1
#>

$ErrorActionPreference = "Stop"

Write-Host "🚀 Deploying Reviews Data Infrastructure (prod)..." -ForegroundColor Cyan
Write-Host "⚠️  WARNING: This will deploy to PRODUCTION!" -ForegroundColor Red

$confirm = Read-Host "Are you sure? (yes/no)"
if ($confirm -ne "yes") {
    Write-Host "❌ Deployment cancelled." -ForegroundColor Yellow
    exit 0
}

try {
    # Build
    Write-Host "`n📦 Building SAM template..." -ForegroundColor Yellow
    sam build --config-env prod

    # Deploy
    Write-Host "`n🌍 Deploying to AWS (prod)..." -ForegroundColor Yellow
    sam deploy --config-env prod

    Write-Host "`n✅ Production deployment completed successfully!" -ForegroundColor Green
    Write-Host "The Reviews DynamoDB table has been created/updated in production." -ForegroundColor Green
}
catch {
    Write-Host "`n❌ Deployment failed!" -ForegroundColor Red
    Write-Host ('Error: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}

