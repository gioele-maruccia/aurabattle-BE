
echo ===============================================
echo    Getting Cognito JWT Token for Testing
echo ===============================================
echo.

REM Set your Cognito configuration here  
set COGNITO_CLIENT_ID=6c3jgvgkk28uurt2qvqf697v5k
set COGNITO_USER_POOL_ID=eu-south-1_Vfr0FKYfO
set REGION=eu-south-1

REM Load from config file if exists
if exist cognito-config.txt (
    echo Loading configuration from cognito-config.txt...
    for /f "tokens=1,2 delims==" %%a in (cognito-config.txt) do (
        if "%%a"=="CLIENT_ID" set COGNITO_CLIENT_ID=%%b
        if "%%a"=="USER_POOL_ID" set COGNITO_USER_POOL_ID=%%b
        if "%%a"=="REGION" set REGION=%%b
    )
)

echo Using configuration:
echo - User Pool ID: %COGNITO_USER_POOL_ID%
echo - Client ID: %COGNITO_CLIENT_ID%
echo - Region: %REGION%
echo.

if "%COGNITO_CLIENT_ID%"=="your-cognito-client-id" (
    echo ERROR: Client ID not configured!
    echo Please run get-client-id.bat first to get the correct Client ID.
    pause
    exit /b 1
)

echo Please enter your backoffice credentials:
set /p USERNAME="Username: "
set /p PASSWORD="Password: "

echo.
echo Authenticating with Cognito...

REM Use AWS CLI to authenticate and get tokens
aws cognito-idp admin-initiate-auth ^
    --user-pool-id %COGNITO_USER_POOL_ID% ^
    --client-id %COGNITO_CLIENT_ID% ^
    --auth-flow ADMIN_NO_SRP_AUTH ^
    --auth-parameters USERNAME=%USERNAME%,PASSWORD=%PASSWORD% ^
    --region %REGION% ^
    --output json > cognito-response.json

if %ERRORLEVEL% neq 0 (
    echo ERROR: Authentication failed!
    pause
    exit /b 1
)

REM Extract the ID Token (not Access Token!) using PowerShell
powershell -Command "(Get-Content cognito-response.json | ConvertFrom-Json).AuthenticationResult.IdToken" | powershell -Command "$input | ForEach-Object { $_.Trim() }" > jwt-token.txt

REM Also save access token for reference
powershell -Command "(Get-Content cognito-response.json | ConvertFrom-Json).AuthenticationResult.AccessToken" | powershell -Command "$input | ForEach-Object { $_.Trim() }" > access-token.txt

if exist jwt-token.txt (
    echo.
    echo SUCCESS: ID Token saved to jwt-token.txt
    echo Access Token saved to access-token.txt
    echo.
    echo For API Gateway with Cognito User Pools, use the ID Token!
    echo.
    echo Token info:
    powershell -Command ^
        "$token = (Get-Content jwt-token.txt -Raw).Trim(); ^
         $payload = $token.Split('.')[1]; ^
         $decoded = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String($payload + '=='.Substring(0, (4 - $payload.Length %% 4) %% 4))); ^
         $json = $decoded | ConvertFrom-Json; ^
         Write-Host '- Type:' $json.token_use; ^
         Write-Host '- Email:' $json.email; ^
         Write-Host '- Expires:' ([DateTimeOffset]::FromUnixTimeSeconds($json.exp).ToString('yyyy-MM-dd HH:mm:ss'))"
    echo.
    echo You can now use this token for testing!
) else (
    echo ERROR: Could not extract ID token
)

REM Cleanup
del cognito-response.json 2>nul

echo.
echo Press any key to continue...
pause