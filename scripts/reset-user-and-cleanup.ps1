#Requires -Version 5.1
<#
.SYNOPSIS
Reset user to "basic" and cleanup all associated data (company, job listings).

.DESCRIPTION
This script performs a complete cleanup:
1. Resets Cognito user to "basic" profile
2. Finds and deletes associated company record
3. Finds and deletes all job listings for that company
4. Removes user from worker/company groups

.PARAMETER Email
The user's email address

.PARAMETER CognitoUserPoolId
Cognito User Pool ID (default: eu-south-1_0oK9agPYd)

.PARAMETER Region
AWS region (default: eu-south-1)

.EXAMPLE
.\reset-user-and-cleanup.ps1 -Email "user@example.com"

#>

param(
    [Parameter(Mandatory = $true)]
    [string]$Email,
    
    [Parameter(Mandatory = $false)]
    [string]$CognitoUserPoolId = "eu-south-1_0oK9agPYd",
    
    [Parameter(Mandatory = $false)]
    [string]$Region = "eu-south-1"
)

# Color helpers
function Write-Success { Write-Host $args -ForegroundColor Green }
function Write-Error { Write-Host "ERROR: $args" -ForegroundColor Red }
function Write-Info { Write-Host "INFO: $args" -ForegroundColor Cyan }
function Write-Warning { Write-Host "WARNING: $args" -ForegroundColor Yellow }

Write-Info "=========================================="
Write-Info "Reset User to Basic + Cleanup"
Write-Info "=========================================="
Write-Info ""

# Step 1: Find user in Cognito
Write-Info "Step 1: Finding user by email: $Email"
$userJson = aws cognito-idp admin-get-user `
    --user-pool-id $CognitoUserPoolId `
    --username $Email `
    --region $Region `
    --output json

if ($LASTEXITCODE -ne 0) {
    Write-Error "User not found: $Email"
    exit 1
}

$user = $userJson | ConvertFrom-Json
$userId = $user.Username

# Get current profile type
$profileType = "basic"
foreach ($attr in $user.UserAttributes) {
    if ($attr.Name -eq "custom:profile_type") {
        $profileType = $attr.Value
    }
}

Write-Success "Found user: $userId"
Write-Info "Current profile type: $profileType"
Write-Info ""

# Step 2: Check if user has a company record
Write-Info "Step 2: Checking for associated company..."
$companyJson = aws dynamodb get-item `
    --table-name dev-Companies `
    --key "{`"userId`":{`"S`":`"$userId`"}}" `
    --region $Region `
    --output json 2>$null

$hasCompany = $false
$companyId = $null
$businessName = $null

if ($LASTEXITCODE -eq 0 -and $companyJson) {
    $companyData = $companyJson | ConvertFrom-Json
    if ($companyData.Item) {
        $hasCompany = $true
        $companyId = $companyData.Item.companyId.S
        $businessName = $companyData.Item.businessName.S
        Write-Warning "Found company record:"
        Write-Warning "  - Company ID: $companyId"
        Write-Warning "  - Business Name: $businessName"
    }
}

if (-not $hasCompany) {
    Write-Info "No company record found for this user"
}
Write-Info ""

# Step 3: Check for job listings (if company exists)
$jobListings = @()
if ($hasCompany) {
    Write-Info "Step 3: Checking for job listings..."
    $listingsJson = aws dynamodb scan `
        --table-name dev-JobListings `
        --filter-expression "contains(companyId, :cid)" `
        --expression-attribute-values "{`":cid`":{`"S`":`"$($companyId.Substring(0,8))`"}}" `
        --region $Region `
        --query "Items[].{listingId:listingId.S,companyId:companyId.S,status:status.S,title:title.S}" `
        --output json 2>$null
    
    if ($LASTEXITCODE -eq 0 -and $listingsJson) {
        $listingsData = $listingsJson | ConvertFrom-Json
        if ($listingsData.value) {
            $jobListings = $listingsData.value | Where-Object { $_.companyId -eq $companyId }
        }
    }
    
    if ($jobListings.Count -gt 0) {
        Write-Warning "Found $($jobListings.Count) job listings:"
        foreach ($listing in $jobListings) {
            Write-Warning "  - [$($listing.status)] $($listing.title) (ID: $($listing.listingId))"
        }
    } else {
        Write-Info "No job listings found for this company"
    }
    Write-Info ""
}

# Step 4: Confirm deletion
if ($hasCompany -or $jobListings.Count -gt 0) {
    Write-Warning ""
    Write-Warning "=========================================="
    Write-Warning "DELETION SUMMARY"
    Write-Warning "=========================================="
    Write-Warning "The following will be deleted:"
    Write-Warning ""
    if ($hasCompany) {
        Write-Warning "  [X] Company: $businessName (ID: $companyId)"
    }
    if ($jobListings.Count -gt 0) {
        Write-Warning "  [X] $($jobListings.Count) Job Listings"
    }
    Write-Warning ""
    $confirmation = Read-Host "Type 'DELETE' to confirm deletion"
    
    if ($confirmation -ne "DELETE") {
        Write-Error "Deletion cancelled by user"
        exit 1
    }
    Write-Info ""
}

# Step 5: Delete job listings
if ($jobListings.Count -gt 0) {
    Write-Info "Step 5: Deleting job listings..."
    $deletedCount = 0
    foreach ($listing in $jobListings) {
        aws dynamodb delete-item `
            --table-name dev-JobListings `
            --key "{`"listingId`":{`"S`":`"$($listing.listingId)`"}}" `
            --region $Region 2>$null
        
        if ($LASTEXITCODE -eq 0) {
            $deletedCount++
            Write-Success "  [✓] Deleted: $($listing.title)"
        } else {
            Write-Error "  [X] Failed to delete: $($listing.title)"
        }
    }
    Write-Success "Deleted $deletedCount job listings"
    Write-Info ""
}

# Step 6: Delete company record
if ($hasCompany) {
    Write-Info "Step 6: Deleting company record..."
    aws dynamodb delete-item `
        --table-name dev-Companies `
        --key "{`"userId`":{`"S`":`"$userId`"}}" `
        --region $Region
    
    if ($LASTEXITCODE -eq 0) {
        Write-Success "Company record deleted: $businessName"
    } else {
        Write-Error "Failed to delete company record"
    }
    Write-Info ""
}

# Step 7: Get current Cognito groups
Write-Info "Step 7: Resetting Cognito profile..."
$groupsJson = aws cognito-idp admin-list-groups-for-user `
    --user-pool-id $CognitoUserPoolId `
    --username $userId `
    --region $Region `
    --output json

$groupsToRemove = @()
if ($LASTEXITCODE -eq 0 -and $groupsJson) {
    $groups = $groupsJson | ConvertFrom-Json
    if ($groups.Groups) {
        $groups.Groups | ForEach-Object {
            if ($_.GroupName -eq "workers" -or $_.GroupName -eq "companies") {
                $groupsToRemove += $_.GroupName
            }
        }
    }
}

if ($groupsToRemove.Count -eq 0) {
    Write-Info "User already has no worker/company groups"
} else {
    Write-Info "Removing user from groups: $($groupsToRemove -join ', ')"
    
    # Remove user from groups
    $groupsToRemove | ForEach-Object {
        aws cognito-idp admin-remove-user-from-group `
            --user-pool-id $CognitoUserPoolId `
            --username $userId `
            --group-name $_ `
            --region $Region
        
        if ($LASTEXITCODE -eq 0) {
            Write-Success "  [✓] Removed from group: $_"
        }
    }
}

# Step 8: Reset profile type to basic
Write-Info "Setting profile type to 'basic'..."
aws cognito-idp admin-update-user-attributes `
    --user-pool-id $CognitoUserPoolId `
    --username $userId `
    --user-attributes "Name=custom:profile_type,Value=basic" `
    --region $Region

if ($LASTEXITCODE -eq 0) {
    Write-Success "Profile type set to 'basic'"
}

# Step 9: Clear verification attributes
Write-Info "Clearing verification attributes..."
aws cognito-idp admin-delete-user-attributes `
    --user-pool-id $CognitoUserPoolId `
    --username $userId `
    --user-attribute-names "custom:verification_status" "custom:upgrade_requested_at" `
    --region $Region `
    2>&1 | Out-Null

if ($LASTEXITCODE -eq 0) {
    Write-Success "Verification attributes cleared"
} else {
    Write-Info "Verification attributes may not exist (this is ok)"
}

# Final summary
Write-Info ""
Write-Success "=========================================="
Write-Success "RESET COMPLETED SUCCESSFULLY!"
Write-Success "=========================================="
Write-Success "User: $Email"
Write-Success "User ID: $userId"
if ($hasCompany) {
    Write-Success "Company deleted: $businessName"
}
if ($jobListings.Count -gt 0) {
    Write-Success "Job listings deleted: $($jobListings.Count)"
}
Write-Success "Profile reset to: basic"
Write-Success ""
