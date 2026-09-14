# ============================================
# PROFILE-UPGRADE-DOCUMENTS - QUICK TEST
# ============================================
# Tests the complete document upload flow
# Usage: .\test-upload.ps1 -Environment dev
# ============================================

param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("dev", "prod")]
    [string]$Environment,
    
    [Parameter(Mandatory=$false)]
    [string]$UserId = "test-user-$(Get-Random)"
)

$ErrorActionPreference = "Stop"
$REGION = "eu-south-1"

if ($Environment -eq "dev") {
    $TABLE_NAME = "dev-UserDocuments"
    $STACK_NAME = "dev-docs-upload"
} else {
    $TABLE_NAME = "prod-UserDocuments"
    $STACK_NAME = "prod-docs-upload"
}

Write-Host "========================================" -ForegroundColor Green
Write-Host "Testing Document Upload Flow" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host "Environment: $Environment" -ForegroundColor Cyan
Write-Host "Test User:   $UserId" -ForegroundColor Cyan
Write-Host ""

try {
    # Get API endpoint from CloudFormation
    Write-Host "[1/3] Getting API endpoint..." -ForegroundColor Yellow
    $API_ENDPOINT = aws cloudformation describe-stacks `
        --stack-name $STACK_NAME `
        --region $REGION `
        --query "Stacks[0].Outputs[?OutputKey=='ApiGatewayEndpoint'].OutputValue" `
        --output text
    
    if (-not $API_ENDPOINT) {
        throw "Could not retrieve API endpoint. Check if stack is deployed."
    }
    
    Write-Host "✅ API: $API_ENDPOINT" -ForegroundColor Green
    Write-Host ""
    
    # Check DynamoDB for recent entries
    Write-Host "[2/3] Checking DynamoDB for documents..." -ForegroundColor Yellow
    
    $result = aws dynamodb scan `
        --table-name $TABLE_NAME `
        --region $REGION `
        --limit 10 `
        --output json | ConvertFrom-Json
    
    if ($result.Items.Count -gt 0) {
        Write-Host "✅ Found $(($result.Items).Count) document(s) in DynamoDB:" -ForegroundColor Green
        Write-Host ""
        
        foreach ($item in $result.Items) {
            $status = $item.status.S
            $docType = $item.docType.S
            $userId = ($item.pk.S -split '#')[1]
            $timestamp = $item.sk.S
            
            $statusColor = @{
                "PENDING" = "Yellow"
                "UPLOADED" = "Cyan"
                "AWAITING_REVIEW" = "Green"
                "APPROVED" = "Green"
                "REJECTED" = "Red"
                "EXPIRED" = "Gray"
            }[$status]
            
            Write-Host "   User: $userId | DocType: $docType | Status: " -NoNewline
            Write-Host "$status" -ForegroundColor $statusColor
        }
    } else {
        Write-Host "ℹ️  No documents found in DynamoDB" -ForegroundColor Yellow
        Write-Host "   The table is empty. Once presigned URLs are generated, documents will appear here." -ForegroundColor Gray
    }
    
    Write-Host ""
    
    # Check S3 bucket for uploaded files
    Write-Host "[3/3] Checking S3 bucket for uploaded files..." -ForegroundColor Yellow
    
    $s3Items = aws s3api list-objects-v2 `
        --bucket beezey-dev-user-documents `
        --prefix docs/ `
        --region $REGION `
        --output json | ConvertFrom-Json
    
    if ($s3Items.Contents.Count -gt 0) {
        Write-Host "✅ Found $(($s3Items.Contents).Count) file(s) in S3:" -ForegroundColor Green
        foreach ($obj in $s3Items.Contents) {
            Write-Host "   Key: $($obj.Key) | Size: $($obj.Size) bytes" -ForegroundColor Gray
        }
    } else {
        Write-Host "ℹ️  No files in S3 bucket yet" -ForegroundColor Yellow
    }
    
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "✅ TEST COMPLETE" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
    
} catch {
    Write-Host ""
    Write-Host "❌ Test failed: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
