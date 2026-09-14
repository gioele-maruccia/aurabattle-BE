# Test 1: Update Booking Dates - Verifica fix formato data

$API_BASE = "https://f0xtalggll.execute-api.eu-south-1.amazonaws.com/dev"
$CLIENT_ID = "79g67hnuepfuoh1fnk4d98jfpu"
$REGION = "eu-south-1"

$WORKER_EMAIL = "gecetev283@naqulu.com"
$WORKER_PASSWORD = "Password@1"

Write-Host "=== TEST 1: UPDATE BOOKING DATES - FIX FORMATO DATA ===" -ForegroundColor Cyan

# Step 1: Login worker with Cognito
Write-Host "`n1. Login worker with Cognito..." -ForegroundColor Yellow

try {
    $authResult = aws cognito-idp initiate-auth `
        --region $REGION `
        --auth-flow USER_PASSWORD_AUTH `
        --client-id $CLIENT_ID `
        --auth-parameters "USERNAME=$WORKER_EMAIL,PASSWORD=$WORKER_PASSWORD" `
        --output json | ConvertFrom-Json
    
    $workerToken = $authResult.AuthenticationResult.IdToken
    Write-Host "[OK] Login successful" -ForegroundColor Green
} catch {
    Write-Host "[ERROR] Login failed" -ForegroundColor Red
    exit 1
}

# Step 2: Get worker ID from token
Write-Host "`n2. Getting worker ID from token..." -ForegroundColor Yellow

# Decode JWT payload (middle part)
$tokenParts = $workerToken.Split('.')
$payloadBase64 = $tokenParts[1]

# Add padding if needed
switch ($payloadBase64.Length % 4) {
    2 { $payloadBase64 += "==" }
    3 { $payloadBase64 += "=" }
}

$payload = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($payloadBase64))
$payloadJson = $payload | ConvertFrom-Json
$workerId = $payloadJson.sub

Write-Host "[OK] Worker ID: $workerId" -ForegroundColor Green

# Step 3: Get worker bookings
Write-Host "`n3. Getting worker bookings..." -ForegroundColor Yellow

$headers = @{
    "Authorization" = "Bearer $workerToken"
    "Content-Type" = "application/json"
}

try {
    $bookingsResponse = Invoke-RestMethod -Uri "$API_BASE/bookings/worker/$workerId" -Method GET -Headers $headers
    $bookings = $bookingsResponse.bookings
    Write-Host "[OK] Found $($bookings.Count) bookings" -ForegroundColor Green
    
    $pendingBooking = $bookings | Where-Object { $_.status -eq "pending" } | Select-Object -First 1
    
    if (-not $pendingBooking) {
        Write-Host "[ERROR] No pending bookings found" -ForegroundColor Red
        exit 1
    }
    
    Write-Host "  Using booking: $($pendingBooking.bookingId)" -ForegroundColor Gray
    Write-Host "  Current dates: $($pendingBooking.startDate) to $($pendingBooking.endDate)" -ForegroundColor Gray
    Write-Host "  Listing period: $($pendingBooking.listing.startDate) to $($pendingBooking.listing.endDate)" -ForegroundColor Gray
    
} catch {
    Write-Host "[ERROR] Failed to get bookings: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

# Step 4: Test update with date-only format
Write-Host "`n4. Testing update with date-only format (YYYY-MM-DD)..." -ForegroundColor Yellow

# Use dates within the listing period (near the end to avoid conflicts)
$listingEnd = [DateTime]::Parse($pendingBooking.listing.endDate)

$newStartDate = $listingEnd.AddDays(-20).ToString("yyyy-MM-dd")
$newEndDate = $listingEnd.AddDays(-10).ToString("yyyy-MM-dd")

Write-Host "  New dates: $newStartDate to $newEndDate" -ForegroundColor Gray

$updateBody = @{
    startDate = $newStartDate
    endDate = $newEndDate
} | ConvertTo-Json

try {
    $updateResponse = Invoke-RestMethod -Uri "$API_BASE/bookings/$($pendingBooking.bookingId)/dates" -Method PATCH -Body $updateBody -Headers $headers
    Write-Host "[OK] Update successful with date-only format!" -ForegroundColor Green
} catch {
    Write-Host "[ERROR] Update failed" -ForegroundColor Red
    Write-Host "  StatusCode: $($_.Exception.Response.StatusCode.value__)" -ForegroundColor Red
    if ($_.ErrorDetails.Message) {
        $errorDetails = $_.ErrorDetails.Message | ConvertFrom-Json
        Write-Host "  Error: $($errorDetails.error)" -ForegroundColor Red
        Write-Host "  Message: $($errorDetails.message)" -ForegroundColor Red
    }
    exit 1
}

# Step 5: Test update with datetime format
Write-Host "`n5. Testing update with datetime format (YYYY-MM-DDTHH:MM:SSZ)..." -ForegroundColor Yellow

$newStartDatetime = $listingEnd.AddDays(-9).ToString("yyyy-MM-ddT00:00:00Z")
$newEndDatetime = $listingEnd.AddDays(-5).ToString("yyyy-MM-ddT00:00:00Z")

Write-Host "  New dates: $newStartDatetime to $newEndDatetime" -ForegroundColor Gray

$updateBody2 = @{
    startDate = $newStartDatetime
    endDate = $newEndDatetime
} | ConvertTo-Json

try {
    $updateResponse2 = Invoke-RestMethod -Uri "$API_BASE/bookings/$($pendingBooking.bookingId)/dates" -Method PATCH -Body $updateBody2 -Headers $headers
    Write-Host "[OK] Update successful with datetime format!" -ForegroundColor Green
} catch {
    Write-Host "[ERROR] Update failed" -ForegroundColor Red
    exit 1
}

Write-Host "`n=== TEST 1 COMPLETED SUCCESSFULLY ===" -ForegroundColor Green
