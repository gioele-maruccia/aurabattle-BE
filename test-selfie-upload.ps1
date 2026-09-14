# Test semplificato upload selfie dopo modifica
param(
    [Parameter(Mandatory=$true)][string]$Token,
    [Parameter(Mandatory=$false)][string]$SelfiePath = "C:\temp\test-selfie.jpg"
)

$ErrorActionPreference = "Stop"
$API_URL = "https://fwizu30er5.execute-api.eu-south-1.amazonaws.com/dev"

Write-Host "`n===== TEST SELFIE UPLOAD =====" -ForegroundColor Cyan
Write-Host "Endpoint: $API_URL/documents/upload-url" -ForegroundColor Gray
Write-Host "DocType: selfie (NUOVO!)" -ForegroundColor Yellow

# Crea un file di test se non esiste
if (-not (Test-Path $SelfiePath)) {
    Write-Host "`nCreando file test selfie..." -ForegroundColor Yellow
    New-Item -ItemType Directory -Force -Path (Split-Path $SelfiePath) | Out-Null
    # Crea un PNG minimo (1x1 pixel rosso)
    [byte[]]$pngData = 0x89,0x50,0x4E,0x47,0x0D,0x0A,0x1A,0x0A,0x00,0x00,0x00,0x0D,0x49,0x48,0x44,0x52,
                       0x00,0x00,0x00,0x01,0x00,0x00,0x00,0x01,0x08,0x02,0x00,0x00,0x00,0x90,0x77,0x53,
                       0xDE,0x00,0x00,0x00,0x0C,0x49,0x44,0x41,0x54,0x08,0x99,0x63,0xF8,0x0F,0x00,0x00,
                       0x01,0x01,0x00,0x00,0xC4,0xA9,0xB3,0xD2,0x00,0x00,0x00,0x00,0x49,0x45,0x4E,0x44,
                       0xAE,0x42,0x60,0x82
    [System.IO.File]::WriteAllBytes($SelfiePath, $pngData)
    Write-Host "File creato: $SelfiePath" -ForegroundColor Green
}

$headers = @{ 
    "Authorization" = "Bearer $Token"
    "Content-Type" = "application/json" 
}

try {
    # Richiedi presigned URL per selfie
    Write-Host "`n[1] Richiesta presigned URL per selfie..." -ForegroundColor Yellow
    $fileSize = (Get-Item $SelfiePath).Length
    $body = @{ 
        docType = "selfie"
        mime = "image/png"
        size = $fileSize
    } | ConvertTo-Json
    
    Write-Host "Body: $body" -ForegroundColor Gray
    
    $response = Invoke-RestMethod -Uri "$API_URL/documents/upload-url" `
        -Method POST `
        -Headers $headers `
        -Body $body
    
    Write-Host "✓ SUCCESSO! Presigned URL ricevuto" -ForegroundColor Green
    Write-Host "  - docType accettato: selfie" -ForegroundColor Green
    Write-Host "  - Upload URL valido: $($response.uploadUrl.Substring(0, 60))..." -ForegroundColor Green
    Write-Host "  - Scadenza: $($response.expiresSec) secondi" -ForegroundColor Green
    
    # Upload file (opzionale, se URL è valido)
    Write-Host "`n[2] Upload del selfie su S3..." -ForegroundColor Yellow
    $imageBytes = [System.IO.File]::ReadAllBytes($SelfiePath)
    $uploadHeaders = @{}
    foreach ($key in $response.requiredHeaders.PSObject.Properties.Name) {
        $uploadHeaders[$key] = $response.requiredHeaders.$key
    }
    
    $uploadResult = Invoke-RestMethod -Uri $response.uploadUrl `
        -Method PUT `
        -Body $imageBytes `
        -Headers $uploadHeaders
    
    Write-Host "✓ SUCCESSO! Selfie caricato su S3" -ForegroundColor Green
    
    Write-Host "`n===== TEST COMPLETATO =====" -ForegroundColor Green
    Write-Host "La modifica per supportare docType 'selfie' è FUNZIONANTE!" -ForegroundColor Green
    
} catch {
    Write-Host "✗ ERRORE!" -ForegroundColor Red
    Write-Host "Messaggio: $($_.Exception.Message)" -ForegroundColor Red
    
    if ($_.ErrorDetails.Message) {
        $err = $_.ErrorDetails.Message | ConvertFrom-Json
        Write-Host "  API Error: $($err.message)" -ForegroundColor Red
    }
    
    Write-Host "`nResponse:" -ForegroundColor Yellow
    Write-Host $_.Exception.Response -ForegroundColor Gray
    exit 1
}
