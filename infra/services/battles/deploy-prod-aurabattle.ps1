#!/usr/bin/env pwsh
# ============================================================
# Battles Service - Deploy PROD-AURABATTLE
# ⚠️  QUESTO SCRIPT MODIFICA L'AMBIENTE DI PRODUZIONE! ⚠️
# ============================================================

param([switch]$Yes)

$ErrorActionPreference = "Continue"

$ConfigFile = Join-Path $PSScriptRoot "..\..\prod-aurabattle-config.ps1"
if (-not (Test-Path $ConfigFile)) {
    Write-Host "[ERROR] Config non trovata: $ConfigFile" -ForegroundColor Red
    exit 1
}
. $ConfigFile

$Environment           = $ProdAuraBattle_Environment
$Region                = $ProdAuraBattle_Region
$StackName             = "prod-aurabattle-battles-service"
$S3Bucket              = $ProdAuraBattle_ArtifactsBucket
$UserPoolArn           = $ProdAuraBattle_UserPoolArn
$BattlesTableName      = $ProdAuraBattle_BattlesTable
$UserProfilesTableName = $ProdAuraBattle_UserProfilesTable
$BattleCoversBucketName = "$Environment-battle-covers"

if ($UserPoolArn -eq "PLACEHOLDER_RUN_PREREQS") {
    Write-Host "[ERROR] Cognito non configurato! Esegui: scripts\create-aurabattle-prereqs.ps1 -Environment prod-aurabattle" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Red
Write-Host "   DEPLOY BATTLES API - PROD-AURABATTLE" -ForegroundColor Red
Write-Host "============================================" -ForegroundColor Red
Write-Host "Stack:  $StackName" -ForegroundColor Yellow
Write-Host "Region: $Region" -ForegroundColor Yellow
Write-Host "============================================" -ForegroundColor Red
Write-Host ""

if (-not $Yes) {
    $confirm = Read-Host "Sei sicuro di voler procedere? (digita 'yes' per confermare)"
    if ($confirm -ne "yes") {
        Write-Host "[ABORT] Deploy annullato" -ForegroundColor Yellow
        exit 0
    }
}

$stackExists = $false
try {
    $stackStatus = aws cloudformation describe-stacks --stack-name $StackName --region $Region --query 'Stacks[0].StackStatus' --output text 2>$null
    if ($stackStatus -and $stackStatus -ne "None") {
        $stackExists = $true
        Write-Host "   Stack esistente in stato: $stackStatus" -ForegroundColor Yellow
        $problematicStates = @("REVIEW_IN_PROGRESS", "ROLLBACK_COMPLETE", "ROLLBACK_FAILED", "CREATE_FAILED", "DELETE_FAILED", "UPDATE_ROLLBACK_FAILED")
        if ($problematicStates -contains $stackStatus) {
            Write-Host "⚠️  NON SI CANCELLA MAI UNO STACK DI PRODUZIONE AUTOMATICAMENTE!" -ForegroundColor Red
            exit 1
        }
    }
} catch { Write-Host "   Nessuno stack esistente" -ForegroundColor Gray }

if (Test-Path .aws-sam) { Remove-Item -Recurse -Force .aws-sam }
if (Test-Path packaged.yaml) { Remove-Item -Force packaged.yaml }
if (-not $stackExists) { aws s3 rm "s3://$S3Bucket/battles-prod-aurabattle/" --recursive --region $Region 2>$null }

$validateResult = sam validate --template-file template.yaml --region $Region 2>&1
if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] Template non valido!" -ForegroundColor Red; Write-Host $validateResult -ForegroundColor Red; exit 1 }

sam build --template-file template.yaml 2>&1 | Out-Host
if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] Build fallito!" -ForegroundColor Red; exit 1 }

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
sam package --template-file .aws-sam/build/template.yaml `
    --s3-bucket $S3Bucket --s3-prefix "battles-prod-aurabattle/$timestamp" `
    --region $Region --output-template-file packaged.yaml 2>&1 | Out-Host
if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] Package fallito!" -ForegroundColor Red; exit 1 }

aws cloudformation deploy `
    --template-file packaged.yaml --stack-name $StackName --region $Region `
    --capabilities CAPABILITY_IAM CAPABILITY_AUTO_EXPAND CAPABILITY_NAMED_IAM `
    --tags "Project=aurabattle" "Environment=prod-aurabattle" `
    --parameter-overrides `
        "Environment=$Environment" `
        "UserPoolArn=$UserPoolArn" `
        "BattlesTableName=$BattlesTableName" `
        "UserProfilesTableName=$UserProfilesTableName" `
        "BattleCoversBucketName=$BattleCoversBucketName" `
    --no-fail-on-empty-changeset 2>&1 | Out-Host

if ($LASTEXITCODE -ne 0) {
    aws cloudformation create-stack --template-body "file://packaged.yaml" `
        --stack-name $StackName --region $Region `
        --capabilities CAPABILITY_IAM CAPABILITY_AUTO_EXPAND CAPABILITY_NAMED_IAM `
        --tags "Key=Project,Value=aurabattle" "Key=Environment,Value=prod-aurabattle" `
        --parameters `
            "ParameterKey=Environment,ParameterValue=$Environment" `
            "ParameterKey=UserPoolArn,ParameterValue=$UserPoolArn" `
            "ParameterKey=BattlesTableName,ParameterValue=$BattlesTableName" `
            "ParameterKey=UserProfilesTableName,ParameterValue=$UserProfilesTableName" `
            "ParameterKey=BattleCoversBucketName,ParameterValue=$BattleCoversBucketName" `
        --disable-rollback 2>&1 | Out-Host
    if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] DEPLOY FALLITO!" -ForegroundColor Red; exit 1 }
    aws cloudformation wait stack-create-complete --stack-name $StackName --region $Region
}

# ====================
# Collega l'evento S3 (uploads/*) alla lambda di resize
# ====================
Write-Host ""
Write-Host "Collegamento evento S3 -> lambda di resize copertine..." -ForegroundColor Cyan

$ProcessFunctionArn = aws cloudformation describe-stacks --stack-name $StackName --region $Region `
    --query "Stacks[0].Outputs[?OutputKey=='ProcessCoverUploadFunctionArn'].OutputValue" --output text
$ProcessFunctionName = aws cloudformation describe-stacks --stack-name $StackName --region $Region `
    --query "Stacks[0].Outputs[?OutputKey=='ProcessCoverUploadFunctionName'].OutputValue" --output text

if (-not $ProcessFunctionArn -or $ProcessFunctionArn -eq "None") {
    Write-Host "   [ERROR] Impossibile ottenere l'ARN della lambda di processing!" -ForegroundColor Red
    exit 1
}

$AccountId = aws sts get-caller-identity --query Account --output text

aws lambda add-permission `
    --function-name $ProcessFunctionName `
    --statement-id "s3-battle-covers-invoke" `
    --action "lambda:InvokeFunction" `
    --principal "s3.amazonaws.com" `
    --source-arn "arn:aws:s3:::$BattleCoversBucketName" `
    --source-account $AccountId `
    --region $Region 2>&1 | Out-Null

$NotificationConfig = @{
    LambdaFunctionConfigurations = @(
        @{
            LambdaFunctionArn = $ProcessFunctionArn
            Events = @("s3:ObjectCreated:*")
            Filter = @{
                Key = @{
                    FilterRules = @(
                        @{ Name = "prefix"; Value = "uploads/" }
                    )
                }
            }
        }
    )
} | ConvertTo-Json -Depth 10

$NotificationConfigFile = Join-Path $env:TEMP "battle-covers-notification-$Environment.json"
[System.IO.File]::WriteAllText($NotificationConfigFile, $NotificationConfig, (New-Object System.Text.UTF8Encoding $false))

aws s3api put-bucket-notification-configuration `
    --bucket $BattleCoversBucketName `
    --notification-configuration "file://$NotificationConfigFile" `
    --region $Region

if ($LASTEXITCODE -ne 0) {
    Write-Host "   [ERROR] Impossibile configurare la notifica S3!" -ForegroundColor Red
    exit 1
}
Write-Host "   [OK] Evento S3 collegato a $ProcessFunctionName" -ForegroundColor Green

Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "   [SUCCESS] DEPLOY BATTLES API PROD-AURABATTLE COMPLETATO!" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
