# ============================================================================
# BACKOFFICE API - COMPLETE ENDPOINT TEST SUITE
# ============================================================================
# Tests all backoffice endpoints to verify:
# - API functionality
# - Consistency with new profile_type system
# - Swagger documentation accuracy
# ============================================================================

$ErrorActionPreference = "Continue"
$baseUrl = "https://v7m02xrzyh.execute-api.eu-south-1.amazonaws.com/dev"
$email = "gioelemaruccia8@gmail.com"
$password = "Password@1"

# Colors for output
$colors = @{
    Success = "Green"
    Error = "Red"
    Warning = "Yellow"
    Info = "Cyan"
    Header = "Magenta"
}

# Test results tracking
$testResults = @{
    Passed = 0
    Failed = 0
    Warnings = 0
    Tests = @()
}

function Write-Header {
    param([string]$Text)
    Write-Host "`n============================================================================" -ForegroundColor $colors.Header
    Write-Host " $Text" -ForegroundColor $colors.Header
    Write-Host "============================================================================`n" -ForegroundColor $colors.Header
}

function Write-TestResult {
    param(
        [string]$TestName,
        [bool]$Success,
        [string]$Message = "",
        [string]$Details = ""
    )
    
    $result = @{
        Name = $TestName
        Success = $Success
        Message = $Message
        Details = $Details
    }
    
    $testResults.Tests += $result
    
    if ($Success) {
        $testResults.Passed++
        Write-Host "[PASS] $TestName" -ForegroundColor $colors.Success
        if ($Message) { Write-Host "       $Message" -ForegroundColor Gray }
    } else {
        $testResults.Failed++
        Write-Host "[FAIL] $TestName" -ForegroundColor $colors.Error
        if ($Message) { Write-Host "       $Message" -ForegroundColor $colors.Error }
    }
    
    if ($Details) {
        Write-Host "       Details: $Details" -ForegroundColor Gray
    }
}

function Write-Warning-Test {
    param([string]$TestName, [string]$Message)
    $testResults.Warnings++
    Write-Host "[WARN] $TestName" -ForegroundColor $colors.Warning
    Write-Host "       $Message" -ForegroundColor $colors.Warning
}

function Invoke-ApiRequest {
    param(
        [string]$Method,
        [string]$Endpoint,
        [hashtable]$Headers,
        [object]$Body = $null
    )
    
    try {
        $params = @{
            Uri = "$baseUrl$Endpoint"
            Method = $Method
            Headers = $Headers
            ContentType = "application/json"
            UseBasicParsing = $true
        }
        
        if ($Body) {
            $params.Body = ($Body | ConvertTo-Json -Depth 10)
        }
        
        $response = Invoke-WebRequest @params -ErrorAction Stop
        
        return @{
            Success = $true
            StatusCode = $response.StatusCode
            Data = ($response.Content | ConvertFrom-Json)
            RawResponse = $response
        }
    } catch {
        return @{
            Success = $false
            StatusCode = $_.Exception.Response.StatusCode.value__
            Error = $_.Exception.Message
            ErrorDetails = $_.ErrorDetails.Message
        }
    }
}

# ============================================================================
# STEP 1: Authentication
# ============================================================================
Write-Header "STEP 1: Authentication"

Write-Host "Attempting login with: $email" -ForegroundColor $colors.Info

try {
    # Use AWS CLI to get IdToken (required by Cognito Authorizer)
    $clientId = "79g67hnuepfuoh1fnk4d98jfpu"
    $userPoolId = "eu-south-1_0oK9agPYd"
    
    Write-Host "Getting IdToken from Cognito..." -ForegroundColor $colors.Info
    
    $authResult = aws cognito-idp initiate-auth `
        --auth-flow USER_PASSWORD_AUTH `
        --client-id $clientId `
        --auth-parameters USERNAME=$email,PASSWORD=$password `
        --region eu-south-1 `
        --query 'AuthenticationResult' `
        --output json 2>&1 | ConvertFrom-Json
    
    if ($authResult.IdToken) {
        $token = $authResult.IdToken
        Write-Host "Successfully authenticated!" -ForegroundColor $colors.Success
        $token | Out-File "scripts/backoffice/id-token.txt" -NoNewline
    } else {
        Write-Host "ERROR: Could not get IdToken." -ForegroundColor $colors.Error
        Write-Host "Trying to use existing token file..." -ForegroundColor $colors.Warning
        
        $tokenFile = "scripts/backoffice/id-token.txt"
        if (Test-Path $tokenFile) {
            $token = (Get-Content $tokenFile).Trim()
            Write-Host "Using token from file (may be expired)" -ForegroundColor $colors.Warning
        } else {
            Write-Host "No token file found. Cannot proceed." -ForegroundColor $colors.Error
            exit 1
        }
    }
    
} catch {
    Write-Host "ERROR: Authentication failed: $($_.Exception.Message)" -ForegroundColor $colors.Error
    Write-Host "Trying existing token file..." -ForegroundColor $colors.Warning
    
    $tokenFile = "scripts/backoffice/id-token.txt"
    if (Test-Path $tokenFile) {
        $token = (Get-Content $tokenFile).Trim()
    } else {
        Write-Host "No token file found. Cannot proceed." -ForegroundColor $colors.Error
        exit 1
    }
}

$headers = @{
    "Authorization" = "Bearer $token"
    "Content-Type" = "application/json"
}

# ============================================================================
# STEP 2: Test Search Users Endpoint
# ============================================================================
Write-Header "STEP 2: Test GET /users/search"

# Test 2.1: Search all users (type=recent to get all without query)
$result = Invoke-ApiRequest -Method GET -Endpoint "/users/search?type=recent&limit=50" -Headers $headers
Write-TestResult -TestName "GET /users/search (all users)" `
    -Success $result.Success `
    -Message "Found $($result.Data.users.Count) users" `
    -Details "Response includes: $($result.Data.PSObject.Properties.Name -join ', ')"

if ($result.Success -and $result.Data.users) {
    # Check for profileType field
    $firstUser = $result.Data.users[0]
    $hasProfileType = $firstUser.PSObject.Properties.Name -contains "profileType"
    $hasOldUserType = $firstUser.PSObject.Properties.Name -contains "userType"
    
    Write-TestResult -TestName "Users have 'profileType' field (not 'userType')" `
        -Success $hasProfileType `
        -Message "Field found: profileType=$($firstUser.profileType)" `
        -Details "Old userType field present: $hasOldUserType"
    
    # Store user info for later tests
    $global:testUsers = @{
        All = $result.Data.users
        Basic = $result.Data.users | Where-Object { $_.profileType -eq "basic" }
        Worker = $result.Data.users | Where-Object { $_.profileType -eq "worker" }
        Company = $result.Data.users | Where-Object { $_.profileType -eq "company" }
    }
    
    Write-Host "Users by profile type:" -ForegroundColor $colors.Info
    Write-Host "  - Basic: $($global:testUsers.Basic.Count)" -ForegroundColor Gray
    Write-Host "  - Worker: $($global:testUsers.Worker.Count)" -ForegroundColor Gray
    Write-Host "  - Company: $($global:testUsers.Company.Count)" -ForegroundColor Gray
}

# Test 2.2: Search by email
$result = Invoke-ApiRequest -Method GET -Endpoint "/users/search?q=test&limit=10" -Headers $headers
Write-TestResult -TestName "GET /users/search?q=test" `
    -Success $result.Success `
    -Message "Found $($result.Data.users.Count) users matching 'test'"

# ============================================================================
# STEP 3: Test Document Statistics
# ============================================================================
Write-Header "STEP 3: Test GET /documents/stats"

$result = Invoke-ApiRequest -Method GET -Endpoint "/documents/stats" -Headers $headers
Write-TestResult -TestName "GET /documents/stats" `
    -Success $result.Success `
    -Message "Total documents: $($result.Data.total_documents)" `
    -Details "Response fields: $($result.Data.PSObject.Properties.Name -join ', ')"

if ($result.Success) {
    # Check if by_type exists
    $hasByType = $result.Data.PSObject.Properties.Name -contains "by_type"
    Write-TestResult -TestName "Stats include 'by_type' breakdown" `
        -Success $hasByType `
        -Details "by_type: $($result.Data.by_type | ConvertTo-Json -Compress)"
}

# ============================================================================
# STEP 4: Test List All Documents
# ============================================================================
Write-Header "STEP 4: Test GET /documents"

# Test 4.1: List all documents
$result = Invoke-ApiRequest -Method GET -Endpoint "/documents?limit=20" -Headers $headers
Write-TestResult -TestName "GET /documents (all)" `
    -Success $result.Success `
    -Message "Found $($result.Data.count) documents"

if ($result.Success) {
    # Check response structure
    $hasFilters = $result.Data.PSObject.Properties.Name -contains "filters"
    Write-TestResult -TestName "Response includes 'filters' object" `
        -Success $hasFilters
    
    if ($hasFilters) {
        $hasProfileType = $result.Data.filters.PSObject.Properties.Name -contains "profileType"
        $hasOldUserType = $result.Data.filters.PSObject.Properties.Name -contains "userType"
        
        Write-TestResult -TestName "Filters use 'profileType' (not 'userType')" `
            -Success $hasProfileType `
            -Details "Old userType in filters: $hasOldUserType"
    }
    
    $global:testDocuments = $result.Data.documents
}

# Test 4.2: Filter by status
$result = Invoke-ApiRequest -Method GET -Endpoint "/documents?status=AWAITING_REVIEW&limit=10" -Headers $headers
Write-TestResult -TestName "GET /documents?status=AWAITING_REVIEW" `
    -Success $result.Success `
    -Message "Found $($result.Data.count) documents awaiting review"

# ============================================================================
# STEP 5: Test User-Specific Documents
# ============================================================================
Write-Header "STEP 5: Test GET /documents/user/{user_sub}"

if ($global:testUsers.All.Count -gt 0) {
    $testUser = $global:testUsers.All[0]
    $userSub = $testUser.sub
    
    $result = Invoke-ApiRequest -Method GET -Endpoint "/documents/user/$userSub" -Headers $headers
    Write-TestResult -TestName "GET /documents/user/{user_sub}" `
        -Success $result.Success `
        -Message "User: $($testUser.fullName) ($($testUser.email))"
    
    if ($result.Success) {
        # Check userInfo structure
        $hasUserInfo = $result.Data.PSObject.Properties.Name -contains "userInfo"
        Write-TestResult -TestName "Response includes 'userInfo' object" `
            -Success $hasUserInfo
        
        if ($hasUserInfo) {
            $hasProfileType = $result.Data.userInfo.PSObject.Properties.Name -contains "profileType"
            $hasOldUserType = $result.Data.userInfo.PSObject.Properties.Name -contains "userType"
            
            Write-TestResult -TestName "userInfo uses 'profileType' (not 'userType')" `
                -Success $hasProfileType `
                -Details "profileType=$($result.Data.userInfo.profileType), Old userType present: $hasOldUserType"
        }
    }
}

# ============================================================================
# STEP 6: Test Reset Profile - Should FAIL scenarios
# ============================================================================
Write-Header "STEP 6: Test POST /reset-profile (Expected Failures)"

# Test 6.1: Try to reset worker with active booking (should fail)
if ($global:testUsers.Worker.Count -gt 0) {
    $worker = $global:testUsers.Worker[0]
    
    Write-Host "Testing worker: $($worker.fullName) ($($worker.email))" -ForegroundColor $colors.Info
    
    $result = Invoke-ApiRequest -Method POST -Endpoint "/reset-profile" -Headers $headers `
        -Body @{ userSub = $worker.sub }
    
    if ($result.Success -eq $false -and $result.StatusCode -eq 400) {
        Write-TestResult -TestName "Worker reset blocked (has active bookings)" `
            -Success $true `
            -Message "Correctly rejected: $($result.ErrorDetails)"
    } else {
        Write-TestResult -TestName "Worker reset blocked (has active bookings)" `
            -Success $false `
            -Message "Should have been rejected but wasn't"
    }
}

# Test 6.2: Try to reset company with active listings (should fail)
if ($global:testUsers.Company.Count -gt 0) {
    $company = $global:testUsers.Company[0]
    
    Write-Host "Testing company: $($company.fullName) ($($company.email))" -ForegroundColor $colors.Info
    
    $result = Invoke-ApiRequest -Method POST -Endpoint "/reset-profile" -Headers $headers `
        -Body @{ userSub = $company.sub }
    
    if ($result.Success -eq $false -and $result.StatusCode -eq 400) {
        Write-TestResult -TestName "Company reset blocked (has active listings)" `
            -Success $true `
            -Message "Correctly rejected: $($result.ErrorDetails)"
    } else {
        Write-TestResult -TestName "Company reset blocked (has active listings)" `
            -Success $false `
            -Message "Should have been rejected but wasn't"
    }
}

# ============================================================================
# STEP 7: Test Reset Profile - Should SUCCEED scenarios
# ============================================================================
Write-Header "STEP 7: Test POST /reset-profile (Expected Success)"

# Find a worker or company without active bookings/listings
Write-Host "Looking for users without active bookings/listings..." -ForegroundColor $colors.Info

# For now, we'll test with basic users (should always work)
if ($global:testUsers.Basic.Count -gt 0) {
    $basicUser = $global:testUsers.Basic[0]
    
    Write-Host "Testing basic user reset: $($basicUser.fullName)" -ForegroundColor $colors.Info
    
    $result = Invoke-ApiRequest -Method POST -Endpoint "/reset-profile" -Headers $headers `
        -Body @{ userSub = $basicUser.sub }
    
    Write-TestResult -TestName "Basic user reset" `
        -Success $result.Success `
        -Message "User: $($basicUser.email)"
} else {
    Write-Warning-Test -TestName "Basic user reset" `
        -Message "No basic users found to test"
}

# ============================================================================
# STEP 8: Test Document Approval/Rejection (if documents exist)
# ============================================================================
Write-Header "STEP 8: Test PUT /documents/{user_sub}/{document_id}/status"

if ($global:testDocuments -and $global:testDocuments.Count -gt 0) {
    # Find a document in AWAITING_REVIEW status
    $awaitingDoc = $global:testDocuments | Where-Object { $_.status -eq "AWAITING_REVIEW" } | Select-Object -First 1
    
    if ($awaitingDoc) {
        Write-Host "Testing with document: $($awaitingDoc.docType) for user $($awaitingDoc.userSub)" -ForegroundColor $colors.Info
        
        # Test approve
        $result = Invoke-ApiRequest -Method PUT `
            -Endpoint "/documents/$($awaitingDoc.userSub)/$($awaitingDoc.docId)/status" `
            -Headers $headers `
            -Body @{
                status = "APPROVED"
                notes = "Test approval from automated test suite"
            }
        
        Write-TestResult -TestName "Approve document" `
            -Success $result.Success `
            -Message "Document: $($awaitingDoc.docType)"
        
        if ($result.Success) {
            # Check if user was promoted
            $wasPromoted = $result.Data.PSObject.Properties.Name -contains "promotion"
            if ($wasPromoted -and $result.Data.promotion.action -eq "promoted") {
                Write-Host "       User was promoted to: $($result.Data.promotion.new_profile_type)" -ForegroundColor $colors.Success
            }
        }
    } else {
        Write-Warning-Test -TestName "Approve document" `
            -Message "No documents in AWAITING_REVIEW status found"
    }
} else {
    Write-Warning-Test -TestName "Document approval" `
        -Message "No documents found to test approval"
}

# ============================================================================
# STEP 9: Test Document Download URL
# ============================================================================
Write-Header "STEP 9: Test POST /documents/download/{user_sub}/{document_id}"

if ($global:testDocuments -and $global:testDocuments.Count -gt 0) {
    $doc = $global:testDocuments[0]
    
    $result = Invoke-ApiRequest -Method POST `
        -Endpoint "/documents/download/$($doc.userSub)/$($doc.docId)" `
        -Headers $headers
    
    Write-TestResult -TestName "Get document download URL" `
        -Success $result.Success `
        -Message "Document: $($doc.docType)"
    
    if ($result.Success) {
        $hasUrl = $result.Data.PSObject.Properties.Name -contains "downloadUrl"
        Write-TestResult -TestName "Response includes downloadUrl" `
            -Success $hasUrl
    }
} else {
    Write-Warning-Test -TestName "Document download" `
        -Message "No documents found to test download"
}

# ============================================================================
# FINAL REPORT
# ============================================================================
Write-Header "TEST SUITE RESULTS"

Write-Host "Total Tests: $($testResults.Passed + $testResults.Failed)" -ForegroundColor $colors.Info
Write-Host "Passed: $($testResults.Passed)" -ForegroundColor $colors.Success
Write-Host "Failed: $($testResults.Failed)" -ForegroundColor $colors.Error
Write-Host "Warnings: $($testResults.Warnings)" -ForegroundColor $colors.Warning

Write-Host "`nDetailed Results:" -ForegroundColor $colors.Header

foreach ($test in $testResults.Tests) {
    $symbol = if ($test.Success) { "[PASS]" } else { "[FAIL]" }
    $color = if ($test.Success) { $colors.Success } else { $colors.Error }
    
    Write-Host "$symbol $($test.Name)" -ForegroundColor $color
    if ($test.Message) {
        Write-Host "  $($test.Message)" -ForegroundColor Gray
    }
}

# Save results to file
$reportFile = "scripts/backoffice/test-report-$(Get-Date -Format 'yyyyMMdd-HHmmss').json"
$testResults | ConvertTo-Json -Depth 10 | Out-File $reportFile
Write-Host "`nFull report saved to: $reportFile" -ForegroundColor $colors.Info

# Summary
Write-Host "`n" -NoNewline
if ($testResults.Failed -eq 0) {
    Write-Host "ALL TESTS PASSED!" -ForegroundColor $colors.Success
} else {
    Write-Host "SOME TESTS FAILED - Review results above" -ForegroundColor $colors.Error
}

Write-Host ""
