#!/usr/bin/env pwsh
# ============================================================
# Cognito Core Setup - Deploy DEV-BE
# ============================================================
# Deploy della Lambda PostConfirmation e configurazione Cognito
# per l'ambiente dev-be (Backend Developers)
# ============================================================

$ErrorActionPreference = "Continue"

# Carica configurazione dev-be
$ConfigFile = Join-Path $PSScriptRoot "..\..\..\infra\dev-be-config.ps1"
if (-not (Test-Path $ConfigFile)) {
    Write-Host "[ERROR] Config non trovata. Esegui prima: scripts\create-dev-be-prereqs.ps1" -ForegroundColor Red
    exit 1
}
. $ConfigFile

$Environment             = $DevBe_Environment
$Region                  = $DevBe_Region
$StackName               = "dev-be-core-cognito-setup"
$S3Bucket                = $DevBe_ArtifactsBucket
$UserProfilesTableName   = $DevBe_UserProfilesTable
$UserPoolId              = $DevBe_UserPoolId
$UserPoolArn             = $DevBe_UserPoolArn
$ClientId                = $DevBe_ClientId

if ($UserPoolId -eq "PLACEHOLDER_RUN_PREREQS") {
    Write-Host "[ERROR] Cognito User Pool non configurato!" -ForegroundColor Red
    Write-Host "        Esegui prima: scripts\create-dev-be-prereqs.ps1" -ForegroundColor Yellow
    exit 1
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "   DEPLOY COGNITO SETUP - DEV-BE" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "Stack:     $StackName" -ForegroundColor Yellow
Write-Host "Region:    $Region" -ForegroundColor Yellow
Write-Host "Bucket:    $S3Bucket" -ForegroundColor Yellow
Write-Host "UserPool:  $UserPoolId" -ForegroundColor Yellow
Write-Host "============================================" -ForegroundColor Cyan
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
Write-Host "[STEP 2/7] Pulizia cache locale..." -ForegroundColor Green
if (Test-Path .aws-sam) { Remove-Item -Recurse -Force .aws-sam; Write-Host "   [OK] Rimossa .aws-sam" -ForegroundColor Gray }
if (Test-Path packaged.yaml) { Remove-Item -Force packaged.yaml; Write-Host "   [OK] Rimosso packaged.yaml" -ForegroundColor Gray }

# ====================
# STEP 3: Pulizia artifacts S3 (solo per nuovi deploy)
# ====================
if (-not $stackExists) {
    Write-Host "[STEP 3/7] Pulizia artifacts S3..." -ForegroundColor Green
    aws s3 rm "s3://$S3Bucket/cognito-setup-dev-be/" --recursive --region $Region 2>$null
    Write-Host "   [OK] Pulita cartella cognito-setup-dev-be/ su S3" -ForegroundColor Gray
} else {
    Write-Host "[STEP 3/7] Skip pulizia S3 (stack esistente, e' un update)" -ForegroundColor Gray
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
if ($LASTEXITCODE -ne 0) { Write-Host "   [ERROR] Build fallito!" -ForegroundColor Red; exit 1 }
Write-Host "   [OK] Build completato" -ForegroundColor Green

# ====================
# STEP 6: Package
# ====================
Write-Host "[STEP 6/7] Package artifacts su S3..." -ForegroundColor Green
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
sam package `
    --template-file .aws-sam/build/template.yaml `
    --s3-bucket $S3Bucket `
    --s3-prefix "cognito-setup-dev-be/$timestamp" `
    --region $Region `
    --output-template-file packaged.yaml 2>&1 | Out-Host
if ($LASTEXITCODE -ne 0) { Write-Host "   [ERROR] Package fallito!" -ForegroundColor Red; exit 1 }
Write-Host "   [OK] Package completato" -ForegroundColor Green

# ====================
# STEP 7: Deploy via CloudFormation CLI
# ====================
Write-Host "[STEP 7/7] Deploy via CloudFormation..." -ForegroundColor Green
aws cloudformation deploy `
    --template-file packaged.yaml `
    --stack-name $StackName `
    --region $Region `
    --capabilities CAPABILITY_IAM CAPABILITY_AUTO_EXPAND CAPABILITY_NAMED_IAM `
    --parameter-overrides `
        "Environment=$Environment" `
        "UserProfilesTableName=$UserProfilesTableName" `
        "UserPoolId=$UserPoolId" `
        "UserPoolArn=$UserPoolArn" `
    --no-fail-on-empty-changeset 2>&1 | Out-Host

$deployResult = $LASTEXITCODE
if ($deployResult -ne 0) {
    Write-Host "   [WARN] Deploy fallito, provo con create-stack..." -ForegroundColor Yellow
    aws cloudformation create-stack `
        --template-body "file://packaged.yaml" `
        --stack-name $StackName `
        --region $Region `
        --capabilities CAPABILITY_IAM CAPABILITY_AUTO_EXPAND CAPABILITY_NAMED_IAM `
        --parameters `
            "ParameterKey=Environment,ParameterValue=$Environment" `
            "ParameterKey=UserProfilesTableName,ParameterValue=$UserProfilesTableName" `
            "ParameterKey=UserPoolId,ParameterValue=$UserPoolId" `
            "ParameterKey=UserPoolArn,ParameterValue=$UserPoolArn" `
        --disable-rollback 2>&1 | Out-Host
    if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] DEPLOY FALLITO!" -ForegroundColor Red; exit 1 }
    aws cloudformation wait stack-create-complete --stack-name $StackName --region $Region
}

# ====================
# STEP 8: Configurazione trigger Cognito
# ====================
Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "   [STEP 8/8] Configurazione trigger Cognito" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan

$LambdaArn = aws cloudformation describe-stacks `
    --stack-name $StackName `
    --query "Stacks[0].Outputs[?OutputKey=='LambdaArn'].OutputValue" `
    --output text --region $Region

if (-not $LambdaArn -or $LambdaArn -eq "None") {
    Write-Host "[ERROR] Impossibile ottenere ARN Lambda dallo stack!" -ForegroundColor Red
    exit 1
}
Write-Host "Lambda ARN: $LambdaArn" -ForegroundColor Gray

Write-Host ""
Write-Host "Configurazione trigger PostConfirmation su Cognito..." -ForegroundColor Cyan
python "$PSScriptRoot\apply-email-template.py" $UserPoolId $Region $LambdaArn 2>&1 | ForEach-Object { Write-Host "   $_" }

if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Impossibile configurare il trigger su Cognito!" -ForegroundColor Red
    exit 1
}
Write-Host "[OK] Trigger PostConfirmation configurato!" -ForegroundColor Green

$lambdaConfig = aws cognito-idp describe-user-pool --user-pool-id $UserPoolId --region $Region --query "UserPool.LambdaConfig.PostConfirmation" --output text 2>$null
if ($lambdaConfig -and $lambdaConfig -ne "None") {
    Write-Host "   [OK] Trigger verificato su Cognito" -ForegroundColor Green
} else {
    Write-Host "   [ERROR] Trigger PostConfirmation non trovato!" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "   DEPLOY DEV-BE COGNITO COMPLETATO!" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
Write-Host "Prossimi passi:" -ForegroundColor Cyan
Write-Host "1. Testa la registrazione con il pool $UserPoolId" -ForegroundColor Gray
Write-Host "2. Frontend Client ID dev-be: $ClientId" -ForegroundColor Yellow
Write-Host ""
