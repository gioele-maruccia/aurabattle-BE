#!/usr/bin/env pwsh
# ============================================================
# Email Notifications Service - Deploy PROD
# ============================================================
# Parametri opzionali per inviare la broadcast email post-deploy:
#   -AppVersion   "2.5.0"
#   -ReleaseNotes "<ul><li>Novità 1</li><li>Fix bug X</li></ul>"
# ============================================================
param(
    [string]$AppVersion   = "",
    [string]$ReleaseNotes = "",
    [switch]$Force
)

# Fallback a env vars (quando chiamato da deploy-all.ps1)
if ($AppVersion   -eq "" -and $env:DEPLOY_APP_VERSION)   { $AppVersion   = $env:DEPLOY_APP_VERSION }
if ($ReleaseNotes -eq "" -and $env:DEPLOY_RELEASE_NOTES) { $ReleaseNotes = $env:DEPLOY_RELEASE_NOTES }

$ErrorActionPreference = "Continue"
$Environment           = "prod"
$Region                = "eu-south-1"
$StackName             = "prod-email-notifications"
$S3Bucket              = "beezey-prod"
$UserProfilesTableName = "prod-UserProfiles"
$JobListingsTableName  = "prod-JobListings"
$BookingsTableName     = "prod-Bookings"
$CompaniesTableName    = "prod-Companies"
$SesFromAddress        = "noreply@girolavoro.it"
$SesRegion             = $Region

Write-Host ""
Write-Host "============================================" -ForegroundColor Red
Write-Host "   DEPLOY EMAIL NOTIFICATIONS - PRODUCTION" -ForegroundColor Red
Write-Host "============================================" -ForegroundColor Red
Write-Host "Stack:    $StackName" -ForegroundColor Yellow
Write-Host "Region:   $Region" -ForegroundColor Yellow
Write-Host "Bucket:   $S3Bucket" -ForegroundColor Yellow
Write-Host "SES From: $SesFromAddress" -ForegroundColor Yellow
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
# STEP 1: Verifica stack problematici (NON cancellare mai in prod)
# ====================
Write-Host "[STEP 1/8] Verifica stato stack esistente..." -ForegroundColor Green
$stackExists = $false
try {
    $stackStatus = aws cloudformation describe-stacks --stack-name $StackName --region $Region `
        --query 'Stacks[0].StackStatus' --output text 2>$null
    if ($stackStatus -and $stackStatus -ne "None") {
        $stackExists = $true
        Write-Host "   Stack esistente in stato: $stackStatus" -ForegroundColor Yellow
        $problematicStates = @("REVIEW_IN_PROGRESS","ROLLBACK_COMPLETE","ROLLBACK_FAILED","CREATE_FAILED","DELETE_FAILED","UPDATE_ROLLBACK_FAILED")
        if ($problematicStates -contains $stackStatus) {
            Write-Host ""
            Write-Host "============================================" -ForegroundColor Red
            Write-Host "   [ERRORE] STACK IN STATO PROBLEMATICO" -ForegroundColor Red
            Write-Host "============================================" -ForegroundColor Red
            Write-Host ""
            Write-Host "Stack: $StackName" -ForegroundColor Yellow
            Write-Host "Stato: $stackStatus" -ForegroundColor Red
            Write-Host ""
            Write-Host "NON SI CANCELLA MAI UNO STACK DI PRODUZIONE!" -ForegroundColor Red
            Write-Host ""
            Write-Host "Risolvi manualmente via AWS CloudFormation Console:" -ForegroundColor Yellow
            Write-Host "1. Vai a: https://console.aws.amazon.com/cloudformation" -ForegroundColor Gray
            Write-Host "2. Seleziona lo stack: $StackName" -ForegroundColor Gray
            Write-Host "3. Clicca 'Stack Actions' -> 'Continue Update Rollback'" -ForegroundColor Gray
            Write-Host "4. Riprova il deploy quando lo stack è in UPDATE_COMPLETE o CREATE_COMPLETE" -ForegroundColor Gray
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
Write-Host "[STEP 2/8] Pulizia cache locale..." -ForegroundColor Green
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
    Write-Host "[STEP 3/8] Pulizia artifacts S3..." -ForegroundColor Green
    aws s3 rm "s3://$S3Bucket/email-notifications/" --recursive --region $Region 2>$null
    Write-Host "   [OK] Pulita cartella email-notifications/ su S3" -ForegroundColor Gray
} else {
    Write-Host "[STEP 3/8] Skip pulizia S3 (stack esistente, è un update)" -ForegroundColor Gray
}

# ====================
# STEP 4: Sync shared modules
# ====================
Write-Host "[STEP 4/8] Sincronizzazione shared/email_templates.py e shared/reminder_schedule.py..." -ForegroundColor Green
$SharedTemplates = Join-Path $PSScriptRoot "..\..\..\src\lambdas\services\email-notifications\shared\email_templates.py"
$SharedReminder  = Join-Path $PSScriptRoot "..\..\..\src\lambdas\services\email-notifications\shared\reminder_schedule.py"
$LambdaDirs = @("app-update-broadcast","weekly-upgrade-reminder","weekly-company-no-listing","weekly-worker-no-application")
foreach ($dir in $LambdaDirs) {
    $dest  = Join-Path $PSScriptRoot "..\..\..\src\lambdas\services\email-notifications\$dir\email_templates.py"
    $destR = Join-Path $PSScriptRoot "..\..\..\src\lambdas\services\email-notifications\$dir\reminder_schedule.py"
    Copy-Item $SharedTemplates $dest  -Force
    Copy-Item $SharedReminder  $destR -Force
}
Write-Host "   [OK] email_templates.py + reminder_schedule.py sincronizzati in tutti i Lambda" -ForegroundColor Green

# ====================
# STEP 5: Validate + Build
# ====================
Write-Host "[STEP 5/8] Validazione template..." -ForegroundColor Green
$validateResult = sam validate --template-file template.yaml --region $Region 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "   [ERROR] Template non valido!" -ForegroundColor Red
    Write-Host $validateResult -ForegroundColor Red
    exit 1
}
Write-Host "   [OK] Template valido" -ForegroundColor Gray

Write-Host "[STEP 5/8] Build SAM..." -ForegroundColor Green
sam build --template-file template.yaml 2>&1 | Out-Host
if ($LASTEXITCODE -ne 0) {
    Write-Host "   [ERROR] Build fallito!" -ForegroundColor Red
    exit 1
}
Write-Host "   [OK] Build completato" -ForegroundColor Green

# Pulizia file temporanei dai sorgenti
foreach ($dir in $LambdaDirs) {
    $dest  = Join-Path $PSScriptRoot "..\..\..\src\lambdas\services\email-notifications\$dir\email_templates.py"
    $destR = Join-Path $PSScriptRoot "..\..\..\src\lambdas\services\email-notifications\$dir\reminder_schedule.py"
    if (Test-Path $dest)  { Remove-Item $dest  -Force }
    if (Test-Path $destR) { Remove-Item $destR -Force }
}

# ====================
# STEP 6: Package
# ====================
Write-Host "[STEP 6/8] Package artifacts su S3..." -ForegroundColor Green
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
sam package `
    --template-file .aws-sam/build/template.yaml `
    --s3-bucket $S3Bucket `
    --s3-prefix "email-notifications/$timestamp" `
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
Write-Host "[STEP 7/8] Deploy via CloudFormation..." -ForegroundColor Green

aws cloudformation deploy `
    --template-file packaged.yaml `
    --stack-name $StackName `
    --region $Region `
    --capabilities CAPABILITY_IAM CAPABILITY_AUTO_EXPAND CAPABILITY_NAMED_IAM `
    --parameter-overrides `
        "Environment=$Environment" `
        "UserProfilesTableName=$UserProfilesTableName" `
        "JobListingsTableName=$JobListingsTableName" `
        "BookingsTableName=$BookingsTableName" `
        "CompaniesTableName=$CompaniesTableName" `
        "SesFromAddress=$SesFromAddress" `
        "SesRegion=$SesRegion" `
    --no-fail-on-empty-changeset 2>&1 | Out-Host

if ($LASTEXITCODE -ne 0) {
    Write-Host "   [WARN] Deploy CloudFormation fallito, provo con create-stack..." -ForegroundColor Yellow

    aws cloudformation create-stack `
        --template-body "file://packaged.yaml" `
        --stack-name $StackName `
        --region $Region `
        --capabilities CAPABILITY_IAM CAPABILITY_AUTO_EXPAND CAPABILITY_NAMED_IAM `
        --parameters `
            "ParameterKey=Environment,ParameterValue=$Environment" `
            "ParameterKey=UserProfilesTableName,ParameterValue=$UserProfilesTableName" `
            "ParameterKey=JobListingsTableName,ParameterValue=$JobListingsTableName" `
            "ParameterKey=BookingsTableName,ParameterValue=$BookingsTableName" `
            "ParameterKey=CompaniesTableName,ParameterValue=$CompaniesTableName" `
            "ParameterKey=SesFromAddress,ParameterValue=$SesFromAddress" `
            "ParameterKey=SesRegion,ParameterValue=$SesRegion" `
        --disable-rollback 2>&1 | Out-Host

    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "============================================" -ForegroundColor Red
        Write-Host "   [ERROR] DEPLOY FALLITO!" -ForegroundColor Red
        Write-Host "============================================" -ForegroundColor Red
        Write-Host ""
        Write-Host "Controlla la console CloudFormation per i dettagli:" -ForegroundColor Yellow
        Write-Host "https://console.aws.amazon.com/cloudformation/home?region=$Region" -ForegroundColor Gray
        exit 1
    }

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
    & $cleanupScript -Prefix "email-notifications" -KeepVersions 2 -Bucket $S3Bucket -Region $Region -NoConfirm
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
Write-Host "[WARNING] Monitora CloudWatch Logs dopo il deploy!" -ForegroundColor Yellow
Write-Host ""

Write-Host "[INFO] Stack Outputs:" -ForegroundColor Cyan
aws cloudformation describe-stacks `
    --stack-name $StackName `
    --region $Region `
    --query 'Stacks[0].Outputs[*].[OutputKey,OutputValue]' `
    --output table

Write-Host ""
Write-Host "[INFO] Lambda Functions:" -ForegroundColor Cyan
aws lambda list-functions `
    --region $Region `
    --query "Functions[?starts_with(FunctionName, '$Environment-email')].{Name:FunctionName, Runtime:Runtime, Updated:LastModified}" `
    --output table

# ====================
# BROADCAST EMAIL (opzionale)
# ====================
if ($AppVersion -ne "" -and $ReleaseNotes -ne "") {
    Write-Host ""
    Write-Host "============================================" -ForegroundColor Cyan
    Write-Host "   [BROADCAST] Invio email aggiornamento app" -ForegroundColor Cyan
    Write-Host "============================================" -ForegroundColor Cyan
    Write-Host "Versione:  $AppVersion" -ForegroundColor Yellow
    Write-Host "Note:      $ReleaseNotes" -ForegroundColor Yellow
    Write-Host ""

    # Costruisce il JSON senza escape HTML (ConvertTo-Json escaperebbe < > &)
    $safeVersion = $AppVersion   -replace '"','\"'
    $safeNotes   = $ReleaseNotes -replace '"','\"'
    $broadcastPayload = '{"version":"' + $safeVersion + '","notes_html":"' + $safeNotes + '"}'

    # Scrive il payload su file locale: evita tutti i problemi di escaping quote
    # su PowerShell 5.1 con AWS CLI (le " vengono strippate dal C runtime)
    $payloadPath = Join-Path $PWD.Path 'broadcast-payload.json'
    [System.IO.File]::WriteAllText($payloadPath, $broadcastPayload, [System.Text.Encoding]::UTF8)

    $broadcastResult = aws lambda invoke `
        --function-name "$Environment-email-app-update-broadcast" `
        --invocation-type RequestResponse `
        --payload fileb://broadcast-payload.json `
        --region $Region `
        broadcast-response.json 2>&1

    Remove-Item $payloadPath -Force -ErrorAction SilentlyContinue

    if ($LASTEXITCODE -eq 0) {
        $response = Get-Content broadcast-response.json -Raw | ConvertFrom-Json
        Write-Host "   [OK] Broadcast completato: $($response.body)" -ForegroundColor Green
    } else {
        Write-Host "   [WARN] Broadcast fallito (non bloccante): $broadcastResult" -ForegroundColor Yellow
        Write-Host "   Puoi ritentare manualmente dalla AWS Console Lambda:" -ForegroundColor Yellow
        Write-Host "   Funzione: $Environment-email-app-update-broadcast" -ForegroundColor Gray
        Write-Host "   Payload:  $broadcastPayload" -ForegroundColor Gray
    }
    if (Test-Path broadcast-response.json) { Remove-Item broadcast-response.json -Force }
} else {
    Write-Host ""
    Write-Host "[INFO] Nessun broadcast email inviato." -ForegroundColor Gray
    Write-Host "       Per inviarlo al prossimo deploy usa:" -ForegroundColor Gray
    Write-Host "       .\deploy-prod.ps1 -AppVersion '2.5.0' -ReleaseNotes '<ul><li>Novità</li></ul>'" -ForegroundColor Gray
}
