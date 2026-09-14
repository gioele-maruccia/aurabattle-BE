#!/usr/bin/env pwsh
# ============================================================
# Backoffice Service - Deploy DEV
# ============================================================

$ErrorActionPreference = "Continue"
$Environment = "dev"
$Region = "eu-south-1"
$StackName = "backoffice-service-dev"
$S3Bucket = "beezey-dev"
$CognitoUserPoolId = "eu-south-1_0oK9agPYd"
$ExistingBucketName = "beezey-dev-user-documents"
$ExistingTableName = "dev-UserDocuments"
$KMSKeyId = "dba20d4f-3d24-4f4d-a476-4e5a42a7533b"

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "   DEPLOY BACKOFFICE SERVICE - DEV" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "Stack:  $StackName" -ForegroundColor Yellow
Write-Host "Region: $Region" -ForegroundColor Yellow
Write-Host "Bucket: $S3Bucket" -ForegroundColor Yellow
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# ====================
# STEP 1: Verifica stato stack esistente
# ====================
Write-Host "[STEP 1/9] Verifica stato stack esistente..." -ForegroundColor Green
$stackExists = $false
try {
    $stackStatus = aws cloudformation describe-stacks --stack-name $StackName --region $Region --query 'Stacks[0].StackStatus' --output text 2>$null
    if ($stackStatus -and $stackStatus -ne "None") {
        $stackExists = $true
        Write-Host "   Stack esistente in stato: $stackStatus" -ForegroundColor Yellow
        
        # Stati problematici che richiedono cancellazione
        $problematicStates = @("REVIEW_IN_PROGRESS", "ROLLBACK_COMPLETE", "ROLLBACK_FAILED", "CREATE_FAILED", "DELETE_FAILED", "UPDATE_ROLLBACK_FAILED")
        
        if ($problematicStates -contains $stackStatus) {
            Write-Host "   [WARN] Stack in stato problematico, cancello..." -ForegroundColor Yellow
            aws cloudformation delete-stack --stack-name $StackName --region $Region
            Write-Host "   Attendo cancellazione completa (max 5 min)..." -ForegroundColor Gray
            aws cloudformation wait stack-delete-complete --stack-name $StackName --region $Region 2>$null
            Write-Host "   [OK] Stack cancellato" -ForegroundColor Green
            $stackExists = $false
        }
    }
} catch {
    Write-Host "   Nessuno stack esistente, procedo con la creazione" -ForegroundColor Gray
}

# ====================
# STEP 2: Pulizia cache locale
# ====================
Write-Host "[STEP 2/9] Pulizia cache locale..." -ForegroundColor Green
if (Test-Path .aws-sam) {
    Remove-Item -Recurse -Force .aws-sam
    Write-Host "   [OK] Rimossa directory .aws-sam" -ForegroundColor Gray
}
if (Test-Path packaged.yaml) {
    Remove-Item -Force packaged.yaml
    Write-Host "   [OK] Rimosso packaged.yaml" -ForegroundColor Gray
}

# ====================
# STEP 3: Pulizia artifacts S3
# ====================
if (-not $stackExists) {
    Write-Host "[STEP 3/9] Pulizia artifacts S3..." -ForegroundColor Green
    aws s3 rm "s3://$S3Bucket/backoffice/" --recursive --region $Region 2>$null
    Write-Host "   [OK] Pulita cartella backoffice/ su S3" -ForegroundColor Gray
} else {
    Write-Host "[STEP 3/9] Skip pulizia S3 (stack esistente, è un update)" -ForegroundColor Gray
}

# ====================
# STEP 4: Copia Firebase service account nel layer
# ====================
Write-Host "[STEP 4/9] Verifica e copia Firebase service account..." -ForegroundColor Green
$RootDir = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
$LayerDir = Join-Path $RootDir "src\lambdas\layers\firebase-admin"
$ModulesDir = Join-Path $RootDir "modules"
$ServiceAccountFile = "beebusy-99d60-firebase-adminsdk-fbsvc-b37bca6781.json"
$SourcePath = Join-Path $ModulesDir $ServiceAccountFile
$DestPath = Join-Path $LayerDir "python\$ServiceAccountFile"

if (-not (Test-Path $SourcePath)) {
    Write-Host "   [ERROR] Firebase service account non trovato:" -ForegroundColor Red
    Write-Host "   $SourcePath" -ForegroundColor Red
    Write-Host ""
    Write-Host "   CAUSA: Il file del service account Firebase è necessario per le notifiche push!" -ForegroundColor Yellow
    Write-Host "   SOLUZIONE: Copia il file nella directory modules/" -ForegroundColor Yellow
    exit 1
}

# Crea directory se non esiste
$LayerPythonDir = Join-Path $LayerDir "python"
if (-not (Test-Path $LayerPythonDir)) {
    New-Item -ItemType Directory -Path $LayerPythonDir -Force | Out-Null
}

Copy-Item $SourcePath $DestPath -Force
Write-Host "   [OK] Service account copiato nel Firebase layer" -ForegroundColor Green

# Verifica che requirements.txt esista
$RequirementsPath = Join-Path $LayerDir "requirements.txt"
if (-not (Test-Path $RequirementsPath)) {
    Write-Host "   [WARN] requirements.txt non trovato, installo dipendenze Firebase..." -ForegroundColor Yellow
    Push-Location $LayerDir
    & pip install "google-auth>=2.26.0" "requests>=2.31.0" -t python/ --upgrade --quiet
    Pop-Location
}

# ====================
# STEP 5: Validate template
# ====================
Write-Host "[STEP 5/9] Validazione template..." -ForegroundColor Green
$validateResult = sam validate --template-file template.yaml --region $Region 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "   [ERROR] Template non valido!" -ForegroundColor Red
    Write-Host $validateResult -ForegroundColor Red
    exit 1
}
Write-Host "   [OK] Template valido" -ForegroundColor Gray

# ====================
# STEP 6: Build
# ====================
Write-Host "[STEP 6/9] Build SAM..." -ForegroundColor Green
sam build --template-file template.yaml 2>&1 | Out-Host
if ($LASTEXITCODE -ne 0) {
    Write-Host "   [ERROR] Build fallito!" -ForegroundColor Red
    exit 1
}
Write-Host "   [OK] Build completato" -ForegroundColor Green

# ====================
# STEP 7: Package
# ====================
Write-Host "[STEP 7/9] Package artifacts su S3..." -ForegroundColor Green
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
sam package `
    --template-file .aws-sam/build/template.yaml `
    --s3-bucket $S3Bucket `
    --s3-prefix "backoffice/$timestamp" `
    --region $Region `
    --output-template-file packaged.yaml 2>&1 | Out-Host

if ($LASTEXITCODE -ne 0) {
    Write-Host "   [ERROR] Package fallito!" -ForegroundColor Red
    exit 1
}
Write-Host "   [OK] Package completato" -ForegroundColor Green

# ====================
# STEP 8: Deploy via CloudFormation
# ====================
Write-Host "[STEP 8/9] Deploy via CloudFormation..." -ForegroundColor Green
Write-Host "   (Usa CloudFormation CLI per evitare problemi con SAM hooks)" -ForegroundColor Gray
Write-Host ""

aws cloudformation deploy `
    --template-file packaged.yaml `
    --stack-name $StackName `
    --region $Region `
    --capabilities CAPABILITY_IAM CAPABILITY_AUTO_EXPAND CAPABILITY_NAMED_IAM `
    --parameter-overrides `
        "Environment=$Environment" `
        "CognitoUserPoolId=$CognitoUserPoolId" `
        "ExistingBucketName=$ExistingBucketName" `
        "ExistingTableName=$ExistingTableName" `
        "KMSKeyId=$KMSKeyId" `
    --no-fail-on-empty-changeset 2>&1 | Out-Host

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "   [WARN] Deploy CloudFormation fallito, provo con create-stack..." -ForegroundColor Yellow
    aws cloudformation create-stack `
        --template-body "file://packaged.yaml" `
        --stack-name $StackName `
        --region $Region `
        --capabilities CAPABILITY_IAM CAPABILITY_AUTO_EXPAND CAPABILITY_NAMED_IAM `
        --parameters `
            "ParameterKey=Environment,ParameterValue=$Environment" `
            "ParameterKey=CognitoUserPoolId,ParameterValue=$CognitoUserPoolId" `
            "ParameterKey=ExistingBucketName,ParameterValue=$ExistingBucketName" `
            "ParameterKey=ExistingTableName,ParameterValue=$ExistingTableName" `
            "ParameterKey=KMSKeyId,ParameterValue=$KMSKeyId" `
        --disable-rollback 2>&1 | Out-Host
    if ($LASTEXITCODE -ne 0) { Write-Host "   [ERROR] DEPLOY FALLITO!" -ForegroundColor Red; exit 1 }
    aws cloudformation wait stack-create-complete --stack-name $StackName --region $Region
}

# ====================
# STEP 9: Pulizia versioni vecchie S3
# ====================
Write-Host "[STEP 9/9] Pulizia versioni vecchie S3..." -ForegroundColor Green
try {
    & "$PSScriptRoot\..\..\..\scripts\cleanup-s3-old-versions.ps1" -BucketName $S3Bucket -Prefix "backoffice/" -KeepVersions 3 2>&1 | Out-Null
    Write-Host "   [OK] Pulizia completata" -ForegroundColor Gray
} catch {
    Write-Host "   [WARN] Pulizia fallita (non bloccante): $($_.Exception.Message)" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "   [SUCCESS] DEPLOY DEV COMPLETATO!" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""

# ====================
# Show stack outputs
# ====================
Write-Host "[INFO] Stack Outputs:" -ForegroundColor Cyan
aws cloudformation describe-stacks `
    --stack-name $StackName `
    --region $Region `
    --query 'Stacks[0].Outputs' `
    --output table

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "   BASE URL PER FRONTEND:" -ForegroundColor Yellow
$baseUrl = aws cloudformation describe-stacks `
    --stack-name $StackName `
    --region $Region `
    --query 'Stacks[0].Outputs[?OutputKey==`BackofficeApiEndpoint`].OutputValue' `
    --output text

Write-Host "   $baseUrl" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "[READY] Backoffice Service DEV pronto!" -ForegroundColor Green
