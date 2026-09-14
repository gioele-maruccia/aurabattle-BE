#!/usr/bin/env pwsh
# ============================================================
# Cognito Core Setup - Deploy DEV
# ============================================================
# Deploy della Lambda PostConfirmation e configurazione Cognito
# ============================================================

$ErrorActionPreference = "Continue"
$Environment = "dev"
$Region = "eu-south-1"
$StackName = "dev-core-cognito-setup"
$S3Bucket = "beezey-dev"
$UserProfilesTableName = "dev-UserProfiles"
$UserPoolId = "eu-south-1_0oK9agPYd"
$UserPoolArn = "arn:aws:cognito-idp:eu-south-1:881962383770:userpool/eu-south-1_0oK9agPYd"
$ClientId = "4mc318b69uktpmfc008g47dsgj"

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "   DEPLOY COGNITO SETUP - DEV" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "Stack:  $StackName" -ForegroundColor Yellow
Write-Host "Region: $Region" -ForegroundColor Yellow
Write-Host "Bucket: $S3Bucket" -ForegroundColor Yellow
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
    aws s3 rm "s3://$S3Bucket/cognito-setup/" --recursive --region $Region 2>$null
    Write-Host "   [OK] Pulita cartella cognito-setup/ su S3" -ForegroundColor Gray
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
    --s3-prefix "cognito-setup/$timestamp" `
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
        "UserProfilesTableName=$UserProfilesTableName" `
        "UserPoolId=$UserPoolId" `
        "UserPoolArn=$UserPoolArn" `
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
            "ParameterKey=UserProfilesTableName,ParameterValue=$UserProfilesTableName" `
            "ParameterKey=UserPoolId,ParameterValue=$UserPoolId" `
            "ParameterKey=UserPoolArn,ParameterValue=$UserPoolArn" `
            "ParameterKey=ImportExistingResources,ParameterValue=true" `
            "ParameterKey=StageName,ParameterValue=$Environment" `
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
        Write-Host "3. Controlla che la tabella UserProfiles esista" -ForegroundColor Gray
        exit 1
    }
    
    Write-Host ""
    Write-Host "[OK] Stack creato, attendo completamento..." -ForegroundColor Green
    aws cloudformation wait stack-create-complete --stack-name $StackName --region $Region
}

# ====================
# STEP 8: Configurazione trigger Cognito
# ====================
Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "   [STEP 8/8] Configurazione trigger Cognito" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# Ottieni l'ARN della lambda dallo stack
$LambdaArn = aws cloudformation describe-stacks `
    --stack-name $StackName `
    --query "Stacks[0].Outputs[?OutputKey=='LambdaArn'].OutputValue" `
    --output text `
    --region $Region

if (-not $LambdaArn -or $LambdaArn -eq "None") {
    Write-Host "[ERROR] Impossibile ottenere l'ARN della Lambda dallo stack!" -ForegroundColor Red
    exit 1
}

Write-Host "Lambda ARN: $LambdaArn" -ForegroundColor Gray

# Leggi il template email dal file (zero hardcoding)
# IMPORTANTE: includere sempre --auto-verified-attributes, altrimenti update-user-pool
# azzera quell'impostazione e Cognito smette di inviare codici di verifica
# Usiamo Python/boto3 per evitare problemi di escaping su Windows con {####}
Write-Host ""
Write-Host "Configurazione trigger PostConfirmation su Cognito..." -ForegroundColor Cyan
python "$PSScriptRoot\apply-email-template.py" $UserPoolId $Region $LambdaArn 2>&1 | ForEach-Object { Write-Host "   $_" }

if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Impossibile configurare il trigger su Cognito!" -ForegroundColor Red
    exit 1
}

Write-Host "[OK] Trigger PostConfirmation configurato con successo!" -ForegroundColor Green

# Verifica configurazione finale
Write-Host ""
Write-Host "Verifica finale..." -ForegroundColor Cyan
$lambdaConfig = aws cognito-idp describe-user-pool --user-pool-id $UserPoolId --region $Region --query "UserPool.LambdaConfig.PostConfirmation" --output text 2>$null
if ($lambdaConfig -and $lambdaConfig -ne "None") {
    Write-Host "   ✅ Trigger PostConfirmation verificato su Cognito" -ForegroundColor Green
} else {
    Write-Host "   ❌ Trigger PostConfirmation non trovato!" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "   ✅ DEPLOY COMPLETATO CON SUCCESSO!" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
Write-Host "Prossimi passi:" -ForegroundColor Cyan
Write-Host "1. Testa la registrazione utente per verificare il trigger PostConfirmation" -ForegroundColor Gray
Write-Host "2. Controlla i log CloudWatch: /aws/lambda/${Environment}-cognito-post-confirmation" -ForegroundColor Gray
Write-Host "3. IMPORTANTE: Aggiorna il frontend con il Client ID: $ClientId" -ForegroundColor Yellow
Write-Host ""
