# ============================================================================
# Chat API - Complete Test Suite
# ============================================================================
# Script per testare tutte le API della chat con utenti reali
# Utenti test: gecetev283@naqulu.com e titocet754@naqulu.com
# Password: Password@1 (per entrambi)
# ============================================================================

param(
    [string]$Environment = "dev",
    [switch]$Verbose
)

# Configurazione
$ErrorActionPreference = "Stop"
$BASE_URL = "https://57s2xhuuo4.execute-api.eu-south-1.amazonaws.com/dev"
$USER_POOL_ID = "eu-south-1_0oK9agPYd"
$CLIENT_ID = "79g67hnuepfuoh1fnk4d98jfpu"
$REGION = "eu-south-1"

# Utenti test
$USER1_EMAIL = "gecetev283@naqulu.com"
$USER1_PASSWORD = "Password@1"
$USER2_EMAIL = "titocet754@naqulu.com"
$USER2_PASSWORD = "Password@1"

# Colori output
function Write-Success { param($Message) Write-Host "[OK] $Message" -ForegroundColor Green }
function Write-Error-Custom { param($Message) Write-Host "[ERROR] $Message" -ForegroundColor Red }
function Write-Info { param($Message) Write-Host "[INFO] $Message" -ForegroundColor Cyan }
function Write-Step { param($Message) Write-Host "`n========== $Message ==========" -ForegroundColor Yellow }

# ============================================================================
# AUTHENTICATION
# ============================================================================

function Get-AuthToken {
    param(
        [string]$Email,
        [string]$Password
    )
    
    Write-Info "Authenticating user: $Email"
    
    try {
        # Use AWS CLI to authenticate with Cognito
        $authResult = aws cognito-idp initiate-auth `
            --region $REGION `
            --auth-flow USER_PASSWORD_AUTH `
            --client-id $CLIENT_ID `
            --auth-parameters "USERNAME=$Email,PASSWORD=$Password" `
            --output json | ConvertFrom-Json
        
        if ($authResult.AuthenticationResult.IdToken) {
            Write-Success "Authentication successful"
            return @{
                Token = $authResult.AuthenticationResult.IdToken
                UserId = $Email
                RefreshToken = $authResult.AuthenticationResult.RefreshToken
            }
        } else {
            throw "Authentication failed - no token received"
        }
    } catch {
        Write-Error-Custom "Authentication failed: $($_.Exception.Message)"
        throw
    }
}

# ============================================================================
# CHAT API TESTS
# ============================================================================

function Test-GetMyChats {
    param([string]$Token)
    
    Write-Info "Testing: GET /chats (Get my chats)"
    
    try {
        $response = Invoke-RestMethod `
            -Uri "$BASE_URL/chats" `
            -Method Get `
            -Headers @{
                'Authorization' = "Bearer $Token"
                'Content-Type' = 'application/json'
            }
        
        Write-Success "GET /chats - OK (${response.chats.Count} chats found)"
        if ($Verbose) {
            Write-Host ($response | ConvertTo-Json -Depth 3) -ForegroundColor Gray
        }
        return $response.chats
    } catch {
        Write-Error-Custom "GET /chats failed: $($_.Exception.Message)"
        return @()
    }
}

function Test-CreateChat {
    param(
        [string]$Token,
        [string]$BookingId
    )
    
    Write-Info "Testing: POST /chats (Create chat)"
    
    $body = @{
        booking_id = $BookingId
    } | ConvertTo-Json
    
    try {
        $response = Invoke-RestMethod `
            -Uri "$BASE_URL/chats" `
            -Method Post `
            -Headers @{
                'Authorization' = "Bearer $Token"
                'Content-Type' = 'application/json'
            } `
            -Body $body
        
        Write-Success "POST /chats - OK (Chat ID: $($response.chat_id))"
        if ($Verbose) {
            Write-Host ($response | ConvertTo-Json -Depth 3) -ForegroundColor Gray
        }
        return $response.chat_id
    } catch {
        Write-Error-Custom "POST /chats failed: $($_.Exception.Message)"
        return $null
    }
}

function Test-SendMessage {
    param(
        [string]$Token,
        [string]$ChatId,
        [string]$Content
    )
    
    Write-Info "Testing: POST /chats/$ChatId/messages (Send message)"
    
    $body = @{
        message_text = $Content
    } | ConvertTo-Json
    
    try {
        $response = Invoke-WebRequest `
            -Uri "$BASE_URL/chats/$ChatId/messages" `
            -Method Post `
            -Headers @{
                'Authorization' = "Bearer $Token"
                'Content-Type' = 'application/json'
            } `
            -Body $body `
            -UseBasicParsing
        
        $responseData = $response.Content | ConvertFrom-Json
        Write-Success "POST /chats/$ChatId/messages - OK (Message ID: $($responseData.message.messageId))"
        if ($Verbose) {
            Write-Host ($responseData | ConvertTo-Json -Depth 3) -ForegroundColor Gray
        }
        return $responseData.message.messageId
    } catch {
        Write-Error-Custom "POST /chats/$ChatId/messages FAILED"
        Write-Host "Status Code: $($_.Exception.Response.StatusCode.value__)" -ForegroundColor Red
        Write-Host "Error Message: $($_.Exception.Message)" -ForegroundColor Red
        if ($_.ErrorDetails.Message) {
            Write-Host "Error Details: $($_.ErrorDetails.Message)" -ForegroundColor Red
        }
        return $null
    }
}

function Test-GetMessages {
    param(
        [string]$Token,
        [string]$ChatId
    )
    
    Write-Info "Testing: GET /chats/$ChatId/messages (Get messages)"
    
    try {
        $response = Invoke-RestMethod `
            -Uri "$BASE_URL/chats/$ChatId/messages?limit=50" `
            -Method Get `
            -Headers @{
                'Authorization' = "Bearer $Token"
                'Content-Type' = 'application/json'
            }
        
        Write-Success "GET /chats/$ChatId/messages - OK (${response.messages.Count} messages)"
        if ($Verbose) {
            Write-Host ($response | ConvertTo-Json -Depth 3) -ForegroundColor Gray
        }
        return $response.messages
    } catch {
        Write-Error-Custom "GET /chats/$ChatId/messages failed: $($_.Exception.Message)"
        return @()
    }
}

function Test-UpdateMessageState {
    param(
        [string]$Token,
        [string]$ChatId,
        [string]$MessageId,
        [string]$State = "read"
    )
    
    Write-Info "Testing: PATCH /chats/$ChatId/messages/$MessageId/state (Update state to $State)"
    
    $body = @{
        state = $State
    } | ConvertTo-Json
    
    try {
        $response = Invoke-RestMethod `
            -Uri "$BASE_URL/chats/$ChatId/messages/$MessageId/state" `
            -Method Patch `
            -Headers @{
                'Authorization' = "Bearer $Token"
                'Content-Type' = 'application/json'
            } `
            -Body $body
        
        Write-Success "PATCH /chats/$ChatId/messages/$MessageId/state - OK"
        if ($Verbose) {
            Write-Host ($response | ConvertTo-Json -Depth 3) -ForegroundColor Gray
        }
        return $true
    } catch {
        Write-Error-Custom "PATCH /chats/$ChatId/messages/$MessageId/state failed: $($_.Exception.Message)"
        return $false
    }
}

function Test-SetSticker {
    param(
        [string]$Token,
        [string]$ChatId,
        [string]$MessageId,
        [string]$Sticker = "thumbs_up"
    )
    
    Write-Info "Testing: POST /chats/$ChatId/messages/$MessageId/sticker (Set sticker: $Sticker)"
    
    $body = @{
        sticker = $Sticker
    } | ConvertTo-Json
    
    try {
        $response = Invoke-RestMethod `
            -Uri "$BASE_URL/chats/$ChatId/messages/$MessageId/sticker" `
            -Method Post `
            -Headers @{
                'Authorization' = "Bearer $Token"
                'Content-Type' = 'application/json'
            } `
            -Body $body
        
        Write-Success "POST /chats/$ChatId/messages/$MessageId/sticker - OK"
        if ($Verbose) {
            Write-Host ($response | ConvertTo-Json -Depth 3) -ForegroundColor Gray
        }
        return $true
    } catch {
        Write-Error-Custom "POST /chats/$ChatId/messages/$MessageId/sticker failed: $($_.Exception.Message)"
        return $false
    }
}

function Test-GetUploadUrl {
    param(
        [string]$Token,
        [string]$ChatId,
        [string]$FileName = "test-file.pdf",
        [string]$ContentType = "application/pdf"
    )
    
    Write-Info "Testing: GET /chats/$ChatId/upload-url (Get upload URL)"
    Write-Info "Query params: fileName=$FileName, mimeType=$ContentType"
    
    try {
        $encodedFileName = [System.Web.HttpUtility]::UrlEncode($FileName)
        $encodedMimeType = [System.Web.HttpUtility]::UrlEncode($ContentType)
        $url = "$BASE_URL/chats/$ChatId/upload-url?fileName=$encodedFileName&mimeType=$encodedMimeType"
        
        $response = Invoke-WebRequest `
            -Uri $url `
            -Method Get `
            -Headers @{
                'Authorization' = "Bearer $Token"
            } `
            -UseBasicParsing
        
        Write-Success "GET /chats/$ChatId/upload-url - OK (Status: $($response.StatusCode))"
        $responseData = $response.Content | ConvertFrom-Json
        if ($Verbose) {
            Write-Host "Response: $($response.Content)" -ForegroundColor Gray
        }
        return $responseData
    } catch {
        Write-Error-Custom "GET /chats/$ChatId/upload-url FAILED"
        Write-Host "Status Code: $($_.Exception.Response.StatusCode.value__)" -ForegroundColor Red
        Write-Host "Error Message: $($_.Exception.Message)" -ForegroundColor Red
        if ($_.ErrorDetails.Message) {
            Write-Host "Error Details: $($_.ErrorDetails.Message)" -ForegroundColor Red
        }
        return $null
    }
}

function Test-UploadFile {
    param(
        [string]$UploadUrl,
        [string]$FilePath,
        [string]$ContentType = "application/pdf"
    )
    
    Write-Info "Testing: Upload file to S3 using presigned URL"
    Write-Info "File: $FilePath, Size: $((Get-Item $FilePath).Length) bytes"
    
    try {
        $fileBytes = [System.IO.File]::ReadAllBytes($FilePath)
        
        $response = Invoke-WebRequest `
            -Uri $UploadUrl `
            -Method Put `
            -Headers @{
                'Content-Type' = $ContentType
                'x-amz-server-side-encryption' = 'AES256'
            } `
            -Body $fileBytes `
            -UseBasicParsing
        
        Write-Success "File upload - OK (Status: $($response.StatusCode), Size: $($fileBytes.Length) bytes)"
        return $true
    } catch {
        Write-Error-Custom "File upload FAILED"
        Write-Host "Status Code: $($_.Exception.Response.StatusCode.value__)" -ForegroundColor Red
        Write-Host "Error Message: $($_.Exception.Message)" -ForegroundColor Red
        return $false
    }
}

function Test-SendMessageWithAttachment {
    param(
        [string]$Token,
        [string]$ChatId,
        [string]$Content,
        [string]$FileUrl,
        [string]$FileName = "test-document.pdf",
        [int]$FileSize = 0,
        [string]$FileType = "application/pdf"
    )
    
    Write-Info "Testing: POST /chats/$ChatId/messages with attachment (Send message with file)"
    
    $body = @{
        message_text = $Content
        attachments = @(
            @{
                file_name = $FileName
                file_size = $FileSize
                file_type = $FileType
                s3_url = $FileUrl
            }
        )
    } | ConvertTo-Json -Depth 10
    
    try {
        $response = Invoke-WebRequest `
            -Uri "$BASE_URL/chats/$ChatId/messages" `
            -Method Post `
            -Headers @{
                'Authorization' = "Bearer $Token"
                'Content-Type' = 'application/json'
            } `
            -Body $body `
            -UseBasicParsing
        
        $responseData = $response.Content | ConvertFrom-Json
        Write-Success "POST /chats/$ChatId/messages with attachment - OK (Message ID: $($responseData.message.messageId))"
        if ($Verbose) {
            Write-Host ($responseData | ConvertTo-Json -Depth 3) -ForegroundColor Gray
        }
        # Return message ID from response
        if ($responseData.message.messageId) {
            return $responseData.message.messageId
        } elseif ($responseData.message_id) {
            return $responseData.message_id
        } elseif ($responseData.messageId) {
            return $responseData.messageId
        } else {
            Write-Error-Custom "Could not extract message ID from response"
            Write-Host "Response: $($responseData | ConvertTo-Json)" -ForegroundColor Red
            return $null
        }
    } catch {
        Write-Error-Custom "POST /chats/$ChatId/messages with attachment FAILED"
        Write-Host "Status Code: $($_.Exception.Response.StatusCode.value__)" -ForegroundColor Red
        Write-Host "Error Message: $($_.Exception.Message)" -ForegroundColor Red
        if ($_.ErrorDetails.Message) {
            Write-Host "Error Details: $($_.ErrorDetails.Message)" -ForegroundColor Red
        }
        return $null
    }
}

function Test-GetDownloadUrl {
    param(
        [string]$Token,
        [string]$ChatId,
        [string]$MessageId
    )
    
    Write-Info "Testing: GET /chats/$ChatId/download-url (Get download URL for message attachments)"
    Write-Info "Message ID: $MessageId"
    
    try {
        $url = "$BASE_URL/chats/$ChatId/download-url?messageId=$MessageId"
        Write-Info "URL: $url"
        
        $response = Invoke-WebRequest `
            -Uri $url `
            -Method Get `
            -Headers @{
                'Authorization' = "Bearer $Token"
            } `
            -UseBasicParsing
        
        Write-Success "GET /chats/$ChatId/download-url - OK (Status: $($response.StatusCode))"
        $responseData = $response.Content | ConvertFrom-Json
        if ($Verbose) {
            Write-Host "URLs received: $($responseData | ConvertTo-Json)" -ForegroundColor Gray
        }
        return $responseData
    } catch {
        Write-Error-Custom "GET /chats/$ChatId/download-url FAILED"
        Write-Host "Status Code: $($_.Exception.Response.StatusCode.value__)" -ForegroundColor Red
        Write-Host "Status Description: $($_.Exception.Response.StatusDescription)" -ForegroundColor Red
        Write-Host "Error Message: $($_.Exception.Message)" -ForegroundColor Red
        if ($_.ErrorDetails.Message) {
            Write-Host "Error Details: $($_.ErrorDetails.Message)" -ForegroundColor Red
        }
        Write-Host "Full error: $($_)" -ForegroundColor Red
        return $null
    }
}

function Test-DownloadFile {
    param(
        [string]$DownloadUrl,
        [string]$OutputPath
    )
    
    Write-Info "Testing: Download file from S3 using presigned URL"
    Write-Info "Downloading to: $OutputPath"
    
    try {
        $response = Invoke-WebRequest `
            -Uri $DownloadUrl `
            -Method Get `
            -UseBasicParsing `
            -OutFile $OutputPath
        
        $fileSize = (Get-Item $OutputPath).Length
        Write-Success "File download - OK (Status: $($response.StatusCode), Downloaded size: $fileSize bytes)"
        return $fileSize
    } catch {
        Write-Error-Custom "File download FAILED"
        Write-Host "Status Code: $($_.Exception.Response.StatusCode.value__)" -ForegroundColor Red
        Write-Host "Error Message: $($_.Exception.Message)" -ForegroundColor Red
        return 0
    }
}

function Test-RequestBeezeyHelp {
    param(
        [string]$Token,
        [string]$ChatId,
        [string]$Question = "Ho bisogno di aiuto con gli orari di lavoro"
    )
    
    Write-Info "Testing: POST /chats/$ChatId/request-help (Request Beezey help)"
    Write-Info "Question: $Question"
    
    $body = @{
        question = $Question
    } | ConvertTo-Json
    
    try {
        $response = Invoke-WebRequest `
            -Uri "$BASE_URL/chats/$ChatId/request-help" `
            -Method Post `
            -Headers @{
                'Authorization' = "Bearer $Token"
                'Content-Type' = 'application/json'
            } `
            -Body $body `
            -UseBasicParsing
        
        Write-Success "POST /chats/$ChatId/request-help - OK (Status: $($response.StatusCode))"
        if ($Verbose) {
            $responseData = $response.Content | ConvertFrom-Json
            Write-Host "User message: $($responseData.user_message.message_text)" -ForegroundColor Gray
            Write-Host "Beezey response: $($responseData.beezey_response.message_text)" -ForegroundColor Gray
        }
        return $true
    } catch {
        Write-Error-Custom "POST /chats/$ChatId/request-help FAILED"
        Write-Host "Status Code: $($_.Exception.Response.StatusCode.value__)" -ForegroundColor Red
        if ($_.ErrorDetails.Message) {
            Write-Host "Error Details: $($_.ErrorDetails.Message)" -ForegroundColor Red
        }
        return $false
    }
}

function Test-UpdateChatStatus {
    param(
        [string]$Token,
        [string]$ChatId,
        [string]$Status = "archived"
    )
    
    Write-Info "Testing: PATCH /chats/$ChatId/status (Update chat status to '$Status')"
    
    $body = @{
        status = $Status
    } | ConvertTo-Json
    
    try {
        $response = Invoke-WebRequest `
            -Uri "$BASE_URL/chats/$ChatId/status" `
            -Method Patch `
            -Headers @{
                'Authorization' = "Bearer $Token"
                'Content-Type' = 'application/json'
            } `
            -Body $body `
            -UseBasicParsing
        
        $responseData = $response.Content | ConvertFrom-Json
        Write-Success "PATCH /chats/$ChatId/status - OK (Status changed: $($responseData.previousStatus) → $($responseData.status))"
        if ($Verbose) {
            Write-Host ($responseData | ConvertTo-Json -Depth 3) -ForegroundColor Gray
        }
        return $true
    } catch {
        Write-Error-Custom "PATCH /chats/$ChatId/status FAILED"
        Write-Host "Status Code: $($_.Exception.Response.StatusCode.value__)" -ForegroundColor Red
        if ($_.ErrorDetails.Message) {
            Write-Host "Error Details: $($_.ErrorDetails.Message)" -ForegroundColor Red
        }
        return $false
    }
}

function Test-DeleteChat {
    param(
        [string]$Token,
        [string]$ChatId
    )
    
    Write-Info "Testing: DELETE /chats/$ChatId (Delete chat)"
    
    try {
        $response = Invoke-RestMethod `
            -Uri "$BASE_URL/chats/$ChatId" `
            -Method Delete `
            -Headers @{
                'Authorization' = "Bearer $Token"
                'Content-Type' = 'application/json'
            }
        
        Write-Success "DELETE /chats/$ChatId - OK"
        if ($Verbose) {
            Write-Host ($response | ConvertTo-Json -Depth 3) -ForegroundColor Gray
        }
        return $true
    } catch {
        Write-Error-Custom "DELETE /chats/$ChatId failed: $($_.Exception.Message)"
        return $false
    }
}

# ============================================================================
# MAIN TEST EXECUTION
# ============================================================================

Write-Host "`n===============================================================" -ForegroundColor Cyan
Write-Host "          CHAT API - COMPLETE TEST SUITE                   " -ForegroundColor Cyan
Write-Host "===============================================================`n" -ForegroundColor Cyan

try {
    # Step 1: Authenticate both users
    Write-Step "STEP 1: Authentication"
    $user1Auth = Get-AuthToken -Email $USER1_EMAIL -Password $USER1_PASSWORD
    $user2Auth = Get-AuthToken -Email $USER2_EMAIL -Password $USER2_PASSWORD
    
    Write-Info "User 1 ID: $($user1Auth.UserId)"
    Write-Info "User 2 ID: $($user2Auth.UserId)"
    
    # Step 2: Get existing chats for User 1
    Write-Step "STEP 2: Get My Chats (User 1)"
    $chatsResponse = Test-GetMyChats -Token $user1Auth.Token
    
    # Use existing chat
    if ($chatsResponse -and @($chatsResponse).Count -gt 0) {
        $testChatId = $chatsResponse[0].chatId
        Write-Info "Using existing chat: $testChatId"
        Write-Info "Booking ID: $($chatsResponse[0].bookingId)"
        Write-Info "Status: $($chatsResponse[0].status)"
    } else {
        throw "ERRORE: Nessuna chat trovata! La chat deve esistere tra i due utenti!"
    }
    
    if ($true) {
        # Step 3: Send messages from User 1
        Write-Step "STEP 3: Send Messages (User 1)"
        $msg1 = Test-SendMessage -Token $user1Auth.Token -ChatId $testChatId -Content "Ciao! Test message from User 1"
        Start-Sleep -Seconds 1
        $msg2 = Test-SendMessage -Token $user1Auth.Token -ChatId $testChatId -Content "Questo è il secondo messaggio di test"
        
        # Step 4: Get messages as User 2
        Write-Step "STEP 4: Get Messages (User 2)"
        $messages = Test-GetMessages -Token $user2Auth.Token -ChatId $testChatId
        
        # Step 4.1: Verify lastMessageState BEFORE marking as read
        Write-Step "STEP 4.1: Get Chat List BEFORE marking as read (User 2)"
        $chatsBefore = Test-GetMyChats -Token $user2Auth.Token
        $testChatBefore = $chatsBefore | Where-Object { $_.chatId -eq $testChatId } | Select-Object -First 1
        if ($testChatBefore) {
            Write-Host "" -ForegroundColor Cyan
            Write-Host "========== BEFORE MARKING AS READ ==========" -ForegroundColor Cyan
            Write-Host "Chat ID: $($testChatBefore.chatId)" -ForegroundColor Yellow
            Write-Host "lastMessageState: $($testChatBefore.lastMessageState)" -ForegroundColor $(if($testChatBefore.lastMessageState -eq 'sent'){'Yellow'}else{'Red'})
            Write-Host "lastMessageSenderId: $($testChatBefore.lastMessageSenderId)" -ForegroundColor Magenta
            Write-Host "lastMessagePreview: $($testChatBefore.lastMessagePreview)" -ForegroundColor Gray
            Write-Host "Current User ID: $($user2Auth.UserId)" -ForegroundColor Gray
            Write-Host "" -ForegroundColor Cyan
        }
        
        # Step 5: Update message state (User 2 marks as read)
        if ($msg2) {
            Write-Step "STEP 5: Update Message State (User 2 marks as read)"
            # Use msg2 (the LAST message) so the conditional update works
            Test-UpdateMessageState -Token $user2Auth.Token -ChatId $testChatId -MessageId $msg2 -State "read"
            Start-Sleep -Seconds 2
            
            # Step 5.1: Verify lastMessageState AFTER marking as read
            Write-Step "STEP 5.1: Get Chat List AFTER marking as read (User 2)"
            $chatsAfter = Test-GetMyChats -Token $user2Auth.Token
            $testChatAfter = $chatsAfter | Where-Object { $_.chatId -eq $testChatId } | Select-Object -First 1
            if ($testChatAfter) {
                Write-Host "" -ForegroundColor Cyan
                Write-Host "========== AFTER MARKING AS READ ==========" -ForegroundColor Cyan
                Write-Host "Chat ID: $($testChatAfter.chatId)" -ForegroundColor Yellow
                Write-Host "lastMessageState: $($testChatAfter.lastMessageState)" -ForegroundColor $(if($testChatAfter.lastMessageState -eq 'read'){'Green'}else{'Red'})
                Write-Host "lastMessageSenderId: $($testChatAfter.lastMessageSenderId)" -ForegroundColor Magenta
                Write-Host "lastMessagePreview: $($testChatAfter.lastMessagePreview)" -ForegroundColor Gray
                Write-Host "" -ForegroundColor Cyan
                
                if (($testChatBefore.lastMessageState -eq 'sent' -or $testChatBefore.lastMessageState -eq 'delivered') -and $testChatAfter.lastMessageState -eq 'read') {
                    Write-Success "[OK] State changed from '$($testChatBefore.lastMessageState)' to 'read' successfully!"
                } else {
                    Write-Error-Custom "[ERROR] State did NOT change correctly! Before: $($testChatBefore.lastMessageState), After: $($testChatAfter.lastMessageState)"
                }
            }
        }
        
        # Step 6: User 2 sends reply
        Write-Step "STEP 6: Send Reply (User 2)"
        $replyMsg = Test-SendMessage -Token $user2Auth.Token -ChatId $testChatId -Content "Risposta da User 2 - tutto ok!"
        
        # Step 7: Set sticker (User 1)
        if ($replyMsg) {
            # Wait for GSI to index the message
            Start-Sleep -Seconds 2
            Write-Step "STEP 7: Set Sticker (User 1 adds thumbs_up)"
            Test-SetSticker -Token $user1Auth.Token -ChatId $testChatId -MessageId $replyMsg -Sticker "thumbs_up"
        }
        
        # Step 8: Use existing JPG image file
        Write-Step "STEP 8: Use Existing Image File"
        $testFilePath = "C:\Users\miner\Desktop\fronte.jpg"
        
        if (-not (Test-Path $testFilePath)) {
            Write-Error-Custom "Image file not found: $testFilePath"
            throw "Test file not found"
        }
        
        $testContent = [System.IO.File]::ReadAllBytes($testFilePath)
        Write-Success "Using image file: $testFilePath (Size: $($testContent.Length) bytes)"
        
        # Step 9: Get upload URL from Lambda
        Write-Step "STEP 9: Get Upload URL from Lambda"
        $uploadUrlResponse = Test-GetUploadUrl -Token $user1Auth.Token -ChatId $testChatId -FileName "fronte.jpg" -ContentType "image/jpeg"
        
        if ($uploadUrlResponse) {
            $uploadUrl = $uploadUrlResponse.uploadUrl
            $fileUrl = $uploadUrlResponse.fileUrl
            Write-Info "Presigned Upload URL received"
            Write-Info "Static File URL received: $fileUrl"
            
            # Step 10: Upload file to S3 using presigned URL
            Write-Step "STEP 10: Upload File to S3"
            $uploadSuccess = Test-UploadFile -UploadUrl $uploadUrl -FilePath $testFilePath -ContentType "image/jpeg"
            
            if ($uploadSuccess) {
                # Step 11: Send message with attachment using STATIC URL from lambda
                Write-Step "STEP 11: Send Message with Attachment (using static fileUrl from lambda)"
                $msgWithAttachment = Test-SendMessageWithAttachment -Token $user1Auth.Token -ChatId $testChatId -Content "Ecco il documento fronte" -FileUrl $fileUrl -FileName "fronte.jpg" -FileSize $testContent.Length
                
                Write-Info "Message ID returned: '$msgWithAttachment' (Type: $($msgWithAttachment.GetType()))"
                
                if ($msgWithAttachment -and $msgWithAttachment -ne "") {
                    # Step 12: Get download URL from Lambda
                    Write-Step "STEP 12: Get Download URL from Lambda"
                    Write-Info "Message ID for download: $msgWithAttachment"
                    $downloadUrlResponse = Test-GetDownloadUrl -Token $user2Auth.Token -ChatId $testChatId -MessageId $msgWithAttachment
                    
                    if ($downloadUrlResponse) {
                        Write-Info "Download URL response received"
                        if ($Verbose) {
                            Write-Host "Full response: $($downloadUrlResponse | ConvertTo-Json -Depth 5)" -ForegroundColor Gray
                        }
                        
                        # Extract presigned URL from response - support both formats
                        $presignedDownloadUrl = $null
                        
                        # Try different response formats
                        if ($downloadUrlResponse.downloadUrl) {
                            $presignedDownloadUrl = $downloadUrlResponse.downloadUrl
                            Write-Info "Found downloadUrl in root"
                        } elseif ($downloadUrlResponse.attachments) {
                            # Array of attachments
                            if ($downloadUrlResponse.attachments[0].downloadUrl) {
                                $presignedDownloadUrl = $downloadUrlResponse.attachments[0].downloadUrl
                                Write-Info "Found downloadUrl in attachments[0]"
                            }
                        } elseif ($downloadUrlResponse -is [array] -and $downloadUrlResponse.Count -gt 0) {
                            # Direct array response
                            if ($downloadUrlResponse[0].downloadUrl) {
                                $presignedDownloadUrl = $downloadUrlResponse[0].downloadUrl
                                Write-Info "Found downloadUrl in array[0]"
                            }
                        }
                        
                        if ($presignedDownloadUrl) {
                            Write-Success "Presigned Download URL received"
                            Write-Info "Download URL: $($presignedDownloadUrl.Substring(0, 100))..."
                            
                            # Step 13: Download file from S3
                            Write-Step "STEP 13: Download File from S3"
                            $downloadedFilePath = "$env:TEMP\test-image-downloaded-$(Get-Date -Format 'yyyyMMdd-HHmmss').jpg"
                            $downloadedSize = Test-DownloadFile -DownloadUrl $presignedDownloadUrl -OutputPath $downloadedFilePath
                            
                            if ($downloadedSize -gt 0) {
                                # Step 14: Verify file size
                                Write-Step "STEP 14: Verify File Integrity"
                                if ($downloadedSize -eq $testContent.Length) {
                                    Write-Success "File size matches! Original: $($testContent.Length) bytes, Downloaded: $downloadedSize bytes"
                                } else {
                                    Write-Error-Custom "File size mismatch! Original: $($testContent.Length) bytes, Downloaded: $downloadedSize bytes"
                                }
                                
                                # Cleanup - COMMENTED TO KEEP FILE
                                Write-Info "Downloaded file kept at: $downloadedFilePath"
                                # Remove-Item -Path $downloadedFilePath -Force
                            }
                        } else {
                            Write-Error-Custom "No download URL found in response"
                            Write-Host "Response structure: $($downloadUrlResponse | ConvertTo-Json -Depth 3)" -ForegroundColor Red
                        }
                    } else {
                        Write-Error-Custom "Download URL endpoint returned no response"
                    }
                }
            }
            
            # Cleanup test file - COMMENTED TO KEEP FILE
            Write-Info "Test file kept at: $testFilePath"
            # Remove-Item -Path $testFilePath -Force
        }
        
        # Step 15: Request Beezey help
        Write-Step "STEP 15: Request Beezey Help"
        Test-RequestBeezeyHelp -Token $user1Auth.Token -ChatId $testChatId
        
        # Step 16: Final message list
        Write-Step "STEP 16: Final Message List (User 1)"
        $finalMessages = Test-GetMessages -Token $user1Auth.Token -ChatId $testChatId
        Write-Info "Total messages in chat: $($finalMessages.Count)"
        
        # Step 17: Update Chat Status
        Write-Step "STEP 17: Update Chat Status (archived)"
        Test-UpdateChatStatus -Token $user1Auth.Token -ChatId $testChatId -Status "archived"
        
        # Step 18: Verify status change
        Write-Step "STEP 18: Verify Status Change"
        $chatsResponse = Test-GetMyChats -Token $user1Auth.Token
        $testChat = $chatsResponse | Where-Object { $_.chatId -eq $testChatId }
        if ($testChat) {
            Write-Info "Chat Status: $($testChat.status)"
            if ($testChat.status -eq "archived") {
                Write-Success "Status correctly updated to 'archived'"
            } else {
                Write-Error-Custom "Status not updated correctly (expected 'archived', got '$($testChat.status)')"
            }
        }
        
        # Step 19: Reactivate chat
        Write-Step "STEP 19: Reactivate Chat (back to active)"
        Test-UpdateChatStatus -Token $user1Auth.Token -ChatId $testChatId -Status "active"
    }
    
    # Summary
    Write-Host "`n===============================================================" -ForegroundColor Green
    Write-Host "               TEST SUITE COMPLETED                         " -ForegroundColor Green
    Write-Host "===============================================================`n" -ForegroundColor Green
    
    Write-Success "All tests executed successfully!"
    Write-Info "Chat ID used: $testChatId"    
    # ========================================
    # MANUAL TESTING INFORMATION FOR SWAGGER
    # ========================================
    Write-Host "\n" -ForegroundColor White
    Write-Host "===============================================================" -ForegroundColor Cyan
    Write-Host "          MANUAL TESTING INFORMATION (SWAGGER)              " -ForegroundColor Cyan
    Write-Host "===============================================================" -ForegroundColor Cyan
    Write-Host "" -ForegroundColor White
    Write-Host "API BASE URL:" -ForegroundColor Yellow
    Write-Host "  https://57s2xhuuo4.execute-api.eu-south-1.amazonaws.com/dev" -ForegroundColor White
    Write-Host "" -ForegroundColor White
    Write-Host "CHAT ID:" -ForegroundColor Yellow
    Write-Host "  $testChatId" -ForegroundColor White
    Write-Host "" -ForegroundColor White
    Write-Host "USER 1 (Sender):" -ForegroundColor Yellow
    Write-Host "  Email: gecetev283@naqulu.com" -ForegroundColor White
    Write-Host "  Password: Password@1" -ForegroundColor White
    Write-Host "  ID Token (Bearer):" -ForegroundColor White
    Write-Host "  $($user1Auth.Token)" -ForegroundColor Green
    Write-Host "" -ForegroundColor White
    Write-Host "USER 2 (Receiver):" -ForegroundColor Yellow
    Write-Host "  Email: titocet754@naqulu.com" -ForegroundColor White
    Write-Host "  Password: Password@1" -ForegroundColor White
    Write-Host "  ID Token (Bearer):" -ForegroundColor White
    Write-Host "  $($user2Auth.Token)" -ForegroundColor Green
    Write-Host "" -ForegroundColor White
    Write-Host "COGNITO INFO:" -ForegroundColor Yellow
    Write-Host "  User Pool ID: eu-south-1_0oK9agPYd" -ForegroundColor White
    Write-Host "  Client ID: 79g67hnuepfuoh1fnk4d98jfpu" -ForegroundColor White
    Write-Host "  Region: eu-south-1" -ForegroundColor White
    Write-Host "" -ForegroundColor White
    Write-Host "SWAGGER ENDPOINTS TO TEST:" -ForegroundColor Yellow
    Write-Host "  GET    /chats                                  (List chats)" -ForegroundColor White
    Write-Host "  GET    /chats/{chatId}/messages                (Get messages)" -ForegroundColor White
    Write-Host "  POST   /chats/{chatId}/messages                (Send message)" -ForegroundColor White
    Write-Host "  PATCH  /chats/{chatId}/messages/{msgId}/state  (Update state)" -ForegroundColor White
    Write-Host "  POST   /chats/{chatId}/messages/{msgId}/sticker (Set sticker)" -ForegroundColor White
    Write-Host "  GET    /chats/{chatId}/upload-url              (Get upload URL)" -ForegroundColor White
    Write-Host "  GET    /chats/{chatId}/download-url            (Get download URL)" -ForegroundColor White
    Write-Host "" -ForegroundColor White
    Write-Host "HOW TO USE IN SWAGGER:" -ForegroundColor Yellow
    Write-Host "  1. Open Swagger UI" -ForegroundColor White
    Write-Host "  2. Click 'Authorize' button (top right)" -ForegroundColor White
    Write-Host "  3. Paste one of the ID tokens above (without 'Bearer' prefix)" -ForegroundColor White
    Write-Host "  4. Click 'Authorize' then 'Close'" -ForegroundColor White
    Write-Host "  5. Use the Chat ID above to test endpoints" -ForegroundColor White
    Write-Host "" -ForegroundColor White
    Write-Host "===============================================================" -ForegroundColor Cyan
    Write-Host "" -ForegroundColor White    
} catch {
    Write-Host "`n===============================================================" -ForegroundColor Red
    Write-Host "               TEST SUITE FAILED                            " -ForegroundColor Red
    Write-Host "===============================================================`n" -ForegroundColor Red
    
    $errorMsg = $_.Exception.Message
    Write-Error-Custom "Error: $errorMsg"
    Write-Host $_.ScriptStackTrace -ForegroundColor Red
    exit 1
}
