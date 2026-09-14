#!/usr/bin/env pwsh
# ============================================================
# Email Notifications Service - Deploy DEV-BE
# ============================================================
# Parametri opzionali per inviare la broadcast email post-deploy:
#   -AppVersion   "2.5.0"
#   -ReleaseNotes "<ul><li>Novità 1</li><li>Fix bug X</li></ul>"
# ============================================================
param(
    [string]$AppVersion   = "",
    [string]$ReleaseNotes = ""
)

# Fallback a env vars (quando chiamato da deploy-all.ps1)
if ($AppVersion   -eq "" -and $env:DEPLOY_APP_VERSION)   { $AppVersion   = $env:DEPLOY_APP_VERSION }
if ($ReleaseNotes -eq "" -and $env:DEPLOY_RELEASE_NOTES) { $ReleaseNotes = $env:DEPLOY_RELEASE_NOTES }

$ErrorActionPreference = "Continue"

$ConfigFile = Join-Path $PSScriptRoot "..\..\..\infra\dev-be-config.ps1"
if (-not (Test-Path $ConfigFile)) {
    Write-Host "[ERROR] Config non trovata. Esegui prima: scripts\create-dev-be-prereqs.ps1" -ForegroundColor Red
    exit 1
}
. $ConfigFile

$Environment           = $DevBe_Environment
$Region                = $DevBe_Region
$StackName             = "dev-be-email-notifications"
$S3Bucket              = $DevBe_ArtifactsBucket
$UserProfilesTableName = $DevBe_UserProfilesTable
$JobListingsTableName  = $DevBe_JobListingsTable
$BookingsTableName     = "dev-be-Bookings"
$CompaniesTableName    = $DevBe_CompaniesTable
$SesFromAddress        = "noreply@girolavoro.it"
$SesRegion             = $DevBe_Region

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "   DEPLOY EMAIL NOTIFICATIONS - DEV-BE" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "Stack:  $StackName" -ForegroundColor Yellow
Write-Host "Region: $Region" -ForegroundColor Yellow
Write-Host "Bucket: $S3Bucket" -ForegroundColor Yellow
Write-Host "SES From: $SesFromAddress" -ForegroundColor Yellow
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

$stackExists = $false
try {
    $stackStatus = aws cloudformation describe-stacks --stack-name $StackName --region $Region `
        --query 'Stacks[0].StackStatus' --output text 2>$null
    if ($stackStatus -and $stackStatus -ne "None") {
        $stackExists = $true
        Write-Host "   Stack esistente in stato: $stackStatus" -ForegroundColor Yellow
        $problematicStates = @("REVIEW_IN_PROGRESS","ROLLBACK_COMPLETE","ROLLBACK_FAILED","CREATE_FAILED","DELETE_FAILED","UPDATE_ROLLBACK_FAILED")
        if ($problematicStates -contains $stackStatus) {
            aws cloudformation delete-stack --stack-name $StackName --region $Region
            aws cloudformation wait stack-delete-complete --stack-name $StackName --region $Region 2>$null
            $stackExists = $false
        }
    }
} catch { Write-Host "   Nessuno stack esistente" -ForegroundColor Gray }

if (Test-Path .aws-sam) { Remove-Item -Recurse -Force .aws-sam }
if (Test-Path packaged.yaml) { Remove-Item -Force packaged.yaml }
if (-not $stackExists) { aws s3 rm "s3://$S3Bucket/email-notifications-dev-be/" --recursive --region $Region 2>$null }

# Sync shared modules into each Lambda folder before build
Write-Host "[INFO] Sincronizzazione shared/email_templates.py e shared/reminder_schedule.py..." -ForegroundColor Cyan
$SharedTemplates = Join-Path $PSScriptRoot "..\..\..\src\lambdas\services\email-notifications\shared\email_templates.py"
$SharedReminder  = Join-Path $PSScriptRoot "..\..\..\src\lambdas\services\email-notifications\shared\reminder_schedule.py"
$LambdaDirs = @("app-update-broadcast","weekly-upgrade-reminder","weekly-company-no-listing","weekly-worker-no-application")
foreach ($dir in $LambdaDirs) {
    $dest = Join-Path $PSScriptRoot "..\..\..\src\lambdas\services\email-notifications\$dir\email_templates.py"
    Copy-Item $SharedTemplates $dest -Force
    $destR = Join-Path $PSScriptRoot "..\..\..\src\lambdas\services\email-notifications\$dir\reminder_schedule.py"
    Copy-Item $SharedReminder $destR -Force
}
Write-Host "   [OK] email_templates.py + reminder_schedule.py sincronizzati in tutti i Lambda" -ForegroundColor Green

$validateResult = sam validate --template-file template.yaml --region $Region 2>&1
if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] Template non valido!" -ForegroundColor Red; exit 1 }

sam build --template-file template.yaml 2>&1 | Out-Host
if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] Build fallito!" -ForegroundColor Red; exit 1 }

Write-Host "[INFO] Pulizia template temporanei dai sorgenti (per evitare file tripli nell'editor)..." -ForegroundColor Cyan
foreach ($dir in $LambdaDirs) {
    $dest = Join-Path $PSScriptRoot "..\..\..\src\lambdas\services\email-notifications\$dir\email_templates.py"
    if (Test-Path $dest) { Remove-Item $dest -Force }
    $destR = Join-Path $PSScriptRoot "..\..\..\src\lambdas\services\email-notifications\$dir\reminder_schedule.py"
    if (Test-Path $destR) { Remove-Item $destR -Force }
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
sam package --template-file .aws-sam/build/template.yaml `
    --s3-bucket $S3Bucket --s3-prefix "email-notifications-dev-be/$timestamp" `
    --region $Region --output-template-file packaged.yaml 2>&1 | Out-Host
if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] Package fallito!" -ForegroundColor Red; exit 1 }

aws cloudformation deploy `
    --template-file packaged.yaml --stack-name $StackName --region $Region `
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
    aws cloudformation create-stack --template-body "file://packaged.yaml" `
        --stack-name $StackName --region $Region `
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
    if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] DEPLOY FALLITO!" -ForegroundColor Red; exit 1 }
    aws cloudformation wait stack-create-complete --stack-name $StackName --region $Region
}

try {
    $cleanupScript = Join-Path $PSScriptRoot "..\..\..\scripts\cleanup-s3-old-versions.ps1"
    & $cleanupScript -Prefix "email-notifications-dev-be" -KeepVersions 2 -Bucket $S3Bucket -Region $Region -NoConfirm
} catch { Write-Host "   [WARN] Pulizia vecchie versioni fallita (non bloccante)" -ForegroundColor Yellow }

Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "   [SUCCESS] DEPLOY EMAIL NOTIFICATIONS DEV-BE COMPLETATO!" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
aws cloudformation describe-stacks --stack-name $StackName --region $Region `
    --query 'Stacks[0].Outputs[*].[OutputKey,OutputValue]' --output table

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

    $safeVersion = $AppVersion   -replace '"','\"'
    $safeNotes   = $ReleaseNotes -replace '"','\"'
    $broadcastPayload = '{"version":"' + $safeVersion + '","notes_html":"' + $safeNotes + '"}'

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
    Write-Host "       .\deploy-dev-be.ps1 -AppVersion '2.5.0' -ReleaseNotes '<ul><li>Novità</li></ul>'" -ForegroundColor Gray
}
