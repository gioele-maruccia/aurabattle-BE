param(
    [ValidateSet("dev", "prod")]
    [string]$Environment = "dev"
)

$ErrorActionPreference = "Stop"

Write-Host "Deploying Reviews Data Infrastructure ($Environment)..." -ForegroundColor Cyan

try {
    Write-Host "Building SAM template..." -ForegroundColor Yellow
    sam build --config-env $Environment

    Write-Host "Deploying to AWS ($Environment)..." -ForegroundColor Yellow
    sam deploy --config-env $Environment

    Write-Host "Deployment completed successfully!" -ForegroundColor Green
}
catch {
    Write-Host "Deployment failed!" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
