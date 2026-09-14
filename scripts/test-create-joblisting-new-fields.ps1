# Test 2: Create Job Listing with New Fields

$API_JOBLISTINGS = "https://0kur695aae.execute-api.eu-south-1.amazonaws.com/dev"
$CLIENT_ID = "79g67hnuepfuoh1fnk4d98jfpu"
$REGION = "eu-south-1"

$COMPANY_EMAIL = "titocet754@naqulu.com"
$COMPANY_PASSWORD = "Password@1"

Write-Host "=== TEST 2: CREATE JOB LISTING WITH NEW FIELDS ===" -ForegroundColor Cyan

# Step 1: Login company
Write-Host "`n1. Login company with Cognito..." -ForegroundColor Yellow

try {
    $authResult = aws cognito-idp initiate-auth `
        --region $REGION `
        --auth-flow USER_PASSWORD_AUTH `
        --client-id $CLIENT_ID `
        --auth-parameters "USERNAME=$COMPANY_EMAIL,PASSWORD=$COMPANY_PASSWORD" `
        --output json | ConvertFrom-Json
    
    $companyToken = $authResult.AuthenticationResult.IdToken
    Write-Host "[OK] Login successful" -ForegroundColor Green
} catch {
    Write-Host "[ERROR] Login failed" -ForegroundColor Red
    exit 1
}

# Step 2: Get company ID from token
Write-Host "`n2. Getting company ID from token..." -ForegroundColor Yellow

$tokenParts = $companyToken.Split('.')
$payloadBase64 = $tokenParts[1]

switch ($payloadBase64.Length % 4) {
    2 { $payloadBase64 += "==" }
    3 { $payloadBase64 += "=" }
}

$payload = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($payloadBase64))
$payloadJson = $payload | ConvertFrom-Json
$companyId = $payloadJson.sub

Write-Host "[OK] Company ID: $companyId" -ForegroundColor Green

# Step 3: Create simplified job listing
Write-Host "`n3. Creating job listing: 'Cercatore di Tartufi'..." -ForegroundColor Yellow

$today = (Get-Date).ToString("yyyy-MM-dd")
$endDate = "2026-04-30"

$jobListingBody = @{
    title = "Cercatore di Tartufi - Umbria 2026"
    description = "Ricerca tartufi pregiati nelle colline umbre. Test listing per verificare i nuovi campi vitto, alloggio, minConsecutiveDays, minNoticeDays."
    startDate = $today
    endDate = $endDate
    positions = 2
    category = "tourism"
    
    jobRole = @{
        roleId = "FIPE_L4_016"
        roleName = "Istruttore sportivo"
        category = "animazione"
    }
    
    contract = @{
        contractId = "CCNL#turismo#4"
        ccnlType = "turismo"
        level = "4"
        levelName = "Livello 4"
        description = "Operaio qualificato"
        paragraph = "II"
        calculation = @{
            basePay = 1127.75
            contingencyAllowance = 524.94
            grossBasePay = 1652.69
            calculationDate = (Get-Date).ToString("yyyy-MM-ddTHH:mm:ssZ")
        }
    }
    
    location = @{
        city = "Otranto"
        province = "LE"
        postalCode = "73028"
        country = "IT"
        coordinates = @{
            lat = 40.1434
            lon = 18.4910
        }
    }
    
    schedule = @{
        hoursPerWeek = 40
        workTimeSlots = @(
            @{
                type = "single"
                slots = @(
                    @{
                        start = "09:00"
                        end = "18:00"
                    }
                )
                days = @("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
            }
        )
        workDays = @("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
        notes = "Orario continuato con pausa pranzo"
    }
    
    employment = @{
        typeId = "seasonal"
        typeName = "Stagionale"
        contractDuration = "determinato"
    }
    
    responsibilities = "Insegnare surf, gestire allievi, manutenzione attrezzature"
    requirements = "Esperienza 2 anni, brevetto salvataggio, inglese B2"
    benefits = "Alloggio fornito, ambiente stimolante, surf nel tempo libero"
    
    vitto = $false
    alloggio = $true
    minConsecutiveDays = 7
    minNoticeDays = 3
    
    status = "published"
} | ConvertTo-Json -Depth 10

Write-Host "  NEW FIELDS:" -ForegroundColor Cyan
Write-Host "  - vitto: false (meals NOT provided)" -ForegroundColor Gray
Write-Host "  - alloggio: true (accommodation provided)" -ForegroundColor Gray
Write-Host "  - minConsecutiveDays: 7 (minimum 1 week)" -ForegroundColor Gray
Write-Host "  - minNoticeDays: 3 (book at least 3 days in advance)" -ForegroundColor Gray

$headers = @{
    "Authorization" = "Bearer $companyToken"
}

try {
    $createResponse = Invoke-RestMethod -Uri "$API_JOBLISTINGS/listings" -Method POST -Body $jobListingBody -Headers $headers -ContentType "application/json"
    $listingId = $createResponse.listingId
    Write-Host "[OK] Job listing created successfully!" -ForegroundColor Green
    Write-Host "  Listing ID: $listingId" -ForegroundColor Gray
    
    # Verify new fields
    Write-Host "`n  Verification of new fields:" -ForegroundColor Cyan
    $listing = $createResponse.listing
    
    if ($listing.vitto -eq $false) {
        Write-Host "  [OK] vitto: $($listing.vitto)" -ForegroundColor Green
    } else {
        Write-Host "  [FAIL] vitto: $($listing.vitto)" -ForegroundColor Red
    }
    
    if ($listing.alloggio -eq $true) {
        Write-Host "  [OK] alloggio: $($listing.alloggio)" -ForegroundColor Green
    } else {
        Write-Host "  [FAIL] alloggio: $($listing.alloggio)" -ForegroundColor Red
    }
    
    if ($listing.minConsecutiveDays -eq 7) {
        Write-Host "  [OK] minConsecutiveDays: $($listing.minConsecutiveDays)" -ForegroundColor Green
    } else {
        Write-Host "  [FAIL] minConsecutiveDays: $($listing.minConsecutiveDays)" -ForegroundColor Red
    }
    
    if ($listing.minNoticeDays -eq 3) {
        Write-Host "  [OK] minNoticeDays: $($listing.minNoticeDays)" -ForegroundColor Green
    } else {
        Write-Host "  [FAIL] minNoticeDays: $($listing.minNoticeDays)" -ForegroundColor Red
    }
    
    # Save listing ID for next test
    $listingId | Out-File -FilePath ".\test-listing-id.txt"
    Write-Host "`n  Listing ID saved to test-listing-id.txt" -ForegroundColor Gray
    
} catch {
    Write-Host "[ERROR] Failed to create listing" -ForegroundColor Red
    if ($_.ErrorDetails.Message) {
        $errorDetails = $_.ErrorDetails.Message | ConvertFrom-Json
        Write-Host "  Error: $($errorDetails.error)" -ForegroundColor Red
        Write-Host "  Message: $($errorDetails.message)" -ForegroundColor Red
    }
    exit 1
}

Write-Host "`n=== TEST 2 COMPLETED SUCCESSFULLY ===" -ForegroundColor Green
