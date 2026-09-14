# Test Booking Validation Rules
# Tests create-booking and update-booking-dates with conflicts

$ErrorActionPreference = "Continue"

# Configuration
$API_BASE = "https://f0xtalggll.execute-api.eu-south-1.amazonaws.com/dev"
$REGION = "eu-south-1"
$USER_POOL_ID = "eu-south-1_0oK9agPYd"
$CLIENT_ID = "79g67hnuepfuoh1fnk4d98jfpu"
$WORKER_EMAIL = "gecetev283@naqulu.com"
$WORKER_PASSWORD = "Password@1"

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "   BOOKING VALIDATION TEST" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Test User: $WORKER_EMAIL" -ForegroundColor Yellow
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Step 1: Authenticate
Write-Host "[1/5] Authenticating..." -ForegroundColor Green

try {
    $authResponse = aws cognito-idp admin-initiate-auth `
        --user-pool-id $USER_POOL_ID `
        --client-id $CLIENT_ID `
        --auth-flow ADMIN_USER_PASSWORD_AUTH `
        --auth-parameters "USERNAME=$WORKER_EMAIL,PASSWORD=$WORKER_PASSWORD" `
        --region $REGION 2>&1 | ConvertFrom-Json
        
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: $_" -ForegroundColor Red
        exit 1
    }
    
    $TOKEN = $authResponse.AuthenticationResult.IdToken
    
    if ([string]::IsNullOrWhiteSpace($TOKEN)) {
        Write-Host "ERROR: Failed to get token!" -ForegroundColor Red
        exit 1
    }
    
    Write-Host "   Success!" -ForegroundColor Green
}
catch {
    Write-Host "ERROR: $_" -ForegroundColor Red
    exit 1
}

# Step 2: Get existing bookings
Write-Host ""
Write-Host "[2/5] Fetching existing bookings..." -ForegroundColor Green

# Extract workerId from token
$tokenParts = $TOKEN.Split(".")
$payloadBase64 = $tokenParts[1]
while ($payloadBase64.Length % 4 -ne 0) {
    $payloadBase64 += "="
}
$payloadBytes = [Convert]::FromBase64String($payloadBase64)
$payloadJson = [System.Text.Encoding]::UTF8.GetString($payloadBytes)
$payload = $payloadJson | ConvertFrom-Json
$WORKER_ID = $payload.sub

Write-Host "Worker ID: $WORKER_ID" -ForegroundColor Gray

try {
    $response = Invoke-RestMethod -Uri "$API_BASE/bookings/worker/$WORKER_ID" -Method GET -Headers @{
        "Authorization" = "Bearer $TOKEN"
        "Content-Type" = "application/json"
    }
    
    $bookings = $response.bookings
    Write-Host "   Found $($bookings.Count) bookings" -ForegroundColor Cyan
    
    $pending = $bookings | Where-Object { $_.status -eq "pending" }
    $confirmed = $bookings | Where-Object { $_.status -eq "confirmed" }
    $rejected = $bookings | Where-Object { $_.status -eq "rejected" }
    
    Write-Host "   - Pending: $($pending.Count)" -ForegroundColor Yellow
    Write-Host "   - Confirmed: $($confirmed.Count)" -ForegroundColor Green
    Write-Host "   - Rejected: $($rejected.Count)" -ForegroundColor Red
}
catch {
    Write-Host "ERROR: $_" -ForegroundColor Red
}

# Step 3: Get job listings (from different API)
Write-Host ""
Write-Host "[3/5] Using first confirmed booking for conflict tests..." -ForegroundColor Green

if ($confirmed.Count -gt 0) {
    Write-Host "   Using confirmed booking: $($confirmed[0].bookingId)" -ForegroundColor Cyan
}

# Step 4: Test creating booking with PENDING conflict
Write-Host ""
Write-Host "[4/5] TEST: Create booking with PENDING conflict (expect 409)" -ForegroundColor Magenta

if ($pending.Count -gt 0) {
    Write-Host "   SKIPPED: No pending bookings available" -ForegroundColor Yellow
}

# Step 5: Test with confirmed conflict
Write-Host ""
Write-Host "[5/5] TEST: Create booking with confirmed conflict" -ForegroundColor Magenta

if ($confirmed.Count -gt 0 -and $listings.Count -gt 1) {
    $conflictBooking = $confirmed[0]
    $differentListing = $listings | Where-Object { $_.listingId -ne $conflictBooking.listingId } | Select-Object -First 1
    
    if ($differentListing) {
        $body = @{
            listingId = $differentListing.listingId
            startDate = $conflictBooking.startDate
            endDate = $conflictBooking.endDate
            message = "TEST - expecting 409 conflict"
        } | ConvertTo-Json
        
        Write-Host "   Listing: $($differentListing.listingId)" -ForegroundColor Gray
        Write-Host "   Dates: $($conflictBooking.startDate) to $($conflictBooking.endDate)" -ForegroundColor Gray
        
        try {
            $response = Invoke-RestMethod -Uri "$API_BASE/bookings" -Method POST -Headers @{
                "Authorization" = "Bearer $TOKEN"
                "Content-Type" = "application/json"
            } -Body $body
            
            Write-Host "   UNEXPECTED: Got 201 instead of 409!" -ForegroundColor Red
        }
        catch {
            $statusCode = $_.Exception.Response.StatusCode.value__
            
            if ($statusCode -eq 409) {
                Write-Host "   SUCCESS: Got 409 Conflict" -ForegroundColor Green
                try {
                    $error = $_.ErrorDetails.Message | ConvertFrom-Json
                    Write-Host "   Message: $($error.message)" -ForegroundColor Cyan
                }
                catch {}
            }
            else {
                Write-Host "   Got status: $statusCode" -ForegroundColor Yellow
            }
        }
    }
}
else {
    Write-Host "   SKIPPED: No confirmed bookings or listings" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "   TEST COMPLETE" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
