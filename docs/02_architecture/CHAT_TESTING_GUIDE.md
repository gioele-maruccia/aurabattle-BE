# Chat System - Testing Guide

## ✅ Deployment Status
- **DynamoDB Tables**: dev-Chats, dev-Messages
- **S3 Bucket**: dev-beezey-chat-attachments  
- **API Gateway**: https://57s2xhuuo4.execute-api.eu-south-1.amazonaws.com/dev/
- **Lambda Functions**: 7 functions deployed
- **Lambda Layer**: dev-chat-shared-layer (version 7)
- **Status**: **FULLY OPERATIONAL**

## 🔑 Authentication Setup

### Get JWT Token
```powershell
cd C:\Users\miner\Desktop\Beezey\beezey-BE\scripts\chat
.\get-cognito-token.bat
```
This will prompt for username/password and save the token to `jwt-token.txt`.

### Verify Token
```powershell
$token = [System.IO.File]::ReadAllText((Join-Path $PWD 'jwt-token.txt')).Trim()
$parts = $token.Split('.')
$payload = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($parts[1] + '=' * ((4 - ($parts[1].Length % 4)) % 4)))
$payload | ConvertFrom-Json | Format-List
```

## 🧪 Testing Endpoints

### 1. Create Chat
```powershell
cd C:\Users\miner\Desktop\Beezey\beezey-BE\scripts\chat

$token = [System.IO.File]::ReadAllText((Join-Path $PWD 'jwt-token.txt')).Trim()

curl.exe -X POST 'https://57s2xhuuo4.execute-api.eu-south-1.amazonaws.com/dev/chats' `
  -H "Authorization: Bearer $token" `
  -H 'Content-Type: application/json' `
  -d '{\"booking_id\":\"book_test_001\",\"worker_id\":\"worker_123\",\"company_id\":\"comp_456\",\"booking_details\":{\"job_role\":\"cameriere\",\"start_date\":\"2025-11-25\"}}'
```

**Expected Response:**
```json
{
  "chat": {
    "chatId": "chat_xxx",
    "bookingId": "book_test_001",
    "workerId": "worker_123",
    "companyId": "comp_456",
    "createdAt": "2025-11-23T15:03:11+00:00",
    "status": "active"
  },
  "welcome_message": {
    "chatId": "chat_xxx",
    "messageId": "msg_xxx",
    "senderId": "beezey_system",
    "senderType": "beezey",
    "messageText": "👋 Benvenuto nella chat!...",
    "timestamp": "2025-11-23T15:03:11+00:00",
    "state": "sent"
  }
}
```

### 2. Get Messages
```powershell
$chatId = "chat_30d00f7e7b7e4118"  # Use actual chatId from create response

curl.exe -X GET "https://ivs8m2z7bh.execute-api.eu-south-1.amazonaws.com/dev/chats/$chatId/messages" `
  -H "Authorization: Bearer $token"
```

### 3. Send Message
```powershell
$chatId = "chat_30d00f7e7b7e4118"

curl.exe -X POST "https://ivs8m2z7bh.execute-api.eu-south-1.amazonaws.com/dev/chats/$chatId/messages" `
  -H "Authorization: Bearer $token" `
  -H 'Content-Type: application/json' `
  -d '{\"sender_id\":\"worker_123\",\"sender_type\":\"worker\",\"message_text\":\"Ciao, quando posso iniziare?\"}'
```

### 4. Update Message State
```powershell
$chatId = "chat_30d00f7e7b7e4118"
$messageId = "msg_xxx"  # From send message response

curl.exe -X PATCH "https://ivs8m2z7bh.execute-api.eu-south-1.amazonaws.com/dev/chats/$chatId/messages/$messageId/state" `
  -H "Authorization: Bearer $token" `
  -H 'Content-Type: application/json' `
  -d '{\"state\":\"delivered\"}'
```

### 5. Set Sticker
```powershell
$chatId = "chat_30d00f7e7b7e4118"

curl.exe -X PATCH "https://ivs8m2z7bh.execute-api.eu-south-1.amazonaws.com/dev/chats/$chatId/sticker" `
  -H "Authorization: Bearer $token" `
  -H 'Content-Type: application/json' `
  -d '{\"sticker_emoji\":\"⭐\",\"sticker_color\":\"gold\"}'
```

### 6. Get Upload URL
```powershell
$chatId = "chat_30d00f7e7b7e4118"

curl.exe -X POST "https://ivs8m2z7bh.execute-api.eu-south-1.amazonaws.com/dev/chats/$chatId/upload-url" `
  -H "Authorization: Bearer $token" `
  -H 'Content-Type: application/json' `
  -d '{\"file_name\":\"documento.pdf\",\"file_type\":\"application/pdf\"}'
```

### 7. Request Beezey Help
```powershell
$chatId = "chat_30d00f7e7b7e4118"

curl.exe -X POST "https://ivs8m2z7bh.execute-api.eu-south-1.amazonaws.com/dev/chats/$chatId/request-help" `
  -H "Authorization: Bearer $token" `
  -H 'Content-Type: application/json' `
  -d '{\"issue_description\":\"Non riesco a caricare il documento\",\"requester_id\":\"worker_123\",\"requester_type\":\"worker\"}'
```

## 🔍 Debugging

### Check DynamoDB Tables
```powershell
# List all chats
aws dynamodb scan --table-name dev-Chats --region eu-south-1

# List all messages for a chat
aws dynamodb query --table-name dev-Messages `
  --key-condition-expression "chatId = :chatId" `
  --expression-attribute-values '{":chatId":{"S":"chat_30d00f7e7b7e4118"}}' `
  --region eu-south-1
```

### Check Lambda Logs
```powershell
# View logs for create-chat function
aws logs tail /aws/lambda/dev-chat-create --follow --region eu-south-1
```

### Check S3 Bucket
```powershell
aws s3 ls s3://dev-beezey-chat-attachments/ --region eu-south-1
```

## ⚠️ Common Issues

### Issue: "Access Denied"
**Cause**: JWT token file contains BOM (Byte Order Mark)  
**Solution**: Token is saved correctly by `get-cognito-token.bat`. Always use PowerShell to read:
```powershell
$token = [System.IO.File]::ReadAllText((Join-Path $PWD 'jwt-token.txt')).Trim()
```

### Issue: Token Expired
**Cause**: Cognito tokens expire after 24 hours  
**Solution**: Run `get-cognito-token.bat` again to get a fresh token

### Issue: "No module named 'models'"
**Cause**: Lambda layer not properly attached  
**Solution**: This is fixed in layer version 7. Redeploy if needed:
```batch
cd C:\Users\miner\Desktop\Beezey\beezey-BE\scripts
.\deploy-chat-system.bat
```

## 📊 Test Results

✅ **DynamoDB Tables**: Deployed and accessible  
✅ **S3 Bucket**: Created successfully  
✅ **Lambda Layer**: Version 7 working correctly  
✅ **API Gateway**: Authenticated requests working  
✅ **Create Chat**: Returns 201 with chat + welcome message  
✅ **Lambda Direct Invocation**: All functions tested successfully  
✅ **Cognito Authentication**: JWT tokens working correctly  

## 🎯 Next Steps

1. Test remaining endpoints (Send Message, Get Messages, etc.)
2. Test file upload workflow (Get Upload URL → Upload to S3)
3. Test message state transitions (sent → delivered → read)
4. Integrate with frontend application
5. Set up monitoring and alerts
6. Configure production environment

## 📝 Notes

- Current environment: **dev**
- Region: **eu-south-1**
- All Lambda functions use Python 3.13 runtime
- DynamoDB streams enabled for real-time updates
- S3 bucket configured for CORS
- API Gateway has Cognito authorizer attached
