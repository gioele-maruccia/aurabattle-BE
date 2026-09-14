# =============================================================================
# COMPLETE BOOKING VALIDATION TEST
# =============================================================================
# Tests all business rules for create-booking and update-booking-dates
# 
# Test User: gecetev283@naqulu.com / Password@1
# This worker already has bookings for all available listings
#
# Test Scenarios:
# 1. Create booking in dates with PENDING booking for another listing (409)
# 2. Create booking in dates with CONFIRMED booking (409)
# 3. Create booking in dates with REJECTED booking (403)
# 4. Create booking successfully (201)
# 5. Update booking dates to conflict with pending (409)
# 6. Update booking dates to conflict with confirmed (409)
# 7. Update booking dates successfully (200)
# =============================================================================

$ErrorActionPreference = "Continue"

# Configuration
$API_BASE = "https://ybagxg3ni3.execute-api.eu-south-1.amazonaws.com/dev"
$REGION = "eu-south-1"
$COGNITO_CLIENT_ID = "4s0apqg5qtb6v9l82fddvd7o0v"

# Test user credentials
$WORKER_EMAIL = "gecetev283@naqulu.com"
$WORKER_PASSWORD = "Password@1"

Write-Host ""
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host "   COMPLETE BOOKING VALIDATION TEST" -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host "Test User: $WORKER_EMAIL" -ForegroundColor Yellow
Write-Host "API Base:  $API_BASE" -ForegroundColor Yellow
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host ""

# =============================================================================
# STEP 1: Authenticate and get JWT token
# =============================================================================
Write-Host "[1/7] Authenticating user..." -ForegroundColor Green
$authBody = @{
    AuthFlow = "USER_PASSWORD_AUTH"
    ClientId = $COGNITO_CLIENT_ID
    AuthParameters = @{
        USERNAME = $WORKER_EMAIL
        PASSWORD = $WORKER_PASSWORD
    }
} | ConvertTo-Json -Depth 10

try {
    $authResponse = aws cognito-idp initiate-auth --cli-input-json $authBody --region $REGION | ConvertFrom-Json
    $TOKEN = $authResponse.AuthenticationResult.IdToken
    
    if ([string]::IsNullOrWhiteSpace($TOKEN)) {
        Write-Host "ERROR: Failed to get token!" -ForegroundColor Red
        exit 1
    }
    
    Write-Host "   Token obtained successfully" -ForegroundColor Green
} catch {
    Write-Host "ERROR authenticating: $_" -ForegroundColor Red
    exit 1
}

# =============================================================================
# STEP 2: Get worker's existing bookings to understand current state
# =============================================================================
Write-Host ""
Write-Host "[2/8] Fetching worker existing bookings..." -ForegroundColor Green

try {
    $bookingsResponse = Invoke-RestMethod -Uri "$API_BASE/bookings/worker" -Method GET `
        -Headers @{
            "Authorization" = "Bearer $TOKEN"
            "Content-Type" = "application/json"
        }
    
    $existingBookings = $bookingsResponse.bookings
    Write-Host "   ✓ Found $($existingBookings.Count) existing bookings" -ForegroundColor Green
    
    # Categorize bookings by status
    $pendingBookings = $existingBookings | Where-Object { $_.status -eq "pending" }
    $confirmedBookings = $existingBookings | Where-Object { $_.status -eq "confirmed" }
    $rejectedBookings = $existingBookings | Where-Object { $_.status -eq "rejected" }
    $cancelledBookings = $existingBookings | Where-Object { $_.status -eq "cancelled" }
    
    Write-Host ""
    Write-Host "   Booking Summary:" -ForegroundColor Cyan
    Write-Host "   - Pending:   $($pendingBookings.Count)" -ForegroundColor Yellow
    Write-Host "   - Confirmed: $($confirmedBookings.Count)" -ForegroundColor Green
    Write-Host "   - Rejected:  $($rejectedBookings.Count)" -ForegroundColor Red
    Write-Host "   - Cancelled: $($cancelledBookings.Count)" -ForegroundColor Gray
    
    # Display some details
    if ($pendingBookings.Count -gt 0) {
        Write-Host ""
        Write-Host "   First Pending Booking:" -ForegroundColor Yellow
        $firstPending = $pendingBookings[0]
        Write-Host "   - ID:      $($firstPending.bookingId)" -ForegroundColor Gray
        Write-Host "   - Listing: $($firstPending.listingId)" -ForegroundColor Gray
        Write-Host "   - Dates:   $($firstPending.startDate) to $($firstPending.endDate)" -ForegroundColor Gray
    }
    
    if ($confirmedBookings.Count -gt 0) {
        Write-Host ""
        Write-Host "   First Confirmed Booking:" -ForegroundColor Green
        $firstConfirmed = $confirmedBookings[0]
        Write-Host "   - ID:      $($firstConfirmed.bookingId)" -ForegroundColor Gray
        Write-Host "   - Listing: $($firstConfirmed.listingId)" -ForegroundColor Gray
        Write-Host "   - Dates:   $($firstConfirmed.startDate) to $($firstConfirmed.endDate)" -ForegroundColor Gray
    }
    
    if ($rejectedBookings.Count -gt 0) {
        Write-Host ""
        Write-Host "   First Rejected Booking:" -ForegroundColor Red
        $firstRejected = $rejectedBookings[0]
        Write-Host "   - ID:      $($firstRejected.bookingId)" -ForegroundColor Gray
        Write-Host "   - Listing: $($firstRejected.listingId)" -ForegroundColor Gray
        Write-Host "   - Dates:   $($firstRejected.startDate) to $($firstRejected.endDate)" -ForegroundColor Gray
    }
    
} catch {
    Write-Host "ERROR fetching bookings: $_" -ForegroundColor Red
    Write-Host "Response: $($_.ErrorDetails.Message)" -ForegroundColor Gray
}

# =============================================================================
# STEP 3: Get available job listings
# =============================================================================
Write-Host ""
Write-Host "[3/8] Fetching available job listings..." -ForegroundColor Green

try {
    $listingsResponse = Invoke-RestMethod -Uri "$API_BASE/job-listings" -Method GET `
        -Headers @{
            "Authorization" = "Bearer $TOKEN"
            "Content-Type" = "application/json"
        }
    
    $availableListings = $listingsResponse.listings | Where-Object { $_.status -eq "published" }
    Write-Host "   ✓ Found $($availableListings.Count) published listings" -ForegroundColor Green
    
    if ($availableListings.Count -gt 0) {
        $testListing = $availableListings[0]
        Write-Host ""
        Write-Host "   Using test listing:" -ForegroundColor Yellow
        Write-Host "   - ID:      $($testListing.listingId)" -ForegroundColor Gray
        Write-Host "   - Title:   $($testListing.jobTitle)" -ForegroundColor Gray
        Write-Host "   - Period:  $($testListing.startDate) to $($testListing.endDate)" -ForegroundColor Gray
    }
    
} catch {
    Write-Host "ERROR fetching listings: $_" -ForegroundColor Red
    Write-Host "Response: $($_.ErrorDetails.Message)" -ForegroundColor Gray
    exit 1
}

# =============================================================================
# STEP 4: Test creating booking with PENDING conflict (409 expected)
# =============================================================================
Write-Host ""
Write-Host "[4/8] TEST 1: Create booking with PENDING conflict" -ForegroundColor Magenta
Write-Host "   Expected: 409 Conflict" -ForegroundColor Yellow

if ($pendingBookings.Count -gt 0 -and $availableListings.Count -gt 1) {
    $conflictDates = $pendingBookings[0]
    # Find a different listing
    $differentListing = $availableListings | Where-Object { $_.listingId -ne $conflictDates.listingId } | Select-Object -First 1
    
    if ($differentListing) {
        $testBody = @{
            listingId = $differentListing.listingId
            startDate = $conflictDates.startDate
            endDate = $conflictDates.endDate
            message = "TEST: Expecting 409 - pending conflict"
        } | ConvertTo-Json
        
        Write-Host "   Creating booking for listing: $($differentListing.listingId)" -ForegroundColor Gray
        Write-Host "   Using dates from pending booking: $($conflictDates.startDate) to $($conflictDates.endDate)" -ForegroundColor Gray
        
        try {
            $response = Invoke-RestMethod -Uri "$API_BASE/bookings" -Method POST `
                -Headers @{
                    "Authorization" = "Bearer $TOKEN"
                    "Content-Type" = "application/json"
                } `
                -Body $testBody
            
            Write-Host "   ✗ UNEXPECTED: Got 201 instead of 409!" -ForegroundColor Red
            Write-Host "   Response: $($response | ConvertTo-Json -Depth 5)" -ForegroundColor Gray
        } catch {
            $statusCode = $_.Exception.Response.StatusCode.value__
            $errorBody = $_.ErrorDetails.Message | ConvertFrom-Json
            
            if ($statusCode -eq 409) {
                Write-Host "   ✓ SUCCESS: Got 409 Conflict as expected" -ForegroundColor Green
                Write-Host "   Message: $($errorBody.message)" -ForegroundColor Cyan
                if ($errorBody.conflictingBookingId) {
                    Write-Host "   Conflicting Booking: $($errorBody.conflictingBookingId)" -ForegroundColor Gray
                    Write-Host "   Conflicting Status:  $($errorBody.conflictingStatus)" -ForegroundColor Gray
                }
            } else {
                Write-Host "   ✗ UNEXPECTED: Got $statusCode instead of 409" -ForegroundColor Red
                Write-Host "   Error: $($errorBody.message)" -ForegroundColor Gray
            }
        }
    } else {
        Write-Host "   ⊘ SKIPPED: No different listing available" -ForegroundColor Yellow
    }
} else {
    Write-Host "   ⊘ SKIPPED: No pending bookings or not enough listings" -ForegroundColor Yellow
}

# =============================================================================
# STEP 5: Test creating booking with CONFIRMED conflict (409 expected)
# =============================================================================
Write-Host ""
Write-Host "[5/8] TEST 2: Create booking with CONFIRMED conflict" -ForegroundColor Magenta
Write-Host "   Expected: 409 Conflict" -ForegroundColor Yellow

if ($confirmedBookings.Count -gt 0 -and $availableListings.Count -gt 1) {
    $conflictDates = $confirmedBookings[0]
    $differentListing = $availableListings | Where-Object { $_.listingId -ne $conflictDates.listingId } | Select-Object -First 1
    
    if ($differentListing) {
        $testBody = @{
            listingId = $differentListing.listingId
            startDate = $conflictDates.startDate
            endDate = $conflictDates.endDate
            message = "TEST: Expecting 409 - confirmed conflict"
        } | ConvertTo-Json
        
        Write-Host "   Creating booking for listing: $($differentListing.listingId)" -ForegroundColor Gray
        Write-Host "   Using dates from confirmed booking: $($conflictDates.startDate) to $($conflictDates.endDate)" -ForegroundColor Gray
        
        try {
            $response = Invoke-RestMethod -Uri "$API_BASE/bookings" -Method POST `
                -Headers @{
                    "Authorization" = "Bearer $TOKEN"
                    "Content-Type" = "application/json"
                } `
                -Body $testBody
            
            Write-Host "   ✗ UNEXPECTED: Got 201 instead of 409!" -ForegroundColor Red
        } catch {
            $statusCode = $_.Exception.Response.StatusCode.value__
            $errorBody = $_.ErrorDetails.Message | ConvertFrom-Json
            
            if ($statusCode -eq 409) {
                Write-Host "   ✓ SUCCESS: Got 409 Conflict as expected" -ForegroundColor Green
                Write-Host "   Message: $($errorBody.message)" -ForegroundColor Cyan
            } else {
                Write-Host "   ✗ UNEXPECTED: Got $statusCode instead of 409" -ForegroundColor Red
            }
        }
    } else {
        Write-Host "   ⊘ SKIPPED: No different listing available" -ForegroundColor Yellow
    }
} else {
    Write-Host "   ⊘ SKIPPED: No confirmed bookings or not enough listings" -ForegroundColor Yellow
}

# =============================================================================
# STEP 6: Test creating booking with REJECTED conflict (403 expected)
# =============================================================================
Write-Host ""
Write-Host "[6/8] TEST 3: Create booking with REJECTED conflict" -ForegroundColor Magenta
Write-Host "   Expected: 403 Forbidden" -ForegroundColor Yellow

if ($rejectedBookings.Count -gt 0) {
    $rejectedDates = $rejectedBookings[0]
    
    $testBody = @{
        listingId = $rejectedDates.listingId
        startDate = $rejectedDates.startDate
        endDate = $rejectedDates.endDate
        message = "TEST: Expecting 403 - rejected block"
    } | ConvertTo-Json
    
    Write-Host "   Creating booking for listing: $($rejectedDates.listingId)" -ForegroundColor Gray
    Write-Host "   Using dates from rejected booking: $($rejectedDates.startDate) to $($rejectedDates.endDate)" -ForegroundColor Gray
    
    try {
        $response = Invoke-RestMethod -Uri "$API_BASE/bookings" -Method POST `
            -Headers @{
                "Authorization" = "Bearer $TOKEN"
                "Content-Type" = "application/json"
            } `
            -Body $testBody
        
        Write-Host "   ✗ UNEXPECTED: Got 201 instead of 403!" -ForegroundColor Red
    } catch {
        $statusCode = $_.Exception.Response.StatusCode.value__
        $errorBody = $_.ErrorDetails.Message | ConvertFrom-Json
        
        if ($statusCode -eq 403) {
            Write-Host "   ✓ SUCCESS: Got 403 Forbidden as expected" -ForegroundColor Green
            Write-Host "   Message: $($errorBody.message)" -ForegroundColor Cyan
        } else {
            Write-Host "   ✗ UNEXPECTED: Got $statusCode instead of 403" -ForegroundColor Red
            Write-Host "   Error: $($errorBody.message)" -ForegroundColor Gray
        }
    }
} else {
    Write-Host "   ⊘ SKIPPED: No rejected bookings available" -ForegroundColor Yellow
}

# =============================================================================
# STEP 7: Create a new booking successfully (for update tests)
# =============================================================================
Write-Host ""
Write-Host "[7/8] TEST 4: Create new booking successfully" -ForegroundColor Magenta
Write-Host "   Expected: 201 Created" -ForegroundColor Yellow

$newBookingId = $null
if ($availableListings.Count -gt 0) {
    $testListing = $availableListings[0]
    
    # Use dates far in the future to avoid conflicts
    $newStartDate = (Get-Date).AddMonths(6).ToString("yyyy-MM-dd")
    $newEndDate = (Get-Date).AddMonths(6).AddDays(5).ToString("yyyy-MM-dd")
    
    $testBody = @{
        listingId = $testListing.listingId
        startDate = $newStartDate
        endDate = $newEndDate
        message = "TEST: New booking for update tests"
    } | ConvertTo-Json
    
    Write-Host "   Creating booking for listing: $($testListing.listingId)" -ForegroundColor Gray
    Write-Host "   Dates: $newStartDate to $newEndDate" -ForegroundColor Gray
    
    try {
        $response = Invoke-RestMethod -Uri "$API_BASE/bookings" -Method POST `
            -Headers @{
                "Authorization" = "Bearer $TOKEN"
                "Content-Type" = "application/json"
            } `
            -Body $testBody
        
        if ($response.booking.bookingId) {
            $newBookingId = $response.booking.bookingId
            Write-Host "   ✓ SUCCESS: Booking created" -ForegroundColor Green
            Write-Host "   Booking ID: $newBookingId" -ForegroundColor Cyan
            Write-Host "   Status: $($response.booking.status)" -ForegroundColor Gray
            Write-Host "   Chat ID: $($response.chatId)" -ForegroundColor Gray
        } else {
            Write-Host "   ✗ FAILED: No bookingId in response" -ForegroundColor Red
        }
    } catch {
        $statusCode = $_.Exception.Response.StatusCode.value__
        $errorBody = $_.ErrorDetails.Message | ConvertFrom-Json
        Write-Host "   ✗ FAILED: Got $statusCode" -ForegroundColor Red
        Write-Host "   Error: $($errorBody.message)" -ForegroundColor Gray
    }
} else {
    Write-Host "   ⊘ SKIPPED: No listings available" -ForegroundColor Yellow
}

# =============================================================================
# STEP 8: Test updating booking dates with conflict (409 expected)
# =============================================================================
Write-Host ""
Write-Host "[8/8] TEST 5: Update booking dates with conflict" -ForegroundColor Magenta
Write-Host "   Expected: 409 Conflict" -ForegroundColor Yellow

if ($newBookingId -and $pendingBookings.Count -gt 0) {
    $conflictDates = $pendingBookings[0]
    
    $updateBody = @{
        startDate = $conflictDates.startDate
        endDate = $conflictDates.endDate
    } | ConvertTo-Json
    
    Write-Host "   Updating booking: $newBookingId" -ForegroundColor Gray
    Write-Host "   New dates (conflict): $($conflictDates.startDate) to $($conflictDates.endDate)" -ForegroundColor Gray
    
    try {
        $response = Invoke-RestMethod -Uri "$API_BASE/bookings/$newBookingId/dates" -Method PATCH `
            -Headers @{
                "Authorization" = "Bearer $TOKEN"
                "Content-Type" = "application/json"
            } `
            -Body $updateBody
        
        Write-Host "   ✗ UNEXPECTED: Got 200 instead of 409!" -ForegroundColor Red
    } catch {
        $statusCode = $_.Exception.Response.StatusCode.value__
        $errorBody = $_.ErrorDetails.Message | ConvertFrom-Json
        
        if ($statusCode -eq 409) {
            Write-Host "   ✓ SUCCESS: Got 409 Conflict as expected" -ForegroundColor Green
            Write-Host "   Message: $($errorBody.message)" -ForegroundColor Cyan
        } else {
            Write-Host "   ✗ UNEXPECTED: Got $statusCode instead of 409" -ForegroundColor Red
            Write-Host "   Error: $($errorBody.message)" -ForegroundColor Gray
        }
    }
    
    # Now update to valid dates
    Write-Host ""
    Write-Host "   TEST 6: Update booking dates successfully" -ForegroundColor Magenta
    Write-Host "   Expected: 200 OK" -ForegroundColor Yellow
    
    $validStartDate = (Get-Date).AddMonths(7).ToString("yyyy-MM-dd")
    $validEndDate = (Get-Date).AddMonths(7).AddDays(5).ToString("yyyy-MM-dd")
    
    $updateBody = @{
        startDate = $validStartDate
        endDate = $validEndDate
    } | ConvertTo-Json
    
    Write-Host "   Updating booking: $newBookingId" -ForegroundColor Gray
    Write-Host "   New dates (valid): $validStartDate to $validEndDate" -ForegroundColor Gray
    
    try {
        $response = Invoke-RestMethod -Uri "$API_BASE/bookings/$newBookingId/dates" -Method PATCH `
            -Headers @{
                "Authorization" = "Bearer $TOKEN"
                "Content-Type" = "application/json"
            } `
            -Body $updateBody
        
        Write-Host "   ✓ SUCCESS: Booking dates updated" -ForegroundColor Green
        Write-Host "   New dates: $($response.booking.startDate) to $($response.booking.endDate)" -ForegroundColor Cyan
    } catch {
        $statusCode = $_.Exception.Response.StatusCode.value__
        $errorBody = $_.ErrorDetails.Message | ConvertFrom-Json
        Write-Host "   ✗ FAILED: Got $statusCode" -ForegroundColor Red
        Write-Host "   Error: $($errorBody.message)" -ForegroundColor Gray
    }
} else {
    Write-Host "   ⊘ SKIPPED: No new booking created or no pending bookings" -ForegroundColor Yellow
}

# =============================================================================
# SUMMARY
# =============================================================================
Write-Host ""
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host "   TEST EXECUTION COMPLETE" -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Check Lambda logs for detailed validation output:" -ForegroundColor Yellow
Write-Host "aws logs tail /aws/lambda/dev-bookings-create --region $REGION --since 10m --format short" -ForegroundColor Gray
Write-Host "aws logs tail /aws/lambda/dev-bookings-update-dates --region $REGION --since 10m --format short" -ForegroundColor Gray
Write-Host ""
