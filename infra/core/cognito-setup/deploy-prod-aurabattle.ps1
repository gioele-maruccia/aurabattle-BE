#!/usr/bin/env pwsh
# ============================================================
# Cognito Core Setup - Deploy PROD-AURABATTLE
# ============================================================
# Deploy della Lambda PostConfirmation e configurazione Cognito
# ⚠️  QUESTO SCRIPT MODIFICA L'AMBIENTE DI PRODUZIONE! ⚠️
# ============================================================

$ErrorActionPreference = "Continue"

# Carica configurazione prod-aurabattle
$ConfigFile = Join-Path $PSScriptRoot "..\..\prod-aurabattle-config.ps1"
if (-not (Test-Path $ConfigFile)) {
    Write-Host "[ERROR] Config non trovata: $ConfigFile" -ForegroundColor Red
    exit 1
}
. $ConfigFile

$Environment           = $ProdAuraBattle_Environment
$Region                = $ProdAuraBattle_Region
$StackName             = "prod-aurabattle-core-cognito-setup"
$S3Bucket              = $ProdAuraBattle_ArtifactsBucket
$UserProfilesTableName = $ProdAuraBattle_UserProfilesTable
$UserPoolId            = $ProdAuraBattle_UserPoolId
$UserPoolArn           = $ProdAuraBattle_UserPoolArn
$ClientId              = $ProdAuraBattle_ClientId

if ($UserPoolId -eq "PLACEHOLDER_RUN_PREREQS") {
    Write-Host "[ERROR] Cognito User Pool non configurato!" -ForegroundColor Red
    Write-Host "        Esegui prima: scripts\create-aurabattle-prereqs.ps1 -Environment prod-aurabattle" -ForegroundColor Yellow
    exit 1
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Red
Write-Host "   DEPLOY COGNITO SETUP - PROD-AURABATTLE" -ForegroundColor Red
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
Write-Host "Questo modificherà il trigger PostConfirmation su Cognito LIVE!" -ForegroundColor Yellow
Write-Host ""
$confirm = Read-Host "Sei sicuro di voler procedere? (digita 'yes' per confermare)"
if ($confirm -ne "yes") {
    Write-Host ""
    Write-Host "[ABORT] Deploy annullato" -ForegroundColor Yellow
    exit 0
}
Write-Host ""
Write-Host "[OK] Confermato, procedo con il deploy PROD-AURABATTLE..." -ForegroundColor Green
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
            Write-Host ""
            Write-Host "⚠️  NON SI CANCELLA MAI UNO STACK DI PRODUZIONE AUTOMATICAMENTE!" -ForegroundColor Red
            Write-Host "Risolvi manualmente via AWS CloudFormation Console prima di rilanciare." -ForegroundColor Yellow
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
if (Test-Path .aws-sam) { Remove-Item -Recurse -Force .aws-sam; Write-Host "   [OK] Rimossa .aws-sam" -ForegroundColor Gray }
if (Test-Path packaged.yaml) { Remove-Item -Force packaged.yaml; Write-Host "   [OK] Rimosso packaged.yaml" -ForegroundColor Gray }

# ====================
# STEP 3: Pulizia artifacts S3 (solo per nuovi deploy)
# ====================
if (-not $stackExists) {
    Write-Host "[STEP 3/7] Pulizia artifacts S3..." -ForegroundColor Green
    aws s3 rm "s3://$S3Bucket/cognito-setup-prod-aurabattle/" --recursive --region $Region 2>$null
    Write-Host "   [OK] Pulita cartella cognito-setup-prod-aurabattle/ su S3" -ForegroundColor Gray
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
    --s3-prefix "cognito-setup-prod-aurabattle/$timestamp" `
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
    --tags "Project=aurabattle" "Environment=prod-aurabattle" `
    --parameter-overrides `
        "Environment=$Environment" `
        "UserProfilesTableName=$UserProfilesTableName" `
        "UserPoolId=$UserPoolId" `
        "UserPoolArn=$UserPoolArn" `
    --no-fail-on-empty-changeset 2>&1 | Out-Host

$deployResult = $LASTEXITCODE
if ($deployResult -ne 0) {
    Write-Host "   [WARN] Deploy CloudFormation fallito, provo con create-stack..." -ForegroundColor Yellow
    aws cloudformation create-stack `
        --template-body "file://packaged.yaml" `
        --stack-name $StackName `
        --region $Region `
        --capabilities CAPABILITY_IAM CAPABILITY_AUTO_EXPAND CAPABILITY_NAMED_IAM `
        --tags "Key=Project,Value=aurabattle" "Key=Environment,Value=prod-aurabattle" `
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
Write-Host "[STEP 8/8] Configurazione trigger PostConfirmation su Cognito..." -ForegroundColor Green

$LambdaArn = aws cloudformation describe-stacks `
    --stack-name $StackName `
    --region $Region `
    --query "Stacks[0].Outputs[?OutputKey=='LambdaArn'].OutputValue" `
    --output text 2>$null

if (-not $LambdaArn -or $LambdaArn -eq "None") {
    Write-Host "[ERROR] Impossibile ottenere ARN Lambda dallo stack!" -ForegroundColor Red
    exit 1
}
Write-Host "   Lambda ARN: $LambdaArn" -ForegroundColor Gray

python "$PSScriptRoot\apply-email-template.py" $UserPoolId $Region $LambdaArn 2>&1 | ForEach-Object { Write-Host "   $_" }
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Impossibile configurare il trigger su Cognito!" -ForegroundColor Red
    exit 1
}
Write-Host "[OK] Trigger PostConfirmation configurato!" -ForegroundColor Green

Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "   DEPLOY PROD-AURABATTLE COGNITO COMPLETATO!" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
Write-Host "⚠️  Testa la registrazione utente in prod per verificare email, trigger e profilo." -ForegroundColor Yellow
Write-Host "Frontend Client ID prod-aurabattle: $ClientId" -ForegroundColor Yellow
Write-Host ""
