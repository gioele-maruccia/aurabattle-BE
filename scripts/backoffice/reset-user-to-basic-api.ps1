#Requires -Version 5.1
<#
.SYNOPSIS
Reset a user to "basic" profile using the Backoffice API.

.DESCRIPTION
Authenticates a backoffice user and calls the POST /backoffice/reset-profile endpoint
to reset a specified user to "basic" profile type.

.PARAMETER BackofficeEmail
The backoffice user's email address for authentication.

.PARAMETER BackofficePassword
The backoffice user's password for authentication.

.PARAMETER TargetUserEmail
The email address of the user to reset to basic.

.PARAMETER BaseUrl
The API base URL. Default: https://v7m02xrzyh.execute-api.eu-south-1.amazonaws.com/dev

.PARAMETER ClientId
Cognito Client ID. Default: 79g67hnuepfuoh1fnk4d98jfpu

.PARAMETER Region
AWS region. Default: eu-south-1

.EXAMPLE
.\reset-user-to-basic-api.ps1 -BackofficeEmail "gioelemaruccia8@gmail.com" -BackofficePassword "Password@1" -TargetUserEmail "gabrielecassano05@gmail.com"

#>

param(
    [Parameter(Mandatory = $true)]
    [string]$BackofficeEmail,
    
    [Parameter(Mandatory = $true)]
    [string]$BackofficePassword,
    
    [Parameter(Mandatory = $true)]
    [string]$TargetUserEmail,
    
    [Parameter(Mandatory = $false)]
    [string]$BaseUrl = "https://v7m02xrzyh.execute-api.eu-south-1.amazonaws.com/dev",
    
    [Parameter(Mandatory = $false)]
    [string]$ClientId = "79g67hnuepfuoh1fnk4d98jfpu",
    
    [Parameter(Mandatory = $false)]
    [string]$Region = "eu-south-1"
)

# Color helpers
function Write-Success { Write-Host $args -ForegroundColor Green }
function Write-Error { Write-Host "ERROR: $args" -ForegroundColor Red }
function Write-Info { Write-Host "INFO: $args" -ForegroundColor Cyan }
function Write-Warning { Write-Host "WARNING: $args" -ForegroundColor Yellow }

$ErrorActionPreference = "Stop"

Write-Info "==================================================================="
Write-Info "Backoffice Reset User to Basic"
Write-Info "==================================================================="
Write-Info "Backoffice User: $BackofficeEmail"
Write-Info "Target User: $TargetUserEmail"
Write-Info "API Base URL: $BaseUrl"
Write-Info ""

# ============================================================================
# STEP 1: Authentication
# ============================================================================
Write-Info "Step 1: Authenticating backoffice user..."

try {
    $authResult = aws cognito-idp initiate-auth `
        --auth-flow USER_PASSWORD_AUTH `
        --client-id $ClientId `
        --auth-parameters USERNAME=$BackofficeEmail,PASSWORD=$BackofficePassword `
        --region $Region `
        --query 'AuthenticationResult' `
        --output json 2>&1 | ConvertFrom-Json
    
    if (-not $authResult.IdToken) {
        Write-Error "Failed to get IdToken from Cognito"
        exit 1
    }
    
    $token = $authResult.IdToken
    Write-Success "Authentication successful!"
    Write-Info ""
    
} catch {
    Write-Error "Authentication failed: $($_.Exception.Message)"
    exit 1
}

# ============================================================================
# STEP 2: Search for target user to get userSub
# ============================================================================
Write-Info "Step 2: Searching for target user..."

try {
    $headers = @{
        "Authorization" = "Bearer $token"
        "Content-Type" = "application/json"
    }
    
    $searchUrl = "$BaseUrl/users/search?q=$TargetUserEmail&type=email&limit=10"
    
    $searchResponse = Invoke-RestMethod -Uri $searchUrl -Method GET -Headers $headers -ErrorAction Stop
    
    if (-not $searchResponse.users -or $searchResponse.users.Count -eq 0) {
        Write-Error "User not found: $TargetUserEmail"
        exit 1
    }
    
    $targetUser = $searchResponse.users | Where-Object { $_.email -eq $TargetUserEmail } | Select-Object -First 1
    
    if (-not $targetUser) {
        Write-Error "User not found: $TargetUserEmail"
        exit 1
    }
    
    $userSub = $targetUser.sub
    $currentProfileType = $targetUser.profileType
    
    Write-Success "User found!"
    Write-Info "  User Sub: $userSub"
    Write-Info "  Name: $($targetUser.name)"
    Write-Info "  Current Profile Type: $currentProfileType"
    Write-Info ""
    
} catch {
    Write-Error "Failed to search for user: $($_.Exception.Message)"
    if ($_.ErrorDetails.Message) {
        Write-Error "Details: $($_.ErrorDetails.Message)"
    }
    exit 1
}

# ============================================================================
# STEP 3: Call reset-profile endpoint
# ============================================================================
Write-Info "Step 3: Resetting user profile to basic..."

try {
    $resetUrl = "$BaseUrl/reset-profile"
    
    # The API expects userSub in the body
    $requestBody = @{
        userSub = $userSub
    } | ConvertTo-Json -Compress
    
    Write-Info "Calling POST $resetUrl"
    Write-Info "Request body: $requestBody"
    Write-Info ""
    
    $resetResponse = Invoke-RestMethod -Uri $resetUrl -Method POST -Headers $headers -Body $requestBody -ErrorAction Stop
    
    Write-Success "===================================================================`n"
    Write-Success "Profile Reset Successful!"
    Write-Success ""
    Write-Info "Response:"
    Write-Info ($resetResponse | ConvertTo-Json -Depth 10)
    Write-Success ""
    Write-Success "===================================================================`n"
    
} catch {
    Write-Error "Failed to reset profile: $($_.Exception.Message)"
    
    if ($_.ErrorDetails.Message) {
        Write-Error ""
        Write-Error "Error Details:"
        try {
            $errorJson = $_.ErrorDetails.Message | ConvertFrom-Json
            Write-Error ($errorJson | ConvertTo-Json -Depth 10)
            
            # Display active bookings/listings if present
            if ($errorJson.activeBookings) {
                Write-Warning ""
                Write-Warning "Active Bookings Found:"
                $errorJson.activeBookings | ForEach-Object {
                    Write-Warning "  - Booking ID: $($_.bookingId)"
                    Write-Warning "    Job: $($_.jobTitle)"
                    Write-Warning "    Status: $($_.status)"
                    Write-Warning "    Dates: $($_.startDate) to $($_.endDate)"
                    Write-Warning ""
                }
            }
            
            if ($errorJson.activeListings) {
                Write-Warning ""
                Write-Warning "Active Job Listings Found:"
                $errorJson.activeListings | ForEach-Object {
                    Write-Warning "  - Listing ID: $($_.listingId)"
                    Write-Warning "    Title: $($_.jobTitle)"
                    Write-Warning "    Status: $($_.status)"
                    Write-Warning ""
                }
            }
            
        } catch {
            Write-Error $_.ErrorDetails.Message
        }
    }
    
    exit 1
}
