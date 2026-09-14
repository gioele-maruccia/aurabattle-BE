#Requires -Version 5.1
<#
.SYNOPSIS
Reset a user to "basic" role via Backoffice API (properly deletes company and all data).

.DESCRIPTION
Given a user email, authenticates as backoffice admin and calls the reset-profile endpoint.
This properly:
- Deletes company record from Companies table
- Deletes all inactive job listings and bookings
- Deletes all user documents
- Resets Cognito attributes to basic

.PARAMETER Email
The user's email address

.EXAMPLE
.\reset-user-via-backoffice-api.ps1 -Email "baximat685@noihse.com"
#>

param(
    [Parameter(Mandatory = $true)]
    [string]$Email,
    
    [string]$BackofficeEmail = "gioelemaruccia8@gmail.com",
    [string]$BackofficePassword = "Password@1",
    [string]$ApiEndpoint = "https://a8ombqjwe2.execute-api.eu-south-1.amazonaws.com/dev",
    [string]$Region = "eu-south-1",
    [string]$CognitoUserPoolId = "eu-south-1_0oK9agPYd",
    [string]$ClientId = "4mc318b69uktpmfc008g47dsgj"
)

function Write-Success { Write-Host $args -ForegroundColor Green }
function Write-Error { Write-Host "ERROR: $args" -ForegroundColor Red }
function Write-Info { Write-Host "INFO: $args" -ForegroundColor Cyan }
function Write-Warning { Write-Host "WARNING: $args" -ForegroundColor Yellow }

Write-Info "Backoffice Reset User to Basic (via API)"
Write-Info "=========================================="
Write-Info ""

# Step 1: Find user
Write-Info "Step 1: Finding user by email: $Email"
$userJson = aws cognito-idp admin-get-user --user-pool-id $CognitoUserPoolId --username $Email --region $Region --output json
if ($LASTEXITCODE -ne 0) {
    Write-Error "User not found: $Email"
    exit 1
}

$user = $userJson | ConvertFrom-Json
$userId = $user.Username
$profileType = "basic"
foreach ($attr in $user.UserAttributes) {
    if ($attr.Name -eq "custom:profile_type") {
        $profileType = $attr.Value
    }
}

Write-Success "Found user: $userId"
Write-Info "Current profile type: $profileType"

# Step 2: Authenticate as backoffice admin
Write-Info ""
Write-Info "Step 2: Authenticating as backoffice admin..."
$authJson = aws cognito-idp initiate-auth --auth-flow USER_PASSWORD_AUTH --client-id $ClientId --auth-parameters "USERNAME=$BackofficeEmail,PASSWORD=$BackofficePassword" --region $Region --output json
if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to authenticate"
    exit 1
}

$authResponse = $authJson | ConvertFrom-Json
$idToken = $authResponse.AuthenticationResult.IdToken
Write-Success "Authenticated successfully"

# Step 3: Call reset-profile endpoint
Write-Info ""
Write-Info "Step 3: Calling backoffice reset-profile API..."
Write-Warning "This will delete company record, job listings, bookings, and documents"
Write-Info ""

$resetUrl = "$ApiEndpoint/reset-profile"
$bodyJson = @{ userSub = $userId } | ConvertTo-Json -Compress
$headers = @{ "Authorization" = "Bearer $idToken"; "Content-Type" = "application/json" }

try {
    $result = Invoke-RestMethod -Uri $resetUrl -Method POST -Headers $headers -Body $bodyJson -ErrorAction Stop
    Write-Success "Profile reset successfully!"
    Write-Info ""
    Write-Info "Reset Summary:"
    Write-Info "User Sub: $($result.summary.userSub)"
    Write-Info "Previous Profile Type: $($result.summary.previousProfileType)"
    
    if ($result.summary.deletedItems) {
        $items = $result.summary.deletedItems
        Write-Info ""
        Write-Info "Deleted Items:"
        if ($items.bookings)     { Write-Info "  - Bookings:      $($items.bookings)" }
        if ($items.jobListings)  { Write-Info "  - Job Listings:  $($items.jobListings)" }
        if ($items.companyRecord){ Write-Info "  - Company Record: $($items.companyRecord)" }
        if ($items.documents)    { Write-Info "  - Documents:     $($items.documents)" }
    }
    
    Write-Info ""
    Write-Success "[OK] Reset completed successfully!"
} catch {
    Write-Host "STATUS: $($_.Exception.Response.StatusCode.value__)" -ForegroundColor Red
    Write-Host "ERROR: $($_.ErrorDetails.Message)" -ForegroundColor Red
    exit 1
}
