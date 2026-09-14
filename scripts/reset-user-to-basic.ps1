#Requires -Version 5.1
<#
.SYNOPSIS
Reset a user to "basic" role in DynamoDB (removes worker/company roles).

.DESCRIPTION
⚠️ WARNING: This script only modifies Cognito attributes.
It does NOT delete the company record from the Companies table or associated data.

For complete profile reset (including company deletion), use:
  .\reset-user-via-backoffice-api.ps1 -Email "user@example.com"

Given a user email, finds the user in Cognito and removes the "workers" or "companies" group,
reverting them to "basic" role (no custom attributes set).

.PARAMETER Email
The user's email address (e.g., nirdoperte@necub.com)

.PARAMETER CognitoUserPoolId
The Cognito User Pool ID. If not provided, reads from environment or prompts.

.PARAMETER Region
AWS region. Default: eu-south-1

.EXAMPLE
.\reset-user-to-basic.ps1 -Email "nirdoperte@necub.com"

#>

param(
    [Parameter(Mandatory = $true)]
    [string]$Email,
    
    [Parameter(Mandatory = $false)]
    [string]$CognitoUserPoolId,
    
    [Parameter(Mandatory = $false)]
    [string]$Region = "eu-south-1"
)

# Color helpers
function Write-Success { Write-Host $args -ForegroundColor Green }
function Write-Error { Write-Host "ERROR: $args" -ForegroundColor Red }
function Write-Info { Write-Host "INFO: $args" -ForegroundColor Cyan }
function Write-Warning { Write-Host "WARNING: $args" -ForegroundColor Yellow }

# Get Cognito User Pool ID
if (-not $CognitoUserPoolId) {
    $CognitoUserPoolId = $env:COGNITO_USER_POOL_ID
}

if (-not $CognitoUserPoolId) {
    Write-Error "Cognito User Pool ID not provided. Set COGNITO_USER_POOL_ID env var or pass -CognitoUserPoolId"
    exit 1
}

Write-Info "Using Cognito User Pool: $CognitoUserPoolId (Region: $Region)"
Write-Info "Searching for user: $Email"
Write-Warning ""
Write-Warning "⚠️  IMPORTANT: This script only modifies Cognito attributes."
Write-Warning "    It does NOT delete the company record or associated data!"
Write-Warning ""
Write-Warning "    For complete profile reset, use:"
Write-Warning "    .\reset-user-via-backoffice-api.ps1 -Email `"$Email`""
Write-Warning ""

try {
    # Find user by email
    $user = aws cognito-idp admin-get-user `
        --user-pool-id $CognitoUserPoolId `
        --username $Email `
        --region $Region `
        --output json | ConvertFrom-Json
    
    if (-not $user.Username) {
        Write-Error "User not found: $Email"
        exit 1
    }
    
    $userId = $user.Username
    Write-Success "Found user: $userId"
    
    # Get current groups
    Write-Info "Fetching user groups..."
    $groups = aws cognito-idp admin-list-groups-for-user `
        --user-pool-id $CognitoUserPoolId `
        --username $userId `
        --region $Region `
        --output json | ConvertFrom-Json
    
    $groupsToRemove = @()
    if ($groups.Groups) {
        $groups.Groups | ForEach-Object {
            if ($_.GroupName -eq "workers" -or $_.GroupName -eq "companies") {
                $groupsToRemove += $_.GroupName
            }
        }
    }
    
    if ($groupsToRemove.Count -eq 0) {
        Write-Warning "User is already basic (no worker/company groups)"
    }
    
    if ($groupsToRemove.Count -gt 0) {
        Write-Info "Groups to remove: $($groupsToRemove -join ', ')"
        
        # Remove user from groups
        $groupsToRemove | ForEach-Object {
            Write-Info "Removing user from group: $_"
            aws cognito-idp admin-remove-user-from-group `
                --user-pool-id $CognitoUserPoolId `
                --username $userId `
                --group-name $_ `
                --region $Region
            
            Write-Success "Removed from group: $_"
        }
    }
    
    # Reset profile type to basic
    Write-Info "Resetting profile type to 'basic'..."
    aws cognito-idp admin-update-user-attributes `
        --user-pool-id $CognitoUserPoolId `
        --username $userId `
        --user-attributes "Name=custom:profile_type,Value=basic" `
        --region $Region
    
    Write-Success "Profile type set to 'basic'"
    
    # Clear verification status and upgrade timestamp (if they exist)
    Write-Info "Clearing verification status and upgrade timestamp..."
    aws cognito-idp admin-delete-user-attributes `
        --user-pool-id $CognitoUserPoolId `
        --username $userId `
        --user-attribute-names "custom:verification_status" "custom:upgrade_requested_at" `
        --region $Region `
        2>&1 | Out-Null
    
    if ($LASTEXITCODE -eq 0) {
        Write-Success "Verification attributes cleared"
    } else {
        Write-Host "INFO: Verification attributes may not exist (this is ok)" -ForegroundColor Yellow
    }
    
    Write-Success "User reset to basic successfully!"
    Write-Success "Email: $Email"
    Write-Success "User ID: $userId"
    
}
catch {
    Write-Error "Failed to reset user: $_"
    exit 1
}
