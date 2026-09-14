# Test script for Face Verification API
# Run from beezey-BE root folder

# Load token from file or set manually
$TOKEN = Get-Content -Path ".\scripts\backoffice\jwt-token.txt" -ErrorAction SilentlyContinue
if (-not $TOKEN) {
    Write-Host "Token not found. Set your JWT token:" -ForegroundColor Yellow
    $TOKEN = Read-Host "JWT Token"
}

# API Configuration
$API_BASE_URL = "https://b99hejeuca.execute-api.eu-south-1.amazonaws.com/dev"
$ENDPOINT = "$API_BASE_URL/documents/verify-face"

# Headers
$headers = @{
    "Authorization" = "Bearer $TOKEN"
    "Content-Type" = "application/json"
}

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "  Face Verification API Test" -ForegroundColor Cyan
Write-Host "========================================`n" -ForegroundColor Cyan

# Test 1: Missing selfie
Write-Host "Test 1: Missing selfie parameter" -ForegroundColor Yellow
$body = @{} | ConvertTo-Json
try {
    $response = Invoke-RestMethod -Uri $ENDPOINT -Method POST -Headers $headers -Body $body -ErrorAction Stop
    Write-Host "Unexpected success: $($response | ConvertTo-Json)" -ForegroundColor Red
} catch {
    $errorResponse = $_.ErrorDetails.Message | ConvertFrom-Json
    if ($errorResponse.error_code -eq "MISSING_SELFIE") {
        Write-Host "✅ Correctly returned MISSING_SELFIE error" -ForegroundColor Green
    } else {
        Write-Host "❌ Wrong error: $($errorResponse | ConvertTo-Json)" -ForegroundColor Red
    }
}

Write-Host ""

# Test 2: Invalid base64
Write-Host "Test 2: Invalid base64 image" -ForegroundColor Yellow
$body = @{
    selfie_base64 = "not-valid-base64!!!"
} | ConvertTo-Json

try {
    $response = Invoke-RestMethod -Uri $ENDPOINT -Method POST -Headers $headers -Body $body -ErrorAction Stop
    Write-Host "Unexpected success: $($response | ConvertTo-Json)" -ForegroundColor Red
} catch {
    $errorResponse = $_.ErrorDetails.Message | ConvertFrom-Json
    if ($errorResponse.error_code -eq "INVALID_BASE64") {
        Write-Host "✅ Correctly returned INVALID_BASE64 error" -ForegroundColor Green
    } else {
        Write-Host "Response: $($errorResponse | ConvertTo-Json)" -ForegroundColor Yellow
    }
}

Write-Host ""

# Test 3: Valid image (you need to provide a real test image)
Write-Host "Test 3: With real selfie image" -ForegroundColor Yellow
$TEST_IMAGE_PATH = ".\test-selfie.jpg"

if (Test-Path $TEST_IMAGE_PATH) {
    $imageBytes = [System.IO.File]::ReadAllBytes($TEST_IMAGE_PATH)
    $base64Image = [Convert]::ToBase64String($imageBytes)
    
    $body = @{
        selfie_base64 = $base64Image
    } | ConvertTo-Json
    
    Write-Host "Sending image ($(($imageBytes.Length / 1024).ToString('F2')) KB)..." -ForegroundColor Cyan
    
    try {
        $response = Invoke-RestMethod -Uri $ENDPOINT -Method POST -Headers $headers -Body $body -ErrorAction Stop
        
        if ($response.success) {
            Write-Host "✅ Verification successful!" -ForegroundColor Green
            Write-Host "   Similarity: $($response.verification.similarity)%" -ForegroundColor Green
            Write-Host "   Face Confidence: $($response.verification.face_confidence)%" -ForegroundColor Green
        } else {
            Write-Host "Verification failed: $($response.message)" -ForegroundColor Red
        }
    } catch {
        $statusCode = $_.Exception.Response.StatusCode.value__
        $errorResponse = $_.ErrorDetails.Message | ConvertFrom-Json
        Write-Host "Error ($statusCode): $($errorResponse.error_code)" -ForegroundColor Red
        Write-Host "Message: $($errorResponse.message)" -ForegroundColor Yellow
        
        if ($errorResponse.details) {
            Write-Host "Details: $($errorResponse.details | ConvertTo-Json)" -ForegroundColor Gray
        }
    }
} else {
    Write-Host "⚠️ No test image found at $TEST_IMAGE_PATH" -ForegroundColor Yellow
    Write-Host "   Place a selfie image there to test with real data" -ForegroundColor Yellow
}

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "  Test Complete" -ForegroundColor Cyan
Write-Host "========================================`n" -ForegroundColor Cyan
