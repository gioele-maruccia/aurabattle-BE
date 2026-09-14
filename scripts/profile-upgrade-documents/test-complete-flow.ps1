# Test completo del flusso Profile Upgrade
param(
    [Parameter(Mandatory=$true)][string]$Username,
    [Parameter(Mandatory=$true)][string]$Password,
    [Parameter(Mandatory=$true)][string]$IdCardPath,
    [Parameter(Mandatory=$true)][string]$SelfiePath
)

$ErrorActionPreference = "Stop"
$API_URL = "https://fwizu30er5.execute-api.eu-south-1.amazonaws.com/dev"

Write-Host "`n====================================" -ForegroundColor Cyan
Write-Host "  PROFILE UPGRADE - TEST COMPLETO" -ForegroundColor Cyan
Write-Host "====================================`n" -ForegroundColor Cyan

# STEP 1: Login con Cognito (senza API)
Write-Host "[1/5] Login con AWS Cognito..." -ForegroundColor Yellow
try {
    $result = aws cognito-idp admin-initiate-auth `
        --user-pool-id "eu-south-1_0oK9agPYd" `
        --client-id "79g67hnuepfuoh1fnk4d98jfpu" `
        --auth-flow ADMIN_NO_SRP_AUTH `
        --auth-parameters "USERNAME=$Username,PASSWORD=$Password" `
        --region eu-south-1 | ConvertFrom-Json
    
    $TOKEN = $result.AuthenticationResult.IdToken
    Write-Host "OK Login effettuato" -ForegroundColor Green
} catch {
    Write-Host "ERRORE Login fallito: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

$headers = @{ "Authorization" = "Bearer $TOKEN"; "Content-Type" = "application/json" }

# STEP 2: Upload ID Card
Write-Host "`n[2/5] Upload documento..." -ForegroundColor Yellow
try {
    $presignBody = @{ docType = "id_card_front"; mime = "image/jpeg"; size = (Get-Item $IdCardPath).Length } | ConvertTo-Json
    $presignResponse = Invoke-RestMethod -Uri "$API_URL/documents/upload-url" -Method POST -Headers $headers -Body $presignBody
    Write-Host "OK Presigned URL: $($presignResponse.documentId)" -ForegroundColor Green
    
    $imageBytes = [System.IO.File]::ReadAllBytes($IdCardPath)
    $uploadHeaders = @{}
    foreach ($key in $presignResponse.requiredHeaders.PSObject.Properties.Name) {
        $uploadHeaders[$key] = $presignResponse.requiredHeaders.$key
    }
    Invoke-RestMethod -Uri $presignResponse.uploadUrl -Method PUT -Body $imageBytes -Headers $uploadHeaders | Out-Null
    Write-Host "OK Documento caricato" -ForegroundColor Green
    Start-Sleep -Seconds 2
} catch {
    Write-Host "ERRORE Upload: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

# STEP 3: Verifica Selfie
Write-Host "`n[3/5] Verifica selfie..." -ForegroundColor Yellow
try {
    $selfieBytes = [System.IO.File]::ReadAllBytes($SelfiePath)
    $selfieBase64 = [Convert]::ToBase64String($selfieBytes)
    $verifyBody = @{ selfie_base64 = $selfieBase64 } | ConvertTo-Json
    $verifyResponse = Invoke-RestMethod -Uri "$API_URL/documents/verify-face" -Method POST -Headers $headers -Body $verifyBody
    
    Write-Host "OK Verifica completata!" -ForegroundColor Green
    Write-Host "  Face match: $($verifyResponse.verification.face_match)" -ForegroundColor Gray
    Write-Host "  Similarity: $($verifyResponse.verification.similarity)%" -ForegroundColor Gray
} catch {
    Write-Host "ERRORE Verifica: $($_.Exception.Message)" -ForegroundColor Red
    if ($_.ErrorDetails.Message) {
        $err = $_.ErrorDetails.Message | ConvertFrom-Json
        Write-Host "  Code: $($err.error_code)" -ForegroundColor Red
        Write-Host "  Msg: $($err.message)" -ForegroundColor Red
    }
    exit 1
}

# STEP 4: Upload Selfie
Write-Host "`n[4/5] Upload selfie..." -ForegroundColor Yellow
try {
    $selfiePresignBody = @{ docType = "selfie"; mime = "image/jpeg"; size = (Get-Item $SelfiePath).Length } | ConvertTo-Json
    $selfiePresignResponse = Invoke-RestMethod -Uri "$API_URL/documents/upload-url" -Method POST -Headers $headers -Body $selfiePresignBody
    Write-Host "OK Presigned URL: $($selfiePresignResponse.documentId)" -ForegroundColor Green
    
    $selfieBytes = [System.IO.File]::ReadAllBytes($SelfiePath)
    $selfieUploadHeaders = @{}
    foreach ($key in $selfiePresignResponse.requiredHeaders.PSObject.Properties.Name) {
        $selfieUploadHeaders[$key] = $selfiePresignResponse.requiredHeaders.$key
    }
    Invoke-RestMethod -Uri $selfiePresignResponse.uploadUrl -Method PUT -Body $selfieBytes -Headers $selfieUploadHeaders | Out-Null
    Write-Host "OK Selfie caricato" -ForegroundColor Green
} catch {
    Write-Host "ERRORE Upload selfie: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

# STEP 5: Stato documenti
Write-Host "`n[5/5] Stato documenti..." -ForegroundColor Yellow
try {
    $tokenParts = $TOKEN.Split('.')
    $payload = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($tokenParts[1] + "=="))
    $payloadJson = $payload | ConvertFrom-Json
    $userSub = $payloadJson.sub
    
    $statusResponse = Invoke-RestMethod -Uri "$API_URL/user/$userSub/documents/status" -Method GET -Headers @{ "Authorization" = "Bearer $TOKEN" }
    
    Write-Host "OK Stato recuperato" -ForegroundColor Green
    Write-Host "`nDocumenti:" -ForegroundColor Cyan
    foreach ($doc in $statusResponse.documents) {
        Write-Host "  - $($doc.document_type): $($doc.status)" -ForegroundColor Gray
    }
} catch {
    Write-Host "WARN Stato non disponibile" -ForegroundColor Yellow
}

Write-Host "`n====================================" -ForegroundColor Cyan
Write-Host "  TEST COMPLETATO!" -ForegroundColor Green
Write-Host "====================================`n" -ForegroundColor Cyan
