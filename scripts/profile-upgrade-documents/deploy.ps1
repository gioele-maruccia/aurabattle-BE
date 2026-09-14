# ============================================
# PROFILE-UPGRADE-DOCUMENTS - AUTOMATIC SETUP
# ============================================
# Deploys CloudFormation stack AND configures
# S3 event notifications automatically.
# 
# Single command deployment - no manual steps!
# Usage: .\deploy.ps1 -Environment dev
# ============================================

param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("dev", "prod")]
    [string]$Environment,
    
    [Parameter(Mandatory=$false)]
    [switch]$SkipConfigFile
)

$ErrorActionPreference = "Stop"
$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommandPath
$REPO_ROOT = Split-Path -Parent (Split-Path -Parent $SCRIPT_DIR)
$INFRA_DIR = Join-Path $REPO_ROOT "infra\services\profile-upgrade-documents"

Write-Host "========================================" -ForegroundColor Green
Write-Host "Profile Upgrade Documents - Auto Setup" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host "Environment: $Environment" -ForegroundColor Cyan
Write-Host ""

# Determine configuration based on environment
if ($Environment -eq "dev") {
    $BUCKET = "beezey-dev-user-documents"
    $LAMBDA_FUNC = "dev-doc-received"
    $STACK_NAME = "dev-docs-upload"
} else {
    $BUCKET = "beezey-prod-user-documents"
    $LAMBDA_FUNC = "prod-doc-received"
    $STACK_NAME = "prod-docs-upload"
}

$REGION = "eu-south-1"

try {
    # Step 1: Check AWS credentials
    Write-Host "[1/4] Verifying AWS credentials..." -ForegroundColor Yellow
    $ACCOUNT_ID = aws sts get-caller-identity --query Account --output text 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "❌ AWS CLI not configured. Run: aws configure"
    }
    Write-Host "✅ AWS Account: $ACCOUNT_ID" -ForegroundColor Green
    Write-Host ""
    
    # Step 2: Deploy CloudFormation Stack
    Write-Host "[2/4] Deploying CloudFormation stack '$STACK_NAME'..." -ForegroundColor Yellow
    
    $prevLocation = Get-Location
    Set-Location $INFRA_DIR
    
    $deployCmd = "sam deploy --config-env $Environment --no-confirm-changeset"
    Write-Host "Running: $deployCmd" -ForegroundColor Gray
    Write-Host "Working directory: $(Get-Location)" -ForegroundColor Gray
    
    # SAM returns 1 for "no changes", which is OK
    Invoke-Expression $deployCmd -ErrorAction SilentlyContinue
    
    Set-Location $prevLocation
    Write-Host "✅ Stack deployed (or no changes needed)" -ForegroundColor Green
    Write-Host ""
    
    # Step 3: Get Lambda ARN from CloudFormation outputs
    Write-Host "[3/4] Retrieving Lambda ARN from stack outputs..." -ForegroundColor Yellow
    
    $stackOutputs = aws cloudformation describe-stacks `
        --stack-name $STACK_NAME `
        --region $REGION `
        --query "Stacks[0].Outputs[?OutputKey=='DocReceivedFunctionArn'].OutputValue" `
        --output text 2>$null
    
    if (-not $stackOutputs) {
        throw "❌ Could not retrieve DocReceivedFunctionArn from stack outputs"
    }
    
    $LAMBDA_ARN = $stackOutputs.Trim()
    Write-Host "✅ Lambda ARN: $LAMBDA_ARN" -ForegroundColor Green
    Write-Host ""
    
    # Step 4: Configure S3 Event Notification
    Write-Host "[4/4] Configuring S3 event notification..." -ForegroundColor Yellow
    
    $notificationConfig = @{
        LambdaFunctionConfigurations = @(
            @{
                LambdaFunctionArn = $LAMBDA_ARN
                Events = @("s3:ObjectCreated:*")
                Filter = @{
                    Key = @{
                        FilterRules = @(
                            @{
                                Name = "prefix"
                                Value = "docs/"
                            }
                        )
                    }
                }
            }
        )
    } | ConvertTo-Json -Depth 10
    
    # Create temporary file
    $tempFile = [System.IO.Path]::GetTempFileName()
    # Use UTF8 without BOM to avoid parsing issues with AWS CLI
    $encoding = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllText($tempFile, $notificationConfig, $encoding)
    
    try {
        # Apply notification configuration
        # Note: Use absolute path for AWS CLI on Windows
        $tempFilePath = (Resolve-Path $tempFile).Path
        Write-Host "Using config file: $tempFilePath" -ForegroundColor Gray
        
        # Debug: Show the JSON being sent
        Write-Host "JSON Config:" -ForegroundColor Cyan
        $notificationConfig
        Write-Host ""
        
        # On Windows, AWS CLI needs plain path (not file:// URI)
        $pathFormat = if ($PSVersionTable.Platform -eq "Win32NT" -or $PSVersionTable.OS -like "*Windows*") {
            $tempFilePath
        } else {
            "file://$tempFilePath"
        }
        
        # Invoke AWS CLI and capture both stdout and stderr
        $output = & aws s3api put-bucket-notification-configuration `
            --bucket $BUCKET `
            --notification-configuration $pathFormat `
            --region $REGION
        
        if ($LASTEXITCODE -ne 0) {
            Write-Host "AWS CLI output: $output" -ForegroundColor Red
            throw "Failed to configure S3 event notification (exit code: $LASTEXITCODE)"
        }
        
        Write-Host "✅ S3 event notification configured" -ForegroundColor Green
        
    } finally {
        Remove-Item $tempFile -Force -ErrorAction SilentlyContinue
    }
    
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "✅ SETUP COMPLETE!" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "Summary:" -ForegroundColor Yellow
    Write-Host "  Stack Name:        $STACK_NAME" -ForegroundColor Gray
    Write-Host "  Bucket:            $BUCKET" -ForegroundColor Gray
    Write-Host "  Lambda:            $LAMBDA_FUNC" -ForegroundColor Gray
    Write-Host "  Region:            $REGION" -ForegroundColor Gray
    Write-Host "  S3 Event Status:   ✅ Configured" -ForegroundColor Gray
    Write-Host ""
    Write-Host "Next steps:" -ForegroundColor Yellow
    Write-Host "  1. Test upload: .\test-upload.ps1 -Environment $Environment" -ForegroundColor Gray
    Write-Host "  2. Check logs:  aws logs tail /aws/lambda/$LAMBDA_FUNC --follow" -ForegroundColor Gray
    Write-Host ""
    
} catch {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Red
    Write-Host "❌ SETUP FAILED" -ForegroundColor Red
    Write-Host "========================================" -ForegroundColor Red
    Write-Host ""
    Write-Host "Error: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host ""
    Write-Host "Troubleshooting:" -ForegroundColor Yellow
    Write-Host "  • Verify AWS credentials: aws sts get-caller-identity" -ForegroundColor Gray
    Write-Host "  • Check stack status:     aws cloudformation describe-stacks --stack-name $STACK_NAME" -ForegroundColor Gray
    Write-Host "  • Review SAM template:    $INFRA_DIR\template.yaml" -ForegroundColor Gray
    Write-Host ""
    exit 1
}
