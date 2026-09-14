# Test update-booking-dates with date conflict

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
Write-Host "   UPDATE BOOKING DATES - CONFLICT TEST" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Test User: $WORKER_EMAIL" -ForegroundColor Yellow
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Step 1: Authenticate
Write-Host "[1/4] Authenticating..." -ForegroundColor Green

try {
    $authResponse = aws cognito-idp admin-initiate-auth `
        --user-pool-id $USER_POOL_ID `
        --client-id $CLIENT_ID `
        --auth-flow ADMIN_USER_PASSWORD_AUTH `
        --auth-parameters "USERNAME=$WORKER_EMAIL,PASSWORD=$WORKER_PASSWORD" `
        --region $REGION 2>&1 | ConvertFrom-Json
    
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

# Step 2: Extract workerId from token
Write-Host ""
Write-Host "[2/4] Extracting worker ID..." -ForegroundColor Green

$tokenParts = $TOKEN.Split(".")
$payloadBase64 = $tokenParts[1]
while ($payloadBase64.Length % 4 -ne 0) {
    $payloadBase64 += "="
}
$payloadBytes = [Convert]::FromBase64String($payloadBase64)
$payloadJson = [System.Text.Encoding]::UTF8.GetString($payloadBytes)
$payload = $payloadJson | ConvertFrom-Json
$WORKER_ID = $payload.sub

Write-Host "   Worker ID: $WORKER_ID" -ForegroundColor Cyan

# Step 3: Get worker's bookings
Write-Host ""
Write-Host "[3/4] Fetching worker bookings..." -ForegroundColor Green

try {
    $response = Invoke-RestMethod -Uri "$API_BASE/bookings/worker/$WORKER_ID" -Method GET -Headers @{
        "Authorization" = "Bearer $TOKEN"
        "Content-Type" = "application/json"
    }
    
    $bookings = $response.bookings | Sort-Object -Property createdAt -Descending
    Write-Host "   Found $($bookings.Count) bookings" -ForegroundColor Cyan
    
    if ($bookings.Count -eq 0) {
        Write-Host "   ERROR: No bookings found!" -ForegroundColor Red
        exit 1
    }
    
    # Get the latest booking
    $latestBooking = $bookings[0]
    Write-Host ""
    Write-Host "   Latest Booking:" -ForegroundColor Yellow
    Write-Host "   - ID:        $($latestBooking.bookingId)" -ForegroundColor Cyan
    Write-Host "   - Listing:   $($latestBooking.listingId)" -ForegroundColor Cyan
    Write-Host "   - Status:    $($latestBooking.status)" -ForegroundColor Cyan
    Write-Host "   - Dates:     $($latestBooking.startDate) to $($latestBooking.endDate)" -ForegroundColor Cyan
    
    $bookingId = $latestBooking.bookingId
    $listingId = $latestBooking.listingId
}
catch {
    Write-Host "ERROR: $_" -ForegroundColor Red
    exit 1
}

# Step 4: Try to update dates with conflict
Write-Host ""
Write-Host "[4/4] TEST: Update dates to 2026-02-10 / 2026-02-15 (conflict expected)" -ForegroundColor Magenta
Write-Host "   Expected: 409 Conflict (another booking on same listing overlaps)" -ForegroundColor Yellow

$conflictStart = "2026-02-10"
$conflictEnd = "2026-02-15"

$updateBody = @{
    startDate = $conflictStart
    endDate = $conflictEnd
} | ConvertTo-Json

Write-Host "   Booking ID: $bookingId" -ForegroundColor Gray
Write-Host "   New dates: $conflictStart to $conflictEnd" -ForegroundColor Gray
Write-Host ""

try {
    $response = Invoke-RestMethod -Uri "$API_BASE/bookings/$bookingId/dates" -Method PATCH -Headers @{
        "Authorization" = "Bearer $TOKEN"
        "Content-Type" = "application/json"
    } -Body $updateBody
    
    Write-Host "   UNEXPECTED: Got 200 instead of 409!" -ForegroundColor Red
    Write-Host "   Response: $($response | ConvertTo-Json)" -ForegroundColor Gray
}
catch {
    $statusCode = $_.Exception.Response.StatusCode.value__
    
    if ($statusCode -eq 409) {
        Write-Host "   SUCCESS: Got 409 Conflict as expected!" -ForegroundColor Green
        try {
            $error = $_.ErrorDetails.Message | ConvertFrom-Json
            Write-Host ""
            Write-Host "   Error Details:" -ForegroundColor Cyan
            Write-Host "   - Message: $($error.message)" -ForegroundColor Gray
            Write-Host "   - ConflictingBookingId: $($error.conflictingBookingId)" -ForegroundColor Gray
            Write-Host "   - ConflictingStatus: $($error.conflictingStatus)" -ForegroundColor Gray
            if ($error.conflictingDates) {
                Write-Host "   - ConflictingDates: $($error.conflictingDates.startDate) to $($error.conflictingDates.endDate)" -ForegroundColor Gray
            }
        }
        catch {
            Write-Host "   Error response: $($_.ErrorDetails.Message)" -ForegroundColor Gray
        }
    }
    elseif ($statusCode -eq 400) {
        Write-Host "   Got 400 Bad Request:" -ForegroundColor Yellow
        try {
            $error = $_.ErrorDetails.Message | ConvertFrom-Json
            Write-Host "   - Message: $($error.message)" -ForegroundColor Gray
        }
        catch {}
    }
    else {
        Write-Host "   Got status: $statusCode" -ForegroundColor Yellow
        Write-Host "   Error: $($_.Exception.Message)" -ForegroundColor Gray
    }
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "   TEST COMPLETE" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
