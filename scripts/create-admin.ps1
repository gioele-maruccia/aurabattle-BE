#Requires -Version 5.1
<#
.SYNOPSIS
Create or update a Cognito admin user and add them to the admins group.

.DESCRIPTION
Creates a user in the specified Cognito User Pool if it does not exist,
confirms the user, sets a permanent password, and adds them to a group
(default: admins). No secrets are stored in this script.

.PARAMETER Email
User email address (also used as username).

.PARAMETER Password
Permanent password to set for the user.

.PARAMETER CognitoUserPoolId
Cognito User Pool ID. If not provided, reads from COGNITO_USER_POOL_ID.

.PARAMETER Region
AWS region. Default: eu-south-1.

.PARAMETER GroupName
Cognito group name to add the user to. Default: admins.

.PARAMETER FirstName
Given name to set on the user. Default: Admin.

.PARAMETER LastName
Family name to set on the user. Default: User.

.PARAMETER ProfileType
Custom profile type to set (custom:profile_type). Default: admin.

.PARAMETER NoConfirm
Skip confirmation prompt.

.EXAMPLE
.\create-admin.ps1 -Email "admin@example.com" -Password "StrongPass@1" -CognitoUserPoolId "eu-south-1_XXXX" -Region "eu-south-1" -FirstName "Admin" -LastName "User" -ProfileType "admin"
#>

param(
    [Parameter(Mandatory = $true)]
    [string]$Email,

    [Parameter(Mandatory = $true)]
    [string]$Password,

    [Parameter(Mandatory = $false)]
    [string]$CognitoUserPoolId,

    [Parameter(Mandatory = $false)]
    [string]$Region = "eu-south-1",

    [Parameter(Mandatory = $false)]
    [string]$GroupName = "admins",

    [Parameter(Mandatory = $false)]
    [string]$FirstName = "Admin",

    [Parameter(Mandatory = $false)]
    [string]$LastName = "User",

    [Parameter(Mandatory = $false)]
    [string]$ProfileType = "admin",

    [Parameter(Mandatory = $false)]
    [switch]$NoConfirm
)

function Write-Success { Write-Host $args -ForegroundColor Green }
function Write-Error { Write-Host "ERROR: $args" -ForegroundColor Red }
function Write-Info { Write-Host "INFO: $args" -ForegroundColor Cyan }
function Write-Warning { Write-Host "WARNING: $args" -ForegroundColor Yellow }

if (-not $CognitoUserPoolId) {
    $CognitoUserPoolId = $env:COGNITO_USER_POOL_ID
}

if (-not $CognitoUserPoolId) {
    Write-Error "Cognito User Pool ID not provided. Set COGNITO_USER_POOL_ID or pass -CognitoUserPoolId."
    exit 1
}

Write-Info "Target pool: $CognitoUserPoolId (Region: $Region)"
Write-Info "User: $Email"
Write-Info "Group: $GroupName"
Write-Info "Name: $FirstName $LastName"
Write-Info "Profile type: $ProfileType"
Write-Warning "This will modify Cognito in the selected environment."

if (-not $NoConfirm) {
    $confirm = Read-Host "Type 'yes' to continue"
    if ($confirm -ne "yes") {
        Write-Warning "Aborted by user."
        exit 0
    }
}

$existingUser = $null
$userSearch = aws cognito-idp list-users `
    --user-pool-id $CognitoUserPoolId `
    --filter "email = '$Email'" `
    --region $Region `
    --output json | ConvertFrom-Json

if ($userSearch -and $userSearch.Users -and $userSearch.Users.Count -gt 0) {
    $existingUser = $userSearch.Users[0]
}

if ($existingUser -and $existingUser.Username) {
    Write-Warning "User already exists in the pool. Will update password and group only."
} else {
    Write-Info "Creating user..."
    aws cognito-idp admin-create-user `
        --user-pool-id $CognitoUserPoolId `
        --username $Email `
        --user-attributes `
            Name=email,Value=$Email `
            Name=email_verified,Value=true `
            Name=given_name,Value=$FirstName `
            Name=family_name,Value=$LastName `
            Name=name,Value="$FirstName $LastName" `
            Name=custom:profile_type,Value=$ProfileType `
        --message-action SUPPRESS `
        --region $Region | Out-Null

    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to create user."
        exit 1
    }
}

Write-Info "Confirming user..."
aws cognito-idp admin-confirm-sign-up `
    --user-pool-id $CognitoUserPoolId `
    --username $Email `
    --region $Region 2>$null | Out-Null

Write-Info "Setting permanent password..."
aws cognito-idp admin-set-user-password `
    --user-pool-id $CognitoUserPoolId `
    --username $Email `
    --password $Password `
    --permanent `
    --region $Region | Out-Null

if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to set password."
    exit 1
}

Write-Info "Ensuring email is verified..."
aws cognito-idp admin-update-user-attributes `
    --user-pool-id $CognitoUserPoolId `
    --username $Email `
    --user-attributes `
        Name=email_verified,Value=true `
        Name=given_name,Value=$FirstName `
        Name=family_name,Value=$LastName `
        Name=name,Value="$FirstName $LastName" `
        Name=custom:profile_type,Value=$ProfileType `
    --region $Region 2>$null | Out-Null

Write-Info "Adding user to group: $GroupName"
aws cognito-idp admin-add-user-to-group `
    --user-pool-id $CognitoUserPoolId `
    --username $Email `
    --group-name $GroupName `
    --region $Region | Out-Null

if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to add user to group."
    exit 1
}

Write-Success "Admin user ready."
Write-Success "Email: $Email"
Write-Info "Password was set as provided (not displayed)."
