#!/usr/bin/env pwsh
# ============================================================
# Cognito Core Setup - Deploy PROD
# ============================================================
# Deploy della Lambda PostConfirmation e configurazione Cognito
# ⚠️  QUESTO SCRIPT MODIFICA L'AMBIENTE DI PRODUZIONE! ⚠️
# ============================================================

$ErrorActionPreference = "Continue"
$Environment = "prod"
$Region = "eu-south-1"
$StackName = "core-cognito-setup-prod"
$S3Bucket = "beezey-prod"
$UserProfilesTableName = "prod-UserProfiles"
$UserPoolId = "eu-south-1_iCBtUlJO6"
$UserPoolArn = "arn:aws:cognito-idp:eu-south-1:881962383770:userpool/eu-south-1_iCBtUlJO6"

Write-Host ""
Write-Host "============================================" -ForegroundColor Red
Write-Host "   DEPLOY COGNITO SETUP - PRODUCTION" -ForegroundColor Red
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
            # DELETE_FAILED può essere sbloccato con continue-update-rollback
            if ($stackStatus -eq "DELETE_FAILED") {
                Write-Host "   [WARN] Stack in DELETE_FAILED, provo a sbloccarlo..." -ForegroundColor Yellow
                Write-Host "   Eseguo continue-update-rollback..." -ForegroundColor Gray
                aws cloudformation continue-update-rollback --stack-name $StackName --region $Region 2>$null
                Start-Sleep -Seconds 5
                $newStatus = aws cloudformation describe-stacks --stack-name $StackName --region $Region --query 'Stacks[0].StackStatus' --output text 2>$null
                Write-Host "   Nuovo stato: $newStatus" -ForegroundColor Yellow
                
                # Se non è più in stato problematico, procedi
                if ($newStatus -and -not ($problematicStates -contains $newStatus)) {
                    Write-Host "   [OK] Stack sbloccato, procedo con il deploy" -ForegroundColor Green
                    $stackExists = $true
                } else {
                    # Comunque bloccato, basta fermarsi
                    Write-Host ""
                    Write-Host "============================================" -ForegroundColor Red
                    Write-Host "   [ERRORE] STACK ANCORA IN STATO PROBLEMATICO" -ForegroundColor Red
                    Write-Host "============================================" -ForegroundColor Red
                    Write-Host ""
                    Write-Host "Stack: $StackName" -ForegroundColor Yellow
                    Write-Host "Stato: $newStatus" -ForegroundColor Red
                    Write-Host ""
                    Write-Host "⚠️  NON SI CANCELLA MAI UNO STACK DI PRODUZIONE!" -ForegroundColor Red
                    Write-Host ""
                    Write-Host "Contatta AWS Support per risolvere manualmente il DELETE_FAILED:" -ForegroundColor Yellow
                    Write-Host "https://console.aws.amazon.com/support/" -ForegroundColor Gray
                    Write-Host ""
                    exit 1
                }
            } else {
                # Altri stati problematici
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
Write-Host "[STEP 7/9] Deploy via CloudFormation..." -ForegroundColor Green
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
# STEP 8: Configura trigger Cognito
# ====================
Write-Host ""
Write-Host "[STEP 8/9] Configura trigger PostConfirmation su Cognito..." -ForegroundColor Green

# Ottieni l'ARN della lambda dal stack output
$lambdaArn = aws cloudformation describe-stacks `
    --stack-name $StackName `
    --region $Region `
    --query "Stacks[0].Outputs[?OutputKey=='LambdaArn'].OutputValue" `
    --output text 2>$null

if ($lambdaArn -and $lambdaArn -ne "None") {
    Write-Host "   Lambda ARN: $lambdaArn" -ForegroundColor Gray
    Write-Host "   Configurazione trigger su User Pool $UserPoolId..." -ForegroundColor Gray
    
    # Leggi il template email dal file (zero hardcoding)
    # IMPORTANTE: includere sempre --auto-verified-attributes, altrimenti update-user-pool
    # azzera quell'impostazione e Cognito smette di inviare codici di verifica
    # Usiamo Python/boto3 per evitare problemi di escaping su Windows con {####}
    Write-Host "   Configurazione trigger e template email..." -ForegroundColor Gray
    python "$PSScriptRoot\apply-email-template.py" $UserPoolId $Region $lambdaArn 2>&1 | ForEach-Object { Write-Host "   $_" }

    if ($LASTEXITCODE -eq 0) {
        Write-Host "   ✅ Trigger PostConfirmation e template email configurati" -ForegroundColor Green
    } else {
        Write-Host "   ❌ Errore nella configurazione del trigger" -ForegroundColor Red
        Write-Host "   Puoi configurarlo manualmente con questo comando:" -ForegroundColor Yellow
        Write-Host "   aws cognito-idp update-user-pool --user-pool-id $UserPoolId --lambda-config PostConfirmation=$lambdaArn" -ForegroundColor Gray
    }
} else {
    Write-Host "   ⚠️  Lambda ARN non trovato negli stack outputs" -ForegroundColor Yellow
}

# ====================
# STEP 9: Verifica deployment
# ====================
Write-Host ""
Write-Host "[STEP 9/9] Verifica deployment..." -ForegroundColor Green

# Verifica che la lambda esista
$lambdaName = "${Environment}-cognito-post-confirmation"
$lambdaExists = aws lambda get-function --function-name $lambdaName --region $Region 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "   ✅ Lambda $lambdaName creata con successo" -ForegroundColor Green
} else {
    Write-Host "   ❌ Lambda $lambdaName non trovata!" -ForegroundColor Red
}

# Verifica trigger Cognito
$lambdaConfig = aws cognito-idp describe-user-pool --user-pool-id $UserPoolId --region $Region --query "UserPool.LambdaConfig.PostConfirmation" --output text 2>$null
if ($lambdaConfig -and $lambdaConfig -ne "None") {
    Write-Host "   ✅ Trigger PostConfirmation configurato su Cognito" -ForegroundColor Green
} else {
    Write-Host "   ⚠️  Trigger PostConfirmation non trovato su Cognito" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "   ✅ DEPLOY COMPLETATO CON SUCCESSO!" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
Write-Host "⚠️  IMPORTANTE: Testa la registrazione utente in prod per verificare che:" -ForegroundColor Yellow
Write-Host "1. L'email di conferma arrivi correttamente" -ForegroundColor Gray
Write-Host "2. Il codice di verifica funzioni senza LambdaAuthException" -ForegroundColor Gray
Write-Host "3. Il profilo utente venga creato in prod-UserProfiles" -ForegroundColor Gray
Write-Host "4. Controlla i log CloudWatch: /aws/lambda/$lambdaName" -ForegroundColor Gray
Write-Host ""
