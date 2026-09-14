#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Deploy Firebase Push Notifications to Beezey Backend

.DESCRIPTION
    This script helps deploy the Firebase push notifications feature:
    1. Copies Firebase service account to layer
    2. Builds Firebase layer with dependencies
    3. Deploys user-api, chat, and backoffice services

.PARAMETER Environment
    Target environment (dev or prod)

.PARAMETER SkipBuild
    Skip SAM build step (use for quick redeployments)

.EXAMPLE
    .\deploy-firebase-notifications.ps1 -Environment dev
#>

param(
    [Parameter(Mandatory=$false)]
    [ValidateSet('dev', 'prod')]
    [string]$Environment = 'dev',
    
    [Parameter(Mandatory=$false)]
    [switch]$SkipBuild
)

$ErrorActionPreference = 'Stop'

Write-Host "======================================" -ForegroundColor Cyan
Write-Host "  Firebase Push Notifications Deploy" -ForegroundColor Cyan
Write-Host "  Environment: $Environment" -ForegroundColor Cyan
Write-Host "======================================" -ForegroundColor Cyan
Write-Host ""

# Paths
$RootDir = Split-Path -Parent $PSScriptRoot
$LayerDir = Join-Path $RootDir "src\lambdas\layers\firebase-admin"
$ModulesDir = Join-Path $RootDir "modules"
$ServiceAccountFile = "beebusy-b0a51-9aaf1bddae28.json"

# Step 1: Verify service account exists
Write-Host "[1/5] Verifying Firebase service account..." -ForegroundColor Yellow
$SourcePath = Join-Path $ModulesDir $ServiceAccountFile

if (-not (Test-Path $SourcePath)) {
    Write-Host "  ❌ ERROR: Firebase service account not found at:" -ForegroundColor Red
    Write-Host "     $SourcePath" -ForegroundColor Red
    Write-Host ""
    Write-Host "  Please ensure the file exists in the modules directory." -ForegroundColor Red
    exit 1
}
Write-Host "  ✓ Service account found" -ForegroundColor Green

# Step 2: Copy service account to layer
Write-Host ""
Write-Host "[2/5] Copying service account to Firebase layer..." -ForegroundColor Yellow
$DestPath = Join-Path $LayerDir "python\$ServiceAccountFile"

# Create directory if it doesn't exist
$LayerPythonDir = Join-Path $LayerDir "python"
if (-not (Test-Path $LayerPythonDir)) {
    New-Item -ItemType Directory -Path $LayerPythonDir -Force | Out-Null
}

Copy-Item $SourcePath $DestPath -Force
Write-Host "  ✓ Service account copied" -ForegroundColor Green

# Step 3: Build Firebase layer
Write-Host ""
Write-Host "[3/5] Building Firebase layer (installing dependencies)..." -ForegroundColor Yellow
Push-Location $LayerDir

try {
    # Check if pip is available
    $pipVersion = & pip --version 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  ❌ ERROR: pip not found. Please install Python and pip." -ForegroundColor Red
        exit 1
    }
    
    Write-Host "  Installing firebase-admin to layer..." -ForegroundColor Gray
    & pip install -r requirements.txt -t python/ --upgrade --quiet
    
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  ❌ ERROR: Failed to install dependencies" -ForegroundColor Red
        exit 1
    }
    
    Write-Host "  ✓ Firebase layer built successfully" -ForegroundColor Green
}
finally {
    Pop-Location
}

# Step 4: Deploy services
Write-Host ""
Write-Host "[4/5] Deploying services..." -ForegroundColor Yellow

$Services = @(
    @{Name="user-api"; Path="infra\services\user-api"},
    @{Name="chat"; Path="infra\services\chat"},
    @{Name="backoffice"; Path="infra\services\backoffice"}
)

foreach ($Service in $Services) {
    Write-Host ""
    Write-Host "  Deploying $($Service.Name)..." -ForegroundColor Cyan
    
    $ServicePath = Join-Path $RootDir $Service.Path
    Push-Location $ServicePath
    
    try {
        if (-not $SkipBuild) {
            Write-Host "    Building..." -ForegroundColor Gray
            & sam build 2>&1 | Out-Null
            
            if ($LASTEXITCODE -ne 0) {
                Write-Host "    ❌ Build failed for $($Service.Name)" -ForegroundColor Red
                exit 1
            }
        }
        
        Write-Host "    Deploying..." -ForegroundColor Gray
        & sam deploy --no-confirm-changeset --no-fail-on-empty-changeset
        
        if ($LASTEXITCODE -ne 0) {
            Write-Host "    ❌ Deploy failed for $($Service.Name)" -ForegroundColor Red
            exit 1
        }
        
        Write-Host "    ✓ $($Service.Name) deployed" -ForegroundColor Green
    }
    finally {
        Pop-Location
    }
}

# Step 5: Summary
Write-Host ""
Write-Host "[5/5] Deployment complete!" -ForegroundColor Green
Write-Host ""
Write-Host "======================================" -ForegroundColor Cyan
Write-Host "  Next Steps:" -ForegroundColor Cyan
Write-Host "======================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "1. Test FCM token registration:" -ForegroundColor White
Write-Host "   POST /users/{userId}/fcm-token" -ForegroundColor Gray
Write-Host ""
Write-Host "2. Test chat notifications:" -ForegroundColor White
Write-Host "   Send a message in a chat" -ForegroundColor Gray
Write-Host ""
Write-Host "3. Test upgrade notifications:" -ForegroundColor White
Write-Host "   Approve/reject documents in backoffice" -ForegroundColor Gray
Write-Host ""
Write-Host "4. Check CloudWatch Logs for:" -ForegroundColor White
Write-Host "   - 'Push notification sent successfully'" -ForegroundColor Gray
Write-Host "   - 'FCM token registered'" -ForegroundColor Gray
Write-Host ""
Write-Host "Documentation: docs/02_architecture/FIREBASE_PUSH_NOTIFICATIONS.md" -ForegroundColor Yellow
Write-Host ""
