#!/usr/bin/env pwsh
# ============================================================
# Aura Battle - Create AWS Prereqs (Cognito User Pool + Client)
# ============================================================
# Crea le risorse base per l'ambiente aura-battle richiesto
# (dev-aurabattle o prod-aurabattle), taggate Project=aurabattle,
# e scrive/aggiorna il file di config corrispondente in infra/.
#
# Usage:
#   ./scripts/create-aurabattle-prereqs.ps1 -Environment dev-aurabattle
#   ./scripts/create-aurabattle-prereqs.ps1 -Environment prod-aurabattle
# ============================================================

param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("dev-aurabattle", "prod-aurabattle")]
    [string]$Environment
)

$ErrorActionPreference = "Continue"

$Region = "eu-south-1"
$IsProd = $Environment -eq "prod-aurabattle"
$ShortEnv = if ($IsProd) { "prod" } else { "dev" }

$ArtifactsBucket = "aurabattle-$ShortEnv-artifacts"
$UserPoolName    = "$Environment-user-pool"
$ClientName      = "$Environment-client"
$ConfigFile      = Join-Path $PSScriptRoot "..\infra\$Environment-config.ps1"
$VarPrefix       = if ($IsProd) { "ProdAuraBattle" } else { "DevAuraBattle" }

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "   AURA BATTLE - PREREQS ($Environment)" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "Region:  $Region" -ForegroundColor Yellow
Write-Host "Bucket:  $ArtifactsBucket" -ForegroundColor Yellow
Write-Host ""

# ====================
# STEP 1: S3 artifacts bucket
# ====================
Write-Host "[STEP 1/3] Verifica/creazione bucket artifacts..." -ForegroundColor Green
$bucketExists = aws s3api head-bucket --bucket $ArtifactsBucket --region $Region 2>$null
if ($LASTEXITCODE -ne 0) {
    aws s3api create-bucket `
        --bucket $ArtifactsBucket `
        --region $Region `
        --create-bucket-configuration LocationConstraint=$Region | Out-Null
    aws s3api put-bucket-tagging --bucket $ArtifactsBucket --tagging "TagSet=[{Key=Project,Value=aurabattle},{Key=Environment,Value=$Environment}]" | Out-Null
    Write-Host "   [OK] Bucket creato: $ArtifactsBucket" -ForegroundColor Gray
} else {
    Write-Host "   [OK] Bucket gia' esistente: $ArtifactsBucket" -ForegroundColor Gray
}

# ====================
# STEP 2: Cognito User Pool
# ====================
Write-Host "[STEP 2/3] Creazione User Pool..." -ForegroundColor Green
$PoliciesJson = '{\"PasswordPolicy\":{\"MinimumLength\":8,\"RequireUppercase\":true,\"RequireLowercase\":true,\"RequireNumbers\":true,\"RequireSymbols\":false}}'
$poolJson = aws cognito-idp create-user-pool `
    --pool-name $UserPoolName `
    --region $Region `
    --auto-verified-attributes email `
    --username-attributes email `
    --schema `
        'Name=email,Required=true,Mutable=true' `
        'Name=given_name,Required=true,Mutable=true' `
        'Name=family_name,Required=true,Mutable=true' `
    --policies $PoliciesJson `
    --user-pool-tags "Project=aurabattle,Environment=$Environment" `
    --output json

if ($LASTEXITCODE -ne 0) {
    Write-Host "   [ERROR] Creazione User Pool fallita!" -ForegroundColor Red
    exit 1
}
$poolJson = $poolJson | ConvertFrom-Json

$UserPoolId  = $poolJson.UserPool.Id
$UserPoolArn = $poolJson.UserPool.Arn
Write-Host "   [OK] User Pool creato: $UserPoolId" -ForegroundColor Gray

# ====================
# STEP 3: User Pool Client (no secret, per SPA/mobile)
# ====================
Write-Host "[STEP 3/3] Creazione User Pool Client..." -ForegroundColor Green
$clientJson = aws cognito-idp create-user-pool-client `
    --user-pool-id $UserPoolId `
    --client-name $ClientName `
    --region $Region `
    --no-generate-secret `
    --explicit-auth-flows ALLOW_USER_PASSWORD_AUTH ALLOW_ADMIN_USER_PASSWORD_AUTH ALLOW_USER_SRP_AUTH ALLOW_REFRESH_TOKEN_AUTH `
    --output json

if ($LASTEXITCODE -ne 0) {
    Write-Host "   [ERROR] Creazione User Pool Client fallita!" -ForegroundColor Red
    exit 1
}
$clientJson = $clientJson | ConvertFrom-Json

$ClientId = $clientJson.UserPoolClient.ClientId
Write-Host "   [OK] Client creato: $ClientId" -ForegroundColor Gray

# ====================
# Scrittura config file
# ====================
$configContent = @"
#!/usr/bin/env pwsh
# ============================================================
# $Environment Environment Configuration
# ============================================================
# GENERATO da: scripts/create-aurabattle-prereqs.ps1
# NON modificare manualmente - rieseguire lo script prereqs
# ============================================================

`$${VarPrefix}_Environment = "$Environment"
`$${VarPrefix}_Region      = "$Region"
`$${VarPrefix}_AccountId   = "$((aws sts get-caller-identity --query Account --output text))"

# ---- Cognito User Pool ----
`$${VarPrefix}_UserPoolId  = "$UserPoolId"
`$${VarPrefix}_UserPoolArn = "$UserPoolArn"
`$${VarPrefix}_ClientId    = "$ClientId"

# ---- S3 Buckets ----
`$${VarPrefix}_ArtifactsBucket = "$ArtifactsBucket"

# ---- DynamoDB Tables (prefisso $Environment-*) ----
`$${VarPrefix}_UserProfilesTable   = "$Environment-UserProfiles"
`$${VarPrefix}_BattlesTable        = "$Environment-Battles"
`$${VarPrefix}_ParticipationsTable = "$Environment-Participations"
"@

Set-Content -Path $ConfigFile -Value $configContent -Encoding utf8
Write-Host ""
Write-Host "[OK] Config scritta in: $ConfigFile" -ForegroundColor Green
Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "   PREREQS $Environment COMPLETATI!" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
