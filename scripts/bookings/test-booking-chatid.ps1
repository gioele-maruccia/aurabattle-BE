# Test Booking Creation with ChatID
# This script tests if the create-booking endpoint returns chatId

$LISTING_ID = "8fcf0256-e3c2-48fa-8885-0a5234919662"
$API_URL = "https://ybagxg3ni3.execute-api.eu-south-1.amazonaws.com/dev/bookings"
$REGION = "eu-south-1"

Write-Host "=== Test Booking Creation with ChatID ===" -ForegroundColor Cyan
Write-Host ""

# Get a valid worker token (you need to replace with actual worker credentials)
Write-Host "NOTE: You need to provide a valid worker JWT token" -ForegroundColor Yellow
Write-Host "Get it from Cognito or use an existing one from your frontend tests" -ForegroundColor Yellow
Write-Host ""

$TOKEN = Read-Host "Enter Worker JWT Token"

if ([string]::IsNullOrWhiteSpace($TOKEN)) {
    Write-Host "ERROR: Token is required!" -ForegroundColor Red
    exit 1
}

# Prepare booking payload
$startDate = (Get-Date).AddDays(10).ToString("yyyy-MM-dd")
$endDate = (Get-Date).AddDays(15).ToString("yyyy-MM-dd")

$body = @{
    listingId = $LISTING_ID
    startDate = $startDate
    endDate = $endDate
    notes = "Test booking to verify chatId in response"
} | ConvertTo-Json

Write-Host "Creating booking for listing: $LISTING_ID" -ForegroundColor Green
Write-Host "Start date: $startDate"
Write-Host "End date: $endDate"
Write-Host ""

# Call API
try {
    $response = Invoke-RestMethod -Uri $API_URL -Method POST `
        -Headers @{
            "Authorization" = "Bearer $TOKEN"
            "Content-Type" = "application/json"
        } `
        -Body $body
    
    Write-Host "SUCCESS! Booking created" -ForegroundColor Green
    Write-Host ""
    Write-Host "=== RESPONSE ===" -ForegroundColor Cyan
    $response | ConvertTo-Json -Depth 10
    Write-Host ""
    
    # Check if chatId is present
    if ($response.chatId) {
        Write-Host "✓ chatId found: $($response.chatId)" -ForegroundColor Green
        Write-Host "✓ chatCreated: $($response.chatCreated)" -ForegroundColor Green
    } else {
        Write-Host "✗ chatId NOT found in response!" -ForegroundColor Red
        Write-Host "This is the issue the frontend is experiencing" -ForegroundColor Yellow
    }
    
} catch {
    Write-Host "ERROR calling API:" -ForegroundColor Red
    Write-Host $_.Exception.Message
    Write-Host ""
    
    # Show Lambda logs
    Write-Host "Checking Lambda logs for details..." -ForegroundColor Yellow
    aws logs tail "/aws/lambda/dev-bookings-create" --region $REGION --since 5m --format short
}

Write-Host ""
Write-Host "=== Checking Lambda Logs ===" -ForegroundColor Cyan
aws logs tail "/aws/lambda/dev-bookings-create" --region $REGION --since 5m --format short
