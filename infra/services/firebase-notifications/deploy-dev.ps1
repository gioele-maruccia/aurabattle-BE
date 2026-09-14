#!/usr/bin/env pwsh
# ============================================================
# Firebase Notifications Setup - Deploy DEV
# ============================================================
# Prepara il Firebase layer (service account + dipendenze).
# Il deploy di user-api, chat e backoffice va fatto separatamente.
# ============================================================

$ErrorActionPreference = "Continue"
$Environment = "dev"
$Region = "eu-south-1"

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "   FIREBASE PUSH NOTIFICATIONS - DEV" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "Environment: $Environment" -ForegroundColor Yellow
Write-Host "Region:      $Region" -ForegroundColor Yellow
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# Paths
$RootDir = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
$LayerDir = Join-Path $RootDir "src\lambdas\layers\firebase-admin"
$ModulesDir = Join-Path $RootDir "modules"
$ServiceAccountFile = "beebusy-99d60-firebase-adminsdk-fbsvc-b37bca6781.json"

# ====================
# STEP 1: Verifica Firebase service account
# ====================
Write-Host "[STEP 1/3] Verifica Firebase service account..." -ForegroundColor Green
$SourcePath = Join-Path $ModulesDir $ServiceAccountFile

if (-not (Test-Path $SourcePath)) {
    Write-Host "   [ERROR] Firebase service account non trovato:" -ForegroundColor Red
    Write-Host "   $SourcePath" -ForegroundColor Red
    Write-Host ""
    Write-Host "   Assicurati che il file esista nella directory modules/" -ForegroundColor Red
    exit 1
}
Write-Host "   [OK] Service account trovato" -ForegroundColor Green

# ====================
# STEP 2: Copia service account nel layer
# ====================
Write-Host ""
Write-Host "[STEP 2/3] Copia service account nel Firebase layer..." -ForegroundColor Green
$DestPath = Join-Path $LayerDir "python\$ServiceAccountFile"
$LayerPythonDir = Join-Path $LayerDir "python"

if (-not (Test-Path $LayerPythonDir)) {
    New-Item -ItemType Directory -Path $LayerPythonDir -Force | Out-Null
}

Copy-Item $SourcePath $DestPath -Force
Write-Host "   [OK] Service account copiato" -ForegroundColor Green

# ====================
# STEP 3: Build Firebase layer
# ====================
Write-Host ""
Write-Host "[STEP 3/3] Build Firebase layer (installo dipendenze)..." -ForegroundColor Green
Push-Location $LayerDir

try {
    Write-Host "   Installo firebase-admin in python/..." -ForegroundColor Gray
    & pip install -r requirements.txt -t python/ --upgrade --quiet
    
    if ($LASTEXITCODE -ne 0) {
        Write-Host "   [ERROR] Installazione dipendenze fallita" -ForegroundColor Red
        Pop-Location
        exit 1
    }
    
    Write-Host "   [OK] Firebase layer pronto" -ForegroundColor Green
}
finally {
    Pop-Location
}

# ====================
# Summary
# ====================
Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "   FIREBASE LAYER PRONTO!" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
Write-Host "Layer preparato. Deploya separatamente:" -ForegroundColor White
Write-Host "  cd infra/services/user-api  ; .\deploy-dev.ps1" -ForegroundColor Gray
Write-Host "  cd infra/services/chat      ; .\deploy-dev.ps1" -ForegroundColor Gray
Write-Host "  cd infra/services/backoffice; .\deploy-dev.ps1" -ForegroundColor Gray
Write-Host ""
