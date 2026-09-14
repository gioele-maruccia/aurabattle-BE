$username = 'titocet754@naqulu.com'
$password = 'Password@1'
$clientId = '79g67hnuepfuoh1fnk4d98jfpu'
$region = 'eu-south-1'

Write-Host "=== Testing Chat GET ===" -ForegroundColor Cyan
Write-Host "Username: $username"
Write-Host ""

# Ottieni token
Write-Host "1. Authenticating with Cognito..." -ForegroundColor Yellow
$authResponse = aws cognito-idp initiate-auth `
    --auth-flow USER_PASSWORD_AUTH `
    --client-id $clientId `
    --auth-parameters "USERNAME=$username,PASSWORD=$password" `
    --region $region 2>&1

if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Cognito authentication failed" -ForegroundColor Red
    Write-Host $authResponse
    exit 1
}

$authJson = $authResponse | ConvertFrom-Json
$token = $authJson.AuthenticationResult.IdToken

Write-Host "[OK] Token ottenuto" -ForegroundColor Green
Write-Host "Token preview: $($token.Substring(0, 50))..."
Write-Host ""

# Test GET /chats
Write-Host "2. Testing GET /chats..." -ForegroundColor Yellow
$headers = @{
    "Authorization" = "Bearer $token"
    "Content-Type"  = "application/json"
}

$chatsResponse = Invoke-WebRequest `
    -Uri "https://57s2xhuuo4.execute-api.eu-south-1.amazonaws.com/dev/chats" `
    -Method GET `
    -Headers $headers `
    -ErrorAction Stop

Write-Host "[OK] Response received (Status: $($chatsResponse.StatusCode))" -ForegroundColor Green
Write-Host ""

$chatsData = $chatsResponse.Content | ConvertFrom-Json
Write-Host "Response JSON:" -ForegroundColor Cyan
$chatsData | ConvertTo-Json -Depth 5

Write-Host ""
Write-Host "Number of chats: $($chatsData.chats.Count)" -ForegroundColor Green

if ($chatsData.chats -and $chatsData.chats.Count -gt 0) {
    Write-Host ""
    Write-Host "Chats found:" -ForegroundColor Cyan
    foreach ($chat in $chatsData.chats) {
        Write-Host "  - Chat ID: $($chat.chatId)"
        Write-Host "    Booking ID: $($chat.bookingId)"
        Write-Host "    Status: $($chat.status)"
        Write-Host "    Last message: $($chat.lastMessage)"
        Write-Host ""
    }
}
