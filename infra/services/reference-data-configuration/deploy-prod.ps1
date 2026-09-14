#!/usr/bin/env pwsh
# ============================================================
# Reference Data Configuration Service - Deploy PROD - VERSIONE DEFINITIVA
# ============================================================
# Questo script fa un deploy PULITO e COMPLETO su PROD
# Bypassa SAM deploy e usa direttamente CloudFormation per 
# evitare problemi con AWS::EarlyValidation::ResourceExistenceCheck
# ============================================================

param([switch]$Force)

$ErrorActionPreference = "Continue"
$Environment = "prod"
$Region = "eu-south-1"
$StackName = "prod-reference-data-configuration"
$S3Bucket = "beezey-prod"
$JobRolesTableName = "prod-JobRoles"
$ContractsTableName = "prod-Contracts"
$JobCategoriesTableName = "prod-JobCategories"
$EmploymentTypesTableName = "prod-EmploymentTypes"

Write-Host ""
Write-Host "============================================" -ForegroundColor Red
Write-Host "   DEPLOY REFERENCE DATA CONFIG - PRODUCTION" -ForegroundColor Red
Write-Host "============================================" -ForegroundColor Red
Write-Host "Stack:  $StackName" -ForegroundColor Yellow
Write-Host "Region: $Region" -ForegroundColor Yellow
Write-Host "Bucket: $S3Bucket" -ForegroundColor Yellow
Write-Host "============================================" -ForegroundColor Red
Write-Host ""

# ====================
# CONFERMA PRODUZIONE
# ====================
Write-Host "[WARNING] Stai per fare il deploy in PRODUZIONE!" -ForegroundColor Yellow
Write-Host "Questo modificherà i servizi LIVE!" -ForegroundColor Yellow
Write-Host ""
if (-not $Force) {
    $confirm = Read-Host "Sei sicuro di voler procedere? (digita 'yes' per confermare)"
    if ($confirm -ne "yes") {
        Write-Host ""
        Write-Host "[ABORT] Deploy annullato" -ForegroundColor Yellow
        exit 0
    }
}
Write-Host ""
Write-Host "[OK] Confermato, procedo con il deploy PROD..." -ForegroundColor Green
Write-Host ""

# ====================
# STEP 1: Verifica e pulizia stack problematici
# ====================
Write-Host "[STEP 1/7] Verifica stato stack esistente..." -ForegroundColor Green
$stackExists = $false
try {
    $stackStatus = aws cloudformation describe-stacks --stack-name $StackName --region $Region --query 'Stacks[0].StackStatus' --output text 2>$null
    if ($stackStatus -and $stackStatus -ne "None") {
        $stackExists = $true
        Write-Host "   Stack esistente in stato: $stackStatus" -ForegroundColor Yellow
        
        # Stati problematici che NON permettono il deploy
        $problematicStates = @("REVIEW_IN_PROGRESS", "ROLLBACK_COMPLETE", "ROLLBACK_FAILED", "CREATE_FAILED", "DELETE_FAILED", "UPDATE_ROLLBACK_FAILED")
        
        if ($problematicStates -contains $stackStatus) {
            Write-Host ""
            Write-Host "============================================" -ForegroundColor Red
            Write-Host "   [ERRORE] STACK IN STATO PROBLEMATICO" -ForegroundColor Red
            Write-Host "============================================" -ForegroundColor Red
            Write-Host ""
            Write-Host "Stack: $StackName" -ForegroundColor Yellow
            Write-Host "Stato: $stackStatus" -ForegroundColor Red
            Write-Host ""
            Write-Host "⚠️  NON SI CANCELLA MAI UNO STACK DI PRODUZIONE!" -ForegroundColor Red
            Write-Host ""
            Write-Host "Risolvi manualmente via AWS CloudFormation Console:" -ForegroundColor Yellow
            Write-Host "1. Vai a: https://console.aws.amazon.com/cloudformation" -ForegroundColor Gray
            Write-Host "2. Seleziona lo stack: $StackName" -ForegroundColor Gray
            Write-Host "3. Clicca 'Stack Actions' -> 'Continue Update Rollback'" -ForegroundColor Gray
            Write-Host "4. Riprova il deploy quando lo stack è in UPDATE_COMPLETE o DELETE_COMPLETE" -ForegroundColor Gray
            Write-Host ""
            exit 1
        }
    }
} catch {
    Write-Host "   Nessuno stack esistente, procedo con la creazione" -ForegroundColor Gray
}

# ====================
# STEP 2: Pulizia cache locale
# ====================
Write-Host "[STEP 2/7] Pulizia cache locale..." -ForegroundColor Green
if (Test-Path .aws-sam) {
    Remove-Item -Recurse -Force .aws-sam
    Write-Host "   [OK] Rimossa directory .aws-sam" -ForegroundColor Gray
}
if (Test-Path packaged.yaml) {
    Remove-Item -Force packaged.yaml
    Write-Host "   [OK] Rimosso packaged.yaml" -ForegroundColor Gray
}

# ====================
# STEP 3: Pulizia artifacts S3 (solo per nuovi deploy)
# ====================
if (-not $stackExists) {
    Write-Host "[STEP 3/7] Pulizia artifacts S3..." -ForegroundColor Green
    aws s3 rm "s3://$S3Bucket/reference-data-configuration/" --recursive --region $Region 2>$null
    Write-Host "   [OK] Pulita cartella reference-data-configuration/ su S3" -ForegroundColor Gray
} else {
    Write-Host "[STEP 3/7] Skip pulizia S3 (stack esistente, è un update)" -ForegroundColor Gray
}

# ====================
# STEP 4: Validate template
# ====================
Write-Host "[STEP 4/7] Validazione template..." -ForegroundColor Green
$validateResult = sam validate --template-file template.yaml --region $Region 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "   [ERROR] Template non valido!" -ForegroundColor Red
    Write-Host $validateResult -ForegroundColor Red
    exit 1
}
Write-Host "   [OK] Template valido" -ForegroundColor Gray

# ====================
# STEP 5: Build
# ====================
Write-Host "[STEP 5/7] Build SAM..." -ForegroundColor Green
sam build --template-file template.yaml 2>&1 | Out-Host
if ($LASTEXITCODE -ne 0) {
    Write-Host "   [ERROR] Build fallito!" -ForegroundColor Red
    exit 1
}
Write-Host "   [OK] Build completato" -ForegroundColor Green

# ====================
# STEP 6: Package
# ====================
Write-Host "[STEP 6/7] Package artifacts su S3..." -ForegroundColor Green
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
sam package `
    --template-file .aws-sam/build/template.yaml `
    --s3-bucket $S3Bucket `
    --s3-prefix "reference-data-configuration/$timestamp" `
    --region $Region `
    --output-template-file packaged.yaml 2>&1 | Out-Host

if ($LASTEXITCODE -ne 0) {
    Write-Host "   [ERROR] Package fallito!" -ForegroundColor Red
    exit 1
}
Write-Host "   [OK] Package completato" -ForegroundColor Green

# ====================
# STEP 7: Deploy via CloudFormation CLI
# ====================
# IMPORTANTE: Usiamo "aws cloudformation deploy" invece di "sam deploy"
# per evitare i problemi con i SAM hooks di validazione
# ====================
Write-Host "[STEP 7/7] Deploy via CloudFormation..." -ForegroundColor Green
Write-Host "   (Usa CloudFormation CLI per evitare problemi con SAM hooks)" -ForegroundColor Gray
Write-Host ""

aws cloudformation deploy `
    --template-file packaged.yaml `
    --stack-name $StackName `
    --region $Region `
    --capabilities CAPABILITY_IAM CAPABILITY_AUTO_EXPAND CAPABILITY_NAMED_IAM `
    --parameter-overrides `
        "Environment=$Environment" `
        "JobRolesTableName=$JobRolesTableName" `
        "ContractsTableName=$ContractsTableName" `
        "JobCategoriesTableName=$JobCategoriesTableName" `
        "EmploymentTypesTableName=$EmploymentTypesTableName" `
    --no-fail-on-empty-changeset 2>&1 | Out-Host

$deployResult = $LASTEXITCODE

if ($deployResult -ne 0) {
    Write-Host ""
    Write-Host "   [WARN] Deploy CloudFormation fallito, provo con create-stack..." -ForegroundColor Yellow
    
    # Secondo tentativo: create-stack con --disable-rollback
    aws cloudformation create-stack `
        --template-body "file://packaged.yaml" `
        --stack-name $StackName `
        --region $Region `
        --capabilities CAPABILITY_IAM CAPABILITY_AUTO_EXPAND CAPABILITY_NAMED_IAM `
        --parameters `
            "ParameterKey=Environment,ParameterValue=$Environment" `
            "ParameterKey=JobRolesTableName,ParameterValue=$JobRolesTableName" `
            "ParameterKey=ContractsTableName,ParameterValue=$ContractsTableName" `
            "ParameterKey=JobCategoriesTableName,ParameterValue=$JobCategoriesTableName" `
            "ParameterKey=EmploymentTypesTableName,ParameterValue=$EmploymentTypesTableName" `
        --disable-rollback 2>&1 | Out-Host
    
    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "============================================" -ForegroundColor Red
        Write-Host "   [ERROR] DEPLOY FALLITO!" -ForegroundColor Red
        Write-Host "============================================" -ForegroundColor Red
        Write-Host ""
        Write-Host "Possibili cause:" -ForegroundColor Yellow
        Write-Host "1. Controlla CloudFormation console per dettagli errore" -ForegroundColor Gray
        Write-Host "2. Potrebbe esserci uno stack in stato transitorio" -ForegroundColor Gray
        Write-Host "3. Controlla che tutti i prerequisiti esistano (DynamoDB)" -ForegroundColor Gray
        exit 1
    }
    
    Write-Host ""
    Write-Host "   Attendo creazione stack (max 10 min)..." -ForegroundColor Gray
    aws cloudformation wait stack-create-complete --stack-name $StackName --region $Region
    
    if ($LASTEXITCODE -ne 0) {
        Write-Host "   [ERROR] Creazione stack fallita!" -ForegroundColor Red
        Write-Host "   Controlla la console CloudFormation per i dettagli" -ForegroundColor Yellow
        exit 1
    }
}

# ====================
# STEP 8: Cleanup old S3 versions
# ====================
Write-Host "[STEP 8/8] Pulizia versioni vecchie S3..." -ForegroundColor Green
try {
    $cleanupScript = Join-Path $PSScriptRoot "..\..\..\scripts\cleanup-s3-old-versions.ps1"
    & $cleanupScript -Prefix "reference-data-configuration" -KeepVersions 2 -Bucket $S3Bucket -Region $Region -NoConfirm
    Write-Host "   [OK] Pulizia completata" -ForegroundColor Gray
} catch {
    Write-Host "   [WARN] Pulizia fallita (non bloccante): $($_.Exception.Message)" -ForegroundColor Yellow
}

# ====================
# SUCCESS!
# ====================
Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "   [SUCCESS] DEPLOY PROD COMPLETATO!" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""

# Show stack outputs
Write-Host "[INFO] Stack Outputs:" -ForegroundColor Cyan
aws cloudformation describe-stacks `
    --stack-name $StackName `
    --region $Region `
    --query 'Stacks[0].Outputs[*].[OutputKey,OutputValue]' `
    --output table

Write-Host ""
Write-Host "[READY] Reference Data Configuration Service PROD pronto!" -ForegroundColor Green
Write-Host ""
