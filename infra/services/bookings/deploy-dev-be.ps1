#!/usr/bin/env pwsh
# ============================================================
# Bookings Service - Deploy DEV-BE
# ============================================================
# NOTA: richiede che chat-service-dev-be sia gia' deployato!
# (ChatSharedLayerArn viene auto-rilevato dall'output del chat stack)
# ============================================================

$ErrorActionPreference = "Continue"

$ConfigFile = Join-Path $PSScriptRoot "..\..\..\infra\dev-be-config.ps1"
if (-not (Test-Path $ConfigFile)) {
    Write-Host "[ERROR] Config non trovata. Esegui prima: scripts\create-dev-be-prereqs.ps1" -ForegroundColor Red
    exit 1
}
. $ConfigFile

$Environment        = $DevBe_Environment
$Region             = $DevBe_Region
$StackName          = "bookings-service-dev-be"
$S3Bucket           = $DevBe_ArtifactsBucket
$CognitoUserPoolArn = $DevBe_UserPoolArn
$CognitoUserPoolId  = $DevBe_UserPoolId

if ($CognitoUserPoolArn -eq "PLACEHOLDER_RUN_PREREQS") {
    Write-Host "[ERROR] Cognito non configurato! Esegui: scripts\create-dev-be-prereqs.ps1" -ForegroundColor Red
    exit 1
}

# Auto-rileva ChatSharedLayerArn dall'output del chat stack
Write-Host "[INFO] Rilevo ChatSharedLayerArn dal chat stack..." -ForegroundColor Cyan
$ChatSharedLayerArn = aws cloudformation describe-stacks `
    --stack-name "chat-service-dev-be" `
    --query "Stacks[0].Outputs[?OutputKey=='ChatSharedLayerArn'].OutputValue" `
    --output text --region $Region 2>$null

if (-not $ChatSharedLayerArn -or $ChatSharedLayerArn -eq "None" -or $ChatSharedLayerArn -eq "") {
    Write-Host "[ERROR] ChatSharedLayerArn non trovato!" -ForegroundColor Red
    Write-Host "        Assicurati di aver deployato il chat service prima:" -ForegroundColor Yellow
    Write-Host "        .\infra\services\chat\deploy-dev-be.ps1" -ForegroundColor Yellow
    exit 1
}
Write-Host "   [OK] ChatSharedLayerArn: $ChatSharedLayerArn" -ForegroundColor Green

# Auto-rileva ChatWebSocketApiId dall'output del chat stack
Write-Host "[INFO] Rilevo ChatWebSocketApiId dal chat stack..." -ForegroundColor Cyan
$ChatWebSocketApiId = aws cloudformation describe-stacks `
    --stack-name "chat-service-dev-be" `
    --query "Stacks[0].Outputs[?OutputKey=='ChatWebSocketApiId'].OutputValue" `
    --output text --region $Region 2>$null

if (-not $ChatWebSocketApiId -or $ChatWebSocketApiId -eq "None" -or $ChatWebSocketApiId -eq "") {
    Write-Host "[WARN] ChatWebSocketApiId non trovato, WS notifications non funzioneranno" -ForegroundColor Yellow
    $ChatWebSocketApiId = ""
} else {
    Write-Host "   [OK] ChatWebSocketApiId: $ChatWebSocketApiId" -ForegroundColor Green
}

# Auto-rileva FirebaseAdminLayerArn dall'output del chat stack
Write-Host "[INFO] Rilevo FirebaseAdminLayerArn dal chat stack..." -ForegroundColor Cyan
$FirebaseAdminLayerArn = aws cloudformation describe-stacks `
    --stack-name "chat-service-dev-be" `
    --query "Stacks[0].Outputs[?OutputKey=='FirebaseAdminLayerArn'].OutputValue" `
    --output text --region $Region 2>$null

if (-not $FirebaseAdminLayerArn -or $FirebaseAdminLayerArn -eq "None" -or $FirebaseAdminLayerArn -eq "") {
    Write-Host "   [WARN] FirebaseAdminLayerArn non trovato, push notifications non funzioneranno!" -ForegroundColor Yellow
    $FirebaseAdminLayerArn = ""
} else {
    Write-Host "   [OK] FirebaseAdminLayerArn: $FirebaseAdminLayerArn" -ForegroundColor Green
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "   DEPLOY BOOKINGS SERVICE - DEV-BE" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "Stack:     $StackName" -ForegroundColor Yellow
Write-Host "Region:    $Region" -ForegroundColor Yellow
Write-Host "Bucket:    $S3Bucket" -ForegroundColor Yellow
Write-Host "ChatLayer: $ChatSharedLayerArn" -ForegroundColor Yellow
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# STEP 1: Verifica stack
Write-Host "[STEP 1/8] Verifica stato stack esistente..." -ForegroundColor Green
$stackExists = $false
try {
    $stackStatus = aws cloudformation describe-stacks --stack-name $StackName --region $Region --query 'Stacks[0].StackStatus' --output text 2>$null
    if ($stackStatus -and $stackStatus -ne "None") {
        $stackExists = $true
        Write-Host "   Stack esistente in stato: $stackStatus" -ForegroundColor Yellow
        $problematicStates = @("REVIEW_IN_PROGRESS", "ROLLBACK_COMPLETE", "ROLLBACK_FAILED", "CREATE_FAILED", "DELETE_FAILED", "UPDATE_ROLLBACK_FAILED")
        if ($problematicStates -contains $stackStatus) {
            Write-Host "   [WARN] Stack problematico, cancello..." -ForegroundColor Yellow
            aws cloudformation delete-stack --stack-name $StackName --region $Region
            aws cloudformation wait stack-delete-complete --stack-name $StackName --region $Region 2>$null
            Write-Host "   [OK] Stack cancellato" -ForegroundColor Green
            $stackExists = $false
        }
    }
} catch { Write-Host "   Nessuno stack esistente" -ForegroundColor Gray }

# STEP 2-6: Pulizia, Validate, Build, Package (standard)
Write-Host "[STEP 2/8] Pulizia cache locale..." -ForegroundColor Green
if (Test-Path .aws-sam) { Remove-Item -Recurse -Force .aws-sam }
if (Test-Path packaged.yaml) { Remove-Item -Force packaged.yaml }

if (-not $stackExists) {
    Write-Host "[STEP 3/8] Pulizia artifacts S3..." -ForegroundColor Green
    aws s3 rm "s3://$S3Bucket/bookings-dev-be/" --recursive --region $Region 2>$null
} else { Write-Host "[STEP 3/8] Skip pulizia S3 (update)" -ForegroundColor Gray }

Write-Host "[STEP 4/8] Validazione template..." -ForegroundColor Green
$validateResult = sam validate --template-file template.yaml --region $Region 2>&1
if ($LASTEXITCODE -ne 0) { Write-Host "   [ERROR] Template non valido!`n$validateResult" -ForegroundColor Red; exit 1 }
Write-Host "   [OK] Template valido" -ForegroundColor Gray

Write-Host "[STEP 5/8] Build SAM..." -ForegroundColor Green
sam build --template-file template.yaml 2>&1 | Out-Host
if ($LASTEXITCODE -ne 0) { Write-Host "   [ERROR] Build fallito!" -ForegroundColor Red; exit 1 }
Write-Host "   [OK] Build completato" -ForegroundColor Green

Write-Host "[STEP 6/8] Package su S3..." -ForegroundColor Green
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
sam package --template-file .aws-sam/build/template.yaml `
    --s3-bucket $S3Bucket --s3-prefix "bookings-dev-be/$timestamp" `
    --region $Region --output-template-file packaged.yaml 2>&1 | Out-Host
if ($LASTEXITCODE -ne 0) { Write-Host "   [ERROR] Package fallito!" -ForegroundColor Red; exit 1 }
Write-Host "   [OK] Package completato" -ForegroundColor Green

# STEP 7: Deploy
Write-Host "[STEP 7/8] Deploy via CloudFormation..." -ForegroundColor Green
aws cloudformation deploy `
    --template-file packaged.yaml --stack-name $StackName --region $Region `
    --capabilities CAPABILITY_IAM CAPABILITY_AUTO_EXPAND CAPABILITY_NAMED_IAM `
    --parameter-overrides `
        "Environment=$Environment" `
        "CognitoUserPoolArn=$CognitoUserPoolArn" `
        "CognitoUserPoolId=$CognitoUserPoolId" `
        "ChatSharedLayerArn=$ChatSharedLayerArn" `
        "ChatWebSocketApiId=$ChatWebSocketApiId" `
        "FirebaseAdminLayerArn=$FirebaseAdminLayerArn" `
    --no-fail-on-empty-changeset 2>&1 | Out-Host

if ($LASTEXITCODE -ne 0) {
    Write-Host "   [WARN] Deploy fallito, provo create-stack..." -ForegroundColor Yellow
    aws cloudformation create-stack --template-body "file://packaged.yaml" `
        --stack-name $StackName --region $Region `
        --capabilities CAPABILITY_IAM CAPABILITY_AUTO_EXPAND CAPABILITY_NAMED_IAM `
        --parameters `
            "ParameterKey=Environment,ParameterValue=$Environment" `
            "ParameterKey=CognitoUserPoolArn,ParameterValue=$CognitoUserPoolArn" `
            "ParameterKey=CognitoUserPoolId,ParameterValue=$CognitoUserPoolId" `
            "ParameterKey=ChatSharedLayerArn,ParameterValue=$ChatSharedLayerArn" `
            "ParameterKey=ChatWebSocketApiId,ParameterValue=$ChatWebSocketApiId" `
            "ParameterKey=FirebaseAdminLayerArn,ParameterValue=$FirebaseAdminLayerArn" `
        --disable-rollback 2>&1 | Out-Host
    if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] DEPLOY FALLITO!" -ForegroundColor Red; exit 1 }
    aws cloudformation wait stack-create-complete --stack-name $StackName --region $Region
}

# STEP 8: Cleanup S3
Write-Host "[STEP 8/8] Pulizia versioni vecchie S3..." -ForegroundColor Green
try {
    $cleanupScript = Join-Path $PSScriptRoot "..\..\..\scripts\cleanup-s3-old-versions.ps1"
    & $cleanupScript -Prefix "bookings-dev-be" -KeepVersions 2 -Bucket $S3Bucket -Region $Region -NoConfirm
} catch { Write-Host "   [WARN] Pulizia fallita (non bloccante)" -ForegroundColor Yellow }

Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "   [SUCCESS] DEPLOY BOOKINGS DEV-BE COMPLETATO!" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
aws cloudformation describe-stacks --stack-name $StackName --region $Region `
    --query 'Stacks[0].Outputs[*].[OutputKey,OutputValue]' --output table
Write-Host ""
