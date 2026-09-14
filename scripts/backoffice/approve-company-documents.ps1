# ============================================
# APPROVE COMPANY DOCUMENTS - Backoffice Script
# ============================================
# Approva tutti i documenti di un'azienda che ha richiesto l'upgrade
# e triggera la promozione automatica a "company" con creazione del record aziendale
# ============================================

param(
    [Parameter(Mandatory=$false)]
    [string]$TargetUserEmail,
    
    [Parameter(Mandatory=$false)]
    [string]$BackofficeEmail = "gioelemaruccia8@gmail.com",
    
    [Parameter(Mandatory=$false)]
    [string]$BackofficePassword = "Password@1",
    
    [Parameter(Mandatory=$false)]
    [string]$Environment = "dev"
)

$ErrorActionPreference = "Stop"

# Configurazione
$COGNITO_CLIENT_ID = "79g67hnuepfuoh1fnk4d98jfpu"
$COGNITO_USER_POOL_ID = "eu-south-1_0oK9agPYd"
$REGION = "eu-south-1"
$BACKOFFICE_API_BASE = "https://v7m02xrzyh.execute-api.eu-south-1.amazonaws.com/dev"
$DOCUMENTS_TABLE = "dev-UserDocuments"

# Se non è specificato l'utente, chiedi input
if (-not $TargetUserEmail) {
    Write-Host ""
    $TargetUserEmail = Read-Host "Inserisci l'email dell'utente da approvare"
    if (-not $TargetUserEmail) {
        Write-Host "❌ Email utente richiesta!" -ForegroundColor Red
        exit 1
    }
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  APPROVE COMPANY DOCUMENTS" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "Backoffice User: $BackofficeEmail" -ForegroundColor Yellow
Write-Host "Target User: $TargetUserEmail" -ForegroundColor Yellow
Write-Host "Environment: $Environment" -ForegroundColor Yellow
Write-Host ""

# ============================================
# STEP 1: Login backoffice user
# ============================================
Write-Host "[1/5] Login backoffice user..." -ForegroundColor Green
try {
    $authResult = aws cognito-idp initiate-auth `
        --auth-flow USER_PASSWORD_AUTH `
        --client-id $COGNITO_CLIENT_ID `
        --auth-parameters "USERNAME=$BackofficeEmail,PASSWORD=$BackofficePassword" `
        --region $REGION `
        --output json | ConvertFrom-Json
    
    if (-not $authResult.AuthenticationResult) {
        throw "Login failed - no authentication result"
    }
    
    $idToken = $authResult.AuthenticationResult.IdToken
    Write-Host "✅ Login successful" -ForegroundColor Green
} catch {
    Write-Host "❌ Login failed!" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}

Write-Host ""

# ============================================
# STEP 2: Get target user's sub
# ============================================
Write-Host "[2/5] Get target user sub..." -ForegroundColor Green
try {
    $userInfo = aws cognito-idp admin-get-user `
        --user-pool-id $COGNITO_USER_POOL_ID `
        --username $TargetUserEmail `
        --region $REGION `
        --output json | ConvertFrom-Json
    
    $userSub = ($userInfo.UserAttributes | Where-Object { $_.Name -eq "sub" }).Value
    $profileType = ($userInfo.UserAttributes | Where-Object { $_.Name -eq "custom:profile_type" }).Value
    $verificationStatus = ($userInfo.UserAttributes | Where-Object { $_.Name -eq "custom:verification_status" }).Value
    
    Write-Host "✅ User found:" -ForegroundColor Green
    Write-Host "   Sub: $userSub" -ForegroundColor Gray
    Write-Host "   Profile Type: $profileType" -ForegroundColor Gray
    Write-Host "   Verification Status: $verificationStatus" -ForegroundColor Gray
} catch {
    Write-Host "❌ Failed to get user info!" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}

Write-Host ""

# ============================================
# STEP 3: Get user's documents
# ============================================
Write-Host "[3/5] Get user's documents..." -ForegroundColor Green
$documentsEndpoint = "$BACKOFFICE_API_BASE/documents/user/$userSub"

try {
    $documentsResponse = Invoke-RestMethod -Uri $documentsEndpoint `
        -Method GET `
        -Headers @{
            "Authorization" = "Bearer $idToken"
        }
    
    $allDocs = $documentsResponse.documents
    $pendingDocs = $allDocs | Where-Object { $_.status -eq "AWAITING_REVIEW" }
    
    Write-Host "✅ Found $($allDocs.Count) documents total" -ForegroundColor Green
    Write-Host "   Pending review: $($pendingDocs.Count)" -ForegroundColor Yellow
    Write-Host ""
    
    # Mostra tutti i documenti
    Write-Host "   Document status:" -ForegroundColor Cyan
    $allDocs | ForEach-Object {
        $icon = if ($_.status -eq "APPROVED") { "✅" } elseif ($_.status -eq "REJECTED") { "❌" } else { "⏳" }
        Write-Host "   $icon $($_.docType): $($_.status)" -ForegroundColor Gray
    }
    
    Write-Host ""
    
} catch {
    Write-Host "❌ Failed to get documents!" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}

# ============================================
# STEP 4: Approve pending documents
# ============================================
Write-Host "[4/5] Approve documents..." -ForegroundColor Green

if ($pendingDocs.Count -eq 0) {
    Write-Host "   ⚠️  No pending documents found" -ForegroundColor Yellow
    
    # Se l'utente è company e tutti i documenti sono approvati ma non è stato promosso,
    # resettiamo e riapproviamo un documento per triggerare la verifica
    if ($profileType -eq "company" -and $verificationStatus -ne "approved") {
        Write-Host ""
        Write-Host "   🔄 User is company but not approved - retriggering verification..." -ForegroundColor Yellow
        
        # Resetta il selfie a AWAITING_REVIEW in DynamoDB
        $selfieDoc = $allDocs | Where-Object { $_.docType -eq "selfie" } | Select-Object -First 1
        
        if ($selfieDoc) {
            Write-Host "   Resetting selfie to AWAITING_REVIEW..." -ForegroundColor Gray
            
            $pk = "USER#$userSub"
            $sk = "DOC#selfie#$($selfieDoc.timestamp)"
            
            $keyJson = @{
                pk = @{ S = $pk }
                sk = @{ S = $sk }
            } | ConvertTo-Json -Compress
            
            aws dynamodb update-item `
                --table-name $DOCUMENTS_TABLE `
                --key $keyJson `
                --update-expression "SET #status = :status" `
                --expression-attribute-names '{\"#status\":\"status\"}' `
                --expression-attribute-values '{\":status\":{\"S\":\"AWAITING_REVIEW\"}}' `
                --region $REGION | Out-Null
            
            # Ricarica i documenti
            Start-Sleep -Seconds 1
            $documentsResponse = Invoke-RestMethod -Uri $documentsEndpoint `
                -Method GET `
                -Headers @{ "Authorization" = "Bearer $idToken" }
            
            $pendingDocs = $documentsResponse.documents | Where-Object { $_.status -eq "AWAITING_REVIEW" }
            Write-Host "   ✅ Selfie reset to AWAITING_REVIEW" -ForegroundColor Green
            Write-Host ""
        }
    } else {
        Write-Host ""
        Write-Host "   All documents already approved and user already promoted." -ForegroundColor Green
        Write-Host ""
        Write-Host "============================================" -ForegroundColor Green
        Write-Host "✅ NOTHING TO DO - USER ALREADY APPROVED" -ForegroundColor Green
        Write-Host "============================================" -ForegroundColor Green
        exit 0
    }
}

# Approva tutti i documenti pending
$promotionResult = $null

foreach ($doc in $pendingDocs) {
    Write-Host "   Approving: $($doc.docType)..." -ForegroundColor Gray
    
    $approveEndpoint = "$BACKOFFICE_API_BASE/documents/$userSub/$($doc.documentId)/status"
    $approveBody = @{
        status = "APPROVED"
        notes = "Approved by backoffice admin"
    } | ConvertTo-Json
    
    try {
        $approveResponse = Invoke-RestMethod -Uri $approveEndpoint `
            -Method PUT `
            -Headers @{
                "Content-Type" = "application/json"
                "Authorization" = "Bearer $idToken"
            } `
            -Body $approveBody
        
        Write-Host "   ✅ Approved: $($doc.docType)" -ForegroundColor Green
        
        # Salva il risultato della promozione se presente
        if ($approveResponse.userVerification) {
            $promotionResult = $approveResponse.userVerification
        }
        
    } catch {
        Write-Host "   ❌ Failed to approve $($doc.docType)" -ForegroundColor Red
        Write-Host "   $($_.Exception.Message)" -ForegroundColor Red
    }
}

Write-Host ""

# ============================================
# STEP 5: Verify final status
# ============================================
Write-Host "[5/5] Verify final status..." -ForegroundColor Green

try {
    $userInfo = aws cognito-idp admin-get-user `
        --user-pool-id $COGNITO_USER_POOL_ID `
        --username $TargetUserEmail `
        --region $REGION `
        --output json | ConvertFrom-Json
    
    $finalProfileType = ($userInfo.UserAttributes | Where-Object { $_.Name -eq "custom:profile_type" }).Value
    $finalVerificationStatus = ($userInfo.UserAttributes | Where-Object { $_.Name -eq "custom:verification_status" }).Value
    
    $groups = aws cognito-idp admin-list-groups-for-user `
        --user-pool-id $COGNITO_USER_POOL_ID `
        --username $userSub `
        --region $REGION `
        --output json | ConvertFrom-Json
    
    $groupNames = $groups.Groups | ForEach-Object { $_.GroupName }
    
    Write-Host ""
    Write-Host "============================================" -ForegroundColor Green
    Write-Host "✅ APPROVAL COMPLETED SUCCESSFULLY" -ForegroundColor Green
    Write-Host "============================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "Final Status:" -ForegroundColor Cyan
    Write-Host "  Profile Type: $finalProfileType" -ForegroundColor Yellow
    Write-Host "  Verification Status: $finalVerificationStatus" -ForegroundColor Yellow
    Write-Host "  Groups: $($groupNames -join ', ')" -ForegroundColor Yellow
    
    # Se c'è stata una promozione, mostra i dettagli
    if ($promotionResult) {
        Write-Host ""
        Write-Host "Promotion Details:" -ForegroundColor Cyan
        Write-Host "  Action: $($promotionResult.action)" -ForegroundColor Yellow
        Write-Host "  Group: $($promotionResult.group)" -ForegroundColor Yellow
        Write-Host "  Reason: $($promotionResult.reason)" -ForegroundColor Yellow
        
        if ($promotionResult.companyId) {
            Write-Host ""
            Write-Host "🎉 Company Record Created!" -ForegroundColor Magenta
            Write-Host "  Company ID: $($promotionResult.companyId)" -ForegroundColor Yellow
        }
    }
    
    Write-Host ""
    
} catch {
    Write-Host "⚠️  Could not verify final status" -ForegroundColor Yellow
    Write-Host $_.Exception.Message -ForegroundColor Gray
}
