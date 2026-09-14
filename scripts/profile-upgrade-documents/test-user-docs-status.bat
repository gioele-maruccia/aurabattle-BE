@echo off
REM =============================================================================
REM Test script for Documents API - DEV Environment
REM This script tests the get-user-docs-status API endpoint
REM All configuration is hardcoded in this file - NO external parameters
REM =============================================================================

setlocal enabledelayedexpansion

REM =============================================================================
REM HARDCODED CONFIGURATION - Update these values directly in the script
REM =============================================================================

REM API Gateway endpoint (replace with your actual endpoint from CloudFormation outputs)
set "API_ENDPOINT=https://9yg49cl3li.execute-api.eu-south-1.amazonaws.com/Stage/"

REM JWT ID Token (replace with your actual token - get this from Cognito manually)
set "JWT_TOKEN=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"

REM User ID (replace with your actual user ID - must match the 'sub' claim in JWT token)
set "USER_ID=12345678-1234-1234-1234-123456789abc"

REM =============================================================================
REM SCRIPT EXECUTION - DO NOT MODIFY BELOW THIS LINE
REM =============================================================================

echo.
echo =============================================================================
echo Testing Documents API - Get User Documents Status
echo =============================================================================
echo.

REM Check if curl is available
curl --version >nul 2>&1
if !errorlevel! neq 0 (
    echo ERROR: curl is not installed or not in PATH
    echo Please install curl to use this script
    echo Download from: https://curl.se/windows/
    pause
    exit /b 1
)

REM Build the full API URL
set "FULL_URL=%API_ENDPOINT%user/%USER_ID%/documents/status"

REM Display configuration (truncate token for security in console output)
echo Configuration:
echo - API Endpoint: %API_ENDPOINT%
echo - User ID: %USER_ID%
echo - Full URL: %FULL_URL%
echo - Token: %JWT_TOKEN:~0,30%...
echo.

echo Making API request...
echo.
echo =============================================================================

REM Make the API call with proper headers
curl -X GET "%FULL_URL%" ^
     -H "Content-Type: application/json" ^
     -H "Authorization: Bearer %JWT_TOKEN%" ^
     -w "\n\n=============================================================================\nHTTP Status Code: %%{http_code}\nTotal Time: %%{time_total} seconds\nResponse Size: %%{size_download} bytes\n=============================================================================\n" ^
     --silent ^
     --show-error

echo.

REM Check curl exit code
if !errorlevel! equ 0 (
    echo.
    echo ✓ API request completed successfully!
) else (
    echo.
    echo ✗ ERROR: API request failed
    echo.
    echo Please check:
    echo - API endpoint URL is correct
    echo - JWT token is valid and not expired
    echo - User ID matches the token's 'sub' claim
    echo - Internet connection is working
    echo - Lambda function is deployed correctly
)

echo.
echo =============================================================================
echo Test completed - Press any key to exit
echo =============================================================================
echo.

pause