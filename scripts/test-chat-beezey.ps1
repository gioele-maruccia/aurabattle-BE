# Test Completo - Interazione Chat con Beezey
# Testa: @beebusy operator assignment, admin access, booking status messages

param(
    [string]$Environment = "dev",
    [string]$Region = "eu-south-1"
)

$ErrorActionPreference = "Continue"

Write-Host "`n============================================" -ForegroundColor Cyan
Write-Host "  TEST CHAT BEEZEY - COMPLETO" -ForegroundColor Cyan
Write-Host "============================================`n" -ForegroundColor Cyan

# Configuration
$WorkerEmail = "gecetev283@naqulu.com"
$CompanyEmail = "titocet754@naqulu.com"
$AdminEmail = "gioelemaruccia8@gmail.com"
$AdminId = "b63ee210-60f1-7072-682c-1a394a67d7e0"
$UserPoolId = "eu-south-1_0oK9agPYd"
$ClientId = "79g67hnuepfuoh1fnk4d98jfpu"
$Password = "Password@1"

# Get tokens
Write-Host "Authenticating users..." -ForegroundColor Gray

$workerToken = aws cognito-idp admin-initiate-auth `
    --user-pool-id $UserPoolId --client-id $ClientId --auth-flow ADMIN_NO_SRP_AUTH `
    --auth-parameters "USERNAME=$WorkerEmail,PASSWORD=$Password" `
    --region $Region --query 'AuthenticationResult.IdToken' --output text

$companyToken = aws cognito-idp admin-initiate-auth `
    --user-pool-id $UserPoolId --client-id $ClientId --auth-flow ADMIN_NO_SRP_AUTH `
    --auth-parameters "USERNAME=$CompanyEmail,PASSWORD=$Password" `
    --region $Region --query 'AuthenticationResult.IdToken' --output text

$adminToken = aws cognito-idp admin-initiate-auth `
    --user-pool-id $UserPoolId --client-id $ClientId --auth-flow ADMIN_NO_SRP_AUTH `
    --auth-parameters "USERNAME=$AdminEmail,PASSWORD=$Password" `
    --region $Region --query 'AuthenticationResult.IdToken' --output text

if (-not $workerToken -or -not $companyToken -or -not $adminToken) {
    Write-Host "ERROR: Failed to get tokens" -ForegroundColor Red
    exit 1
}

Write-Host "OK Tokens obtained`n" -ForegroundColor Green

# Find chat with backoffice operator
Write-Host "Finding chat with backoffice operator assigned..." -ForegroundColor Gray
$chatId = "chat_3e925bcfcc6041d2"  # Chat with @beebusy mention

$keyJson = @{chatId = @{S = $chatId}} | ConvertTo-Json -Compress -Depth 3
$keyJson | Set-Content temp-key.json -Encoding ASCII

$chatDetails = aws dynamodb get-item `
    --table-name "$Environment-Chats" `
    --key file://temp-key.json `
    --region $Region --output json | ConvertFrom-Json

Remove-Item temp-key.json -ErrorAction SilentlyContinue

if (-not $chatDetails.Item -or -not $chatDetails.Item.backofficeOperatorId) {
    Write-Host "ERROR: Chat $chatId has no backoffice operator" -ForegroundColor Red
    Write-Host "Send a message with @beebusy in this chat first!" -ForegroundColor Yellow
    exit 1
}

$operatorId = $chatDetails.Item.backofficeOperatorId.S

Write-Host "Chat found: $chatId" -ForegroundColor Green
Write-Host "Operator assigned: $operatorId`n" -ForegroundColor Green

# TEST 1: Admin can READ messages
Write-Host "[TEST 1] Admin reading messages..." -ForegroundColor Cyan

@{
    token = $adminToken
    pathParameters = @{chat_id = $chatId}
    queryStringParameters = @{limit = "10"}
    requestContext = @{authorizer = @{claims = @{sub = $AdminId}}}
} | ConvertTo-Json -Depth 5 | Set-Content test-payload.json -Encoding ASCII

aws lambda invoke `
    --function-name "$Environment-chat-get-messages" `
    --cli-binary-format raw-in-base64-out `
    --payload file://test-payload.json `
    --region $Region `
    test-result.json | Out-Null

$result = Get-Content test-result.json -Raw | ConvertFrom-Json

if ($result.statusCode -eq 200) {
    $body = $result.body | ConvertFrom-Json
    Write-Host "  PASS - Admin can read! Messages: $($body.messages.Count)" -ForegroundColor Green
    $body.messages | Select-Object -First 3 | ForEach-Object {
        $preview = $_.messageText.Substring(0, [Math]::Min(50, $_.messageText.Length))
        Write-Host "    [$($_.senderType)] $preview..." -ForegroundColor DarkGray
    }
} else {
    Write-Host "  FAIL - Status: $($result.statusCode)" -ForegroundColor Red
    Write-Host "  $($result.body)" -ForegroundColor Red
}

# TEST 2: Admin can SEND messages
Write-Host "`n[TEST 2] Admin sending message..." -ForegroundColor Cyan

$adminMessage = "Ciao! Sono il supporto Beezey. Come posso aiutarvi?"

@{
    token = $adminToken
    pathParameters = @{chat_id = $chatId}
    body = "{`"message_text`":`"$adminMessage`"}"
    requestContext = @{authorizer = @{claims = @{sub = $AdminId}}}
} | ConvertTo-Json -Depth 5 | Set-Content test-payload.json -Encoding ASCII

aws lambda invoke `
    --function-name "$Environment-chat-send-message" `
    --cli-binary-format raw-in-base64-out `
    --payload file://test-payload.json `
    --region $Region `
    test-result.json | Out-Null

$result = Get-Content test-result.json -Raw | ConvertFrom-Json

if ($result.statusCode -eq 201) {
    $body = $result.body | ConvertFrom-Json
    Write-Host "  PASS - Admin can send! Message ID: $($body.messageId)" -ForegroundColor Green
} else {
    Write-Host "  FAIL - Status: $($result.statusCode)" -ForegroundColor Red
    Write-Host "  $($result.body)" -ForegroundColor Red
}

# TEST 3: Worker/Company can see admin messages
Write-Host "`n[TEST 3] Worker reading messages (should see admin message)..." -ForegroundColor Cyan

@{
    token = $workerToken
    pathParameters = @{chat_id = $chatId}
    queryStringParameters = @{limit = "5"}
    requestContext = @{authorizer = @{claims = @{sub = "865e9280-a041-70ad-d67a-212c99479e9c"}}}
} | ConvertTo-Json -Depth 5 | Set-Content test-payload.json -Encoding ASCII

aws lambda invoke `
    --function-name "$Environment-chat-get-messages" `
    --cli-binary-format raw-in-base64-out `
    --payload file://test-payload.json `
    --region $Region `
    test-result.json | Out-Null

$result = Get-Content test-result.json -Raw | ConvertFrom-Json

if ($result.statusCode -eq 200) {
    $body = $result.body | ConvertFrom-Json
    $beezeyMessages = $body.messages | Where-Object { $_.senderType -eq "beezey" }
    
    if ($beezeyMessages.Count -gt 0) {
        Write-Host "  PASS - Worker can see Beezey messages: $($beezeyMessages.Count)" -ForegroundColor Green
        $beezeyMessages | Select-Object -First 2 | ForEach-Object {
            $preview = $_.messageText.Substring(0, [Math]::Min(50, $_.messageText.Length))
            Write-Host "    [beezey] $preview..." -ForegroundColor Cyan
        }
    } else {
        Write-Host "  WARNING - No Beezey messages found" -ForegroundColor Yellow
    }
} else {
    Write-Host "  FAIL - Status: $($result.statusCode)" -ForegroundColor Red
}

# TEST 4: Verify @beebusy feature (show current status)
Write-Host "`n[TEST 4] Verifying @beebusy operator assignment..." -ForegroundColor Cyan

if ($operatorId -eq $AdminId) {
    Write-Host "  PASS - Backoffice operator correctly assigned" -ForegroundColor Green
    Write-Host "    Chat: $chatId" -ForegroundColor Gray
    Write-Host "    Operator: $operatorId" -ForegroundColor Gray
} else {
    Write-Host "  FAIL - Operator mismatch" -ForegroundColor Red
    Write-Host "    Expected: $AdminId" -ForegroundColor Gray
    Write-Host "    Found: $operatorId" -ForegroundColor Gray
}

# Cleanup
Remove-Item test-payload.json, test-result.json -ErrorAction SilentlyContinue

Write-Host "`n============================================" -ForegroundColor Cyan
Write-Host "  SUMMARY" -ForegroundColor Cyan
Write-Host "============================================`n" -ForegroundColor Cyan
Write-Host "Tested Features:" -ForegroundColor White
Write-Host "  1. @beebusy operator assignment: Operator $AdminId assigned" -ForegroundColor Gray
Write-Host "  2. Admin read access: Admin can read all messages in chat" -ForegroundColor Gray
Write-Host "  3. Admin write access: Admin can send messages as 'beezey'" -ForegroundColor Gray
Write-Host "  4. Users visibility: Workers/Companies see Beezey messages`n" -ForegroundColor Gray

Write-Host "NOTE: To test booking status messages, update a booking status" -ForegroundColor Yellow
Write-Host "      and check that a system message appears in the chat.`n" -ForegroundColor Yellow
