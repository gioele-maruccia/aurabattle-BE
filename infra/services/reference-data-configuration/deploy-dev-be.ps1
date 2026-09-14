#!/usr/bin/env pwsh
# ============================================================
# Reference Data Configuration Service - Deploy DEV-BE
# ============================================================

$ErrorActionPreference = "Continue"

$ConfigFile = Join-Path $PSScriptRoot "..\..\..\infra\dev-be-config.ps1"
if (-not (Test-Path $ConfigFile)) {
    Write-Host "[ERROR] Config non trovata. Esegui prima: scripts\create-dev-be-prereqs.ps1" -ForegroundColor Red
    exit 1
}
. $ConfigFile

$Environment            = $DevBe_Environment
$Region                 = $DevBe_Region
$StackName              = "dev-be-reference-data-configuration"
$S3Bucket               = $DevBe_ArtifactsBucket
$JobRolesTableName      = $DevBe_JobRolesTable
$ContractsTableName     = $DevBe_ContractsTable
$JobCategoriesTableName = $DevBe_JobCategoriesTable
$EmploymentTypesTableName = $DevBe_EmploymentTypesTable

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "   DEPLOY REFERENCE DATA CONFIG - DEV-BE" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "Stack:  $StackName" -ForegroundColor Yellow
Write-Host "Region: $Region" -ForegroundColor Yellow
Write-Host "Bucket: $S3Bucket" -ForegroundColor Yellow
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

$stackExists = $false
try {
    $stackStatus = aws cloudformation describe-stacks --stack-name $StackName --region $Region --query 'Stacks[0].StackStatus' --output text 2>$null
    if ($stackStatus -and $stackStatus -ne "None") {
        $stackExists = $true
        $problematicStates = @("REVIEW_IN_PROGRESS", "ROLLBACK_COMPLETE", "ROLLBACK_FAILED", "CREATE_FAILED", "DELETE_FAILED", "UPDATE_ROLLBACK_FAILED")
        if ($problematicStates -contains $stackStatus) {
            aws cloudformation delete-stack --stack-name $StackName --region $Region
            aws cloudformation wait stack-delete-complete --stack-name $StackName --region $Region 2>$null
            $stackExists = $false
        }
    }
} catch { Write-Host "   Nessuno stack esistente" -ForegroundColor Gray }

if (Test-Path .aws-sam) { Remove-Item -Recurse -Force .aws-sam }
if (Test-Path packaged.yaml) { Remove-Item -Force packaged.yaml }
if (-not $stackExists) { aws s3 rm "s3://$S3Bucket/reference-data-dev-be/" --recursive --region $Region 2>$null }

$validateResult = sam validate --template-file template.yaml --region $Region 2>&1
if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] Template non valido!" -ForegroundColor Red; exit 1 }

sam build --template-file template.yaml 2>&1 | Out-Host
if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] Build fallito!" -ForegroundColor Red; exit 1 }

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
sam package --template-file .aws-sam/build/template.yaml `
    --s3-bucket $S3Bucket --s3-prefix "reference-data-dev-be/$timestamp" `
    --region $Region --output-template-file packaged.yaml 2>&1 | Out-Host
if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] Package fallito!" -ForegroundColor Red; exit 1 }

aws cloudformation deploy `
    --template-file packaged.yaml --stack-name $StackName --region $Region `
    --capabilities CAPABILITY_IAM CAPABILITY_AUTO_EXPAND CAPABILITY_NAMED_IAM `
    --parameter-overrides `
        "Environment=$Environment" `
        "JobRolesTableName=$JobRolesTableName" `
        "ContractsTableName=$ContractsTableName" `
        "JobCategoriesTableName=$JobCategoriesTableName" `
        "EmploymentTypesTableName=$EmploymentTypesTableName" `
    --no-fail-on-empty-changeset 2>&1 | Out-Host

if ($LASTEXITCODE -ne 0) {
    aws cloudformation create-stack --template-body "file://packaged.yaml" `
        --stack-name $StackName --region $Region `
        --capabilities CAPABILITY_IAM CAPABILITY_AUTO_EXPAND CAPABILITY_NAMED_IAM `
        --parameters `
            "ParameterKey=Environment,ParameterValue=$Environment" `
            "ParameterKey=JobRolesTableName,ParameterValue=$JobRolesTableName" `
            "ParameterKey=ContractsTableName,ParameterValue=$ContractsTableName" `
            "ParameterKey=JobCategoriesTableName,ParameterValue=$JobCategoriesTableName" `
            "ParameterKey=EmploymentTypesTableName,ParameterValue=$EmploymentTypesTableName" `
        --disable-rollback 2>&1 | Out-Host
    if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] DEPLOY FALLITO!" -ForegroundColor Red; exit 1 }
    aws cloudformation wait stack-create-complete --stack-name $StackName --region $Region
}

try {
    $cleanupScript = Join-Path $PSScriptRoot "..\..\..\scripts\cleanup-s3-old-versions.ps1"
    & $cleanupScript -Prefix "reference-data-dev-be" -KeepVersions 2 -Bucket $S3Bucket -Region $Region -NoConfirm
} catch { Write-Host "   [WARN] Pulizia fallita (non bloccante)" -ForegroundColor Yellow }

Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "   [SUCCESS] DEPLOY REFERENCE DATA DEV-BE COMPLETATO!" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
aws cloudformation describe-stacks --stack-name $StackName --region $Region `
    --query 'Stacks[0].Outputs[*].[OutputKey,OutputValue]' --output table
