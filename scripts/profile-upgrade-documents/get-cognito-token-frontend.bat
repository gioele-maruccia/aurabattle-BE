@echo off
REM =============================================================================
REM Cognito Login Script - Generate JWT Token for API Testing
REM This script authenticates a user and retrieves the ID token
REM =============================================================================

setlocal enabledelayedexpansion

REM =============================================================================
REM CONFIGURATION - Update these variables with your Cognito settings
REM =============================================================================

REM Cognito User Pool configuration
set USER_POOL_ID=eu-south-1_MsYUCFinM
set CLIENT_ID=5aral6hab7r9ks4t2uf8mtejjg
set AWS_REGION=eu-south-1

REM User credentials (hardcode for testing - NOT for production!)
set USERNAME=diveradar24@gmail.com
set PASSWORD=DiveRadar@123

REM =============================================================================
REM SCRIPT START
REM =============================================================================

echo.
echo =============================================================================
echo Cognito Authentication - Generate JWT Token
echo =============================================================================
echo.

REM Check if AWS CLI is available
aws --version >nul 2>&1
if !errorlevel! neq 0 (
    echo ERROR: AWS CLI is not installed or not in PATH
    echo Please install AWS CLI to use this script
    pause
    exit /b 1
)

REM Check PowerShell availability
powershell -Command "Write-Host 'PowerShell OK'" >nul 2>&1
if !errorlevel! neq 0 (
    echo ERROR: PowerShell is not available
    pause
    exit /b 1
)

REM Validate configuration
if "%CLIENT_ID%"=="your-client-id-here" (
    echo ERROR: Please update CLIENT_ID in the script with your actual Cognito App Client ID
    echo You can find this in AWS Console: Cognito ^> User Pools ^> %USER_POOL_ID% ^> App clients
    pause
    exit /b 1
)

if "%USERNAME%"=="your-username-here" (
    echo ERROR: Please update USERNAME in the script with your test user credentials
    pause
    exit /b 1
)

if "%PASSWORD%"=="your-password-here" (
    echo ERROR: Please update PASSWORD in the script with your test user credentials
    pause
    exit /b 1
)

echo Configuration:
echo - User Pool ID: %USER_POOL_ID%
echo - Client ID: %CLIENT_ID%
echo - Region: %AWS_REGION%
echo - Username: %USERNAME%
echo - Password: [HIDDEN]
echo.

echo Authenticating with Cognito...
echo.

REM Temporary file for storing the response
set TEMP_FILE=%TEMP%\cognito_response.json

REM Authenticate with Cognito using AWS CLI
aws cognito-idp admin-initiate-auth ^
    --user-pool-id %USER_POOL_ID% ^
    --client-id %CLIENT_ID% ^
    --region %AWS_REGION% ^
    --auth-flow ADMIN_NO_SRP_AUTH ^
    --auth-parameters USERNAME=%USERNAME%,PASSWORD=%PASSWORD% ^
    --output json > "%TEMP_FILE%" 2>&1

if !errorlevel! neq 0 (
    echo ERROR: Authentication failed. Response:
    type "%TEMP_FILE%"
    del "%TEMP_FILE%" >nul 2>&1
    pause
    exit /b 1
)

echo Authentication successful!
echo.
echo Parsing response with PowerShell...
echo.

REM Use PowerShell to parse JSON and extract tokens
powershell -Command "& { ^
    try { ^
        $json = Get-Content '%TEMP_FILE%' | ConvertFrom-Json; ^
        $idToken = $json.AuthenticationResult.IdToken; ^
        $accessToken = $json.AuthenticationResult.AccessToken; ^
        $refreshToken = $json.AuthenticationResult.RefreshToken; ^
        ^
        Write-Host '============================================================================='; ^
        Write-Host 'TOKENS GENERATED SUCCESSFULLY'; ^
        Write-Host '============================================================================='; ^
        Write-Host ''; ^
        Write-Host 'ID TOKEN (use this for API calls):'; ^
        Write-Host $idToken; ^
        Write-Host ''; ^
        Write-Host 'ACCESS TOKEN:'; ^
        Write-Host ($accessToken.Substring(0, [Math]::Min(50, $accessToken.Length)) + '...'); ^
        Write-Host ''; ^
        Write-Host 'REFRESH TOKEN:'; ^
        Write-Host ($refreshToken.Substring(0, [Math]::Min(50, $refreshToken.Length)) + '...'); ^
        Write-Host ''; ^
        ^
        Write-Host 'Extracting User ID from ID token...'; ^
        try { ^
            $tokenParts = $idToken.Split('.'); ^
            $paddedPayload = $tokenParts[1]; ^
            while ($paddedPayload.Length %% 4 -ne 0) { $paddedPayload += '=' }; ^
            $payloadBytes = [Convert]::FromBase64String($paddedPayload); ^
            $payloadJson = [System.Text.Encoding]::UTF8.GetString($payloadBytes); ^
            $payload = $payloadJson | ConvertFrom-Json; ^
            Write-Host ''; ^
            Write-Host 'User Information:'; ^
            Write-Host ('User ID (sub): ' + $payload.sub); ^
            if ($payload.email) { Write-Host ('Email: ' + $payload.email) }; ^
            if ($payload.name) { Write-Host ('Name: ' + $payload.name) }; ^
            Write-Host ''; ^
            ^
            Write-Host '============================================================================='; ^
            Write-Host 'COPY THE VALUES BELOW TO USE IN test-api.bat'; ^
            Write-Host '============================================================================='; ^
            Write-Host ''; ^
            Write-Host 'JWT_TOKEN=' -NoNewline; Write-Host $idToken; ^
            Write-Host 'USER_ID=' -NoNewline; Write-Host $payload.sub; ^
        } catch { ^
            Write-Host 'Warning: Could not decode ID token payload'; ^
            Write-Host 'Please extract User ID manually from the token above'; ^
        } ^
    } catch { ^
        Write-Host 'ERROR: Failed to parse JSON response'; ^
        Write-Host 'Raw response:'; ^
        Get-Content '%TEMP_FILE%'; ^
    } ^
}"

REM Cleanup
del "%TEMP_FILE%" >nul 2>&1

echo.
echo =============================================================================
echo NEXT STEPS
echo =============================================================================
echo.
echo 1. Copy the JWT_TOKEN value from above
echo 2. Copy the USER_ID value from above  
echo 3. Update test-api.bat with these values
echo 4. Update the API_ENDPOINT in test-api.bat with your API Gateway URL
echo 5. Run test-api.bat to test the API
echo.

pause