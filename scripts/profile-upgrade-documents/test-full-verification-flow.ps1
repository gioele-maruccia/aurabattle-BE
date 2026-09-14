# Full Face Verification Flow Test
# Run from beezey-BE root folder

param(
    [string]$IdCardPath = "",
    [string]$SelfiePath = "",
    [string]$Env = "dev"
)

# Configuration
$API_URLS = @{
    "dev" = "https://b99hejeuca.execute-api.eu-south-1.amazonaws.com/dev"
    "prod" = "https://YOUR_PROD_API.execute-api.eu-south-1.amazonaws.com/prod"
}

$API_BASE_URL = $API_URLS[$Env]

Write-Host ""
Write-Host "========================================"
Write-Host "  Full Face Verification Flow Test"
Write-Host "  Environment: $Env"
Write-Host "========================================"
Write-Host ""

# Load token
$TOKEN = Get-Content -Path ".\scripts\backoffice\jwt-token.txt" -ErrorAction SilentlyContinue
if (-not $TOKEN) {
    Write-Host "Token not found. Run get-cognito-token first."
    $TOKEN = Read-Host "JWT Token"
}

$headers = @{
    "Authorization" = "Bearer $TOKEN"
    "Content-Type" = "application/json"
}

# Check if images are provided
if (-not $IdCardPath -or -not (Test-Path $IdCardPath)) {
    Write-Host ""
    Write-Host "Usage: .\test-full-verification-flow.ps1 -IdCardPath <path> -SelfiePath <path>"
    Write-Host ""
    Write-Host 'Example: .\test-full-verification-flow.ps1 -IdCardPath "C:\id.jpg" -SelfiePath "C:\selfie.jpg"'
    Write-Host ""
    
    $testChoice = Read-Host "Test with sample base64 image? (y/n)"
    if ($testChoice -ne "y") {
        exit 0
    }
    
    # Tiny valid JPEG for testing (1x1 white pixel)
    $sampleJpegBase64 = "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAAMCAgMCAgMDAwMEAwMEBQgFBQQEBQoHBwYIDAoMCwsKCwsNDhIQDQ4RDgsLEBYQERMUFRUVDA8XGBYUGBIUFRT/2wBDAQMEBAUEBQkFBQkUDQsNFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBT/wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAn/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFQEBAQAAAAAAAAAAAAAAAAAAAAX/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIRAxEAPwCwAB//2Q=="
    
    Write-Host ""
    Write-Host "Testing with minimal sample image..."
    Write-Host "Note: This image will not pass face detection but tests API connectivity"
    
    $body = @{
        selfie_base64 = $sampleJpegBase64
    } | ConvertTo-Json
    
    Write-Host ""
    Write-Host "Calling verify-face API..."
    try {
        $response = Invoke-RestMethod -Uri "$API_BASE_URL/documents/verify-face" -Method POST -Headers $headers -Body $body
        Write-Host "Response: $($response | ConvertTo-Json -Depth 5)"
    } catch {
        $statusCode = $_.Exception.Response.StatusCode.value__
        try {
            $errorResponse = $_.ErrorDetails.Message | ConvertFrom-Json
            Write-Host "Status: $statusCode"
            Write-Host "Response: $($errorResponse | ConvertTo-Json -Depth 5)"
            
            if ($errorResponse.error_code -eq "FACE_NOT_DETECTED") {
                Write-Host ""
                Write-Host "API is working correctly! (No face in sample image is expected)" -ForegroundColor Green
            } elseif ($errorResponse.error_code -eq "ID_CARD_NOT_FOUND") {
                Write-Host ""
                Write-Host "API is working! Face detected but no ID card uploaded yet." -ForegroundColor Green
                Write-Host "To complete the test, upload an id_card_front first."
            }
        } catch {
            Write-Host "Raw error: $($_.ErrorDetails.Message)" -ForegroundColor Red
        }
    }
    
    exit 0
}

if (-not $SelfiePath -or -not (Test-Path $SelfiePath)) {
    Write-Host "Selfie image not found: $SelfiePath" -ForegroundColor Red
    exit 1
}

# STEP 1: Upload ID Card Front
Write-Host "STEP 1: Uploading ID Card Front" -ForegroundColor Cyan

$presignBody = @{
    doc_type = "id_card_front"
    content_type = "image/jpeg"
} | ConvertTo-Json

Write-Host "   Getting presigned URL..."
try {
    $presignResponse = Invoke-RestMethod -Uri "$API_BASE_URL/documents/upload-url" -Method POST -Headers $headers -Body $presignBody
    Write-Host "   Got presigned URL" -ForegroundColor Green
    $uploadUrl = $presignResponse.upload_url
    $s3Key = $presignResponse.s3_key
} catch {
    Write-Host "   Failed to get presigned URL: $($_.ErrorDetails.Message)" -ForegroundColor Red
    exit 1
}

Write-Host "   Uploading to S3..."
$idCardBytes = [System.IO.File]::ReadAllBytes($IdCardPath)
$uploadHeaders = @{
    "Content-Type" = "image/jpeg"
    "x-amz-server-side-encryption" = "aws:kms"
}

try {
    Invoke-RestMethod -Uri $uploadUrl -Method PUT -Body $idCardBytes -Headers $uploadHeaders
    Write-Host "   ID Card uploaded successfully" -ForegroundColor Green
} catch {
    Write-Host "   Failed to upload: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

Write-Host "   Waiting for S3 processing..."
Start-Sleep -Seconds 2

# STEP 2: Verify Face with Selfie
Write-Host ""
Write-Host "STEP 2: Verifying Face with Selfie" -ForegroundColor Cyan

$selfieBytes = [System.IO.File]::ReadAllBytes($SelfiePath)
$selfieBase64 = [Convert]::ToBase64String($selfieBytes)

Write-Host "   Selfie size: $([math]::Round($selfieBytes.Length / 1024, 2)) KB"

$verifyBody = @{
    selfie_base64 = $selfieBase64
} | ConvertTo-Json

Write-Host "   Calling verify-face API..."
try {
    $verifyResponse = Invoke-RestMethod -Uri "$API_BASE_URL/documents/verify-face" -Method POST -Headers $headers -Body $verifyBody -MaximumBodyLength ([int]::MaxValue)
    
    Write-Host ""
    Write-Host "========================================"
    Write-Host "  VERIFICATION SUCCESSFUL!" -ForegroundColor Green
    Write-Host "========================================"
    Write-Host ""
    Write-Host "Result:"
    Write-Host "  Face Detected: $($verifyResponse.verification.face_detected)"
    Write-Host "  Face Confidence: $($verifyResponse.verification.face_confidence)%"
    Write-Host "  Face Match: $($verifyResponse.verification.face_match)"
    Write-Host "  Similarity: $($verifyResponse.verification.similarity)%" -ForegroundColor Cyan
    Write-Host "  Quality Check: $($verifyResponse.verification.quality_check)"
    Write-Host ""
    Write-Host $verifyResponse.message
    
} catch {
    $statusCode = $_.Exception.Response.StatusCode.value__
    try {
        $errorResponse = $_.ErrorDetails.Message | ConvertFrom-Json
        
        Write-Host ""
        Write-Host "========================================"
        Write-Host "  VERIFICATION FAILED" -ForegroundColor Red
        Write-Host "========================================"
        Write-Host ""
        Write-Host "Error Code: $($errorResponse.error_code)" -ForegroundColor Yellow
        Write-Host "Message: $($errorResponse.message)"
        
        if ($errorResponse.details) {
            Write-Host ""
            Write-Host "Details:"
            Write-Host ($errorResponse.details | ConvertTo-Json -Depth 3)
        }
        
        switch ($errorResponse.error_code) {
            "FACE_NOT_DETECTED" {
                Write-Host ""
                Write-Host "Suggestion: Make sure the selfie clearly shows your face" -ForegroundColor Yellow
            }
            "FACE_MISMATCH" {
                Write-Host ""
                Write-Host "Suggestion: The selfie does not match the ID card photo." -ForegroundColor Yellow
            }
            "QUALITY_CHECK_FAILED" {
                Write-Host ""
                Write-Host "Suggestion: Try with better lighting or a clearer image" -ForegroundColor Yellow
            }
            "NO_FACE_IN_DOCUMENT" {
                Write-Host ""
                Write-Host "Suggestion: The ID card needs a clearer face photo." -ForegroundColor Yellow
            }
        }
    } catch {
        Write-Host "Raw error: $($_.ErrorDetails.Message)" -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "========================================"
Write-Host "  Test Complete"
Write-Host "========================================"
Write-Host ""
