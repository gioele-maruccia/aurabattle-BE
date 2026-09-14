@echo off
setlocal enabledelayedexpansion

echo ===============================================
echo    Testing API Gateway Authorization
echo ===============================================
echo.

REM Get API endpoint
set API_ENDPOINT=https://l0v4idxhd1.execute-api.eu-south-1.amazonaws.com/dev

echo Checking for saved API endpoint...
if exist api-endpoint.txt (
    set /p API_ENDPOINT=<api-endpoint.txt
    echo Using saved endpoint: %API_ENDPOINT%
) else (
    echo No saved endpoint found. Using default: %API_ENDPOINT%
    echo Run get-api-endpoint.bat to get the correct endpoint automatically.
)

echo.
echo Testing different authorization scenarios...
echo.

echo 1. Testing WITHOUT Authorization header (should fail with 401)
echo ================================================================
curl -X GET "%API_ENDPOINT%/documents" ^
     -H "Content-Type: application/json" ^
     -w "\nHTTP Status: %%{http_code}\n" ^
     -s

echo.
echo 2. Testing with INVALID token (should fail with 401/403)
echo ========================================================
curl -X GET "%API_ENDPOINT%/documents" ^
     -H "Authorization: Bearer invalid-token-123" ^
     -H "Content-Type: application/json" ^
     -w "\nHTTP Status: %%{http_code}\n" ^
     -s

echo.
echo 3. Testing CORS preflight (should work without auth)
echo ====================================================
curl -X OPTIONS "%API_ENDPOINT%/documents" ^
     -H "Origin: https://yourbackoffice.com" ^
     -H "Access-Control-Request-Method: GET" ^
     -H "Access-Control-Request-Headers: Authorization" ^
     -w "\nHTTP Status: %%{http_code}\n" ^
     -v

echo.
if exist jwt-token.txt (
    echo 4. Testing with VALID JWT token (should succeed)
    echo ================================================
    REM set /p JWT_TOKEN=<jwt-token.txt
	set JWT_TOKEN=eyJraWQiOiJ1SUY5M2x6dUdySGtOOWpUNHhzZlRKdmptQ1I2UFwvVWlFWk1vdjZLUk9MOD0iLCJhbGciOiJSUzI1NiJ9.eyJzdWIiOiI4NjVlYjJiMC1kMGIxLTcwODEtMGFlNi0wZjM2ZTA1ODRjMmUiLCJpc3MiOiJodHRwczpcL1wvY29nbml0by1pZHAuZXUtc291dGgtMS5hbWF6b25hd3MuY29tXC9ldS1zb3V0aC0xX1ZmcjBGS1lmTyIsImNvZ25pdG86dXNlcm5hbWUiOiI4NjVlYjJiMC1kMGIxLTcwODEtMGFlNi0wZjM2ZTA1ODRjMmUiLCJvcmlnaW5fanRpIjoiNTg3ZGI3ZDUtNjJkOS00ZmQ5LWI2YjItNjVlMmEzOGU2MTdlIiwiYXVkIjoiNmMzamd2Z2trMjh1dXJ0MnF2cWY2OTd2NWsiLCJldmVudF9pZCI6IjQxYzFjMjQ4LWFlN2EtNDY3Yy05NTA3LWM2ZDQzNDEwZWZjNSIsInRva2VuX3VzZSI6ImlkIiwiYXV0aF90aW1lIjoxNzU4MTAzOTYzLCJleHAiOjE3NTgxMDc1NjMsImlhdCI6MTc1ODEwMzk2MywianRpIjoiMGY4YjQzYWYtZDI0NC00YjE3LWE2N2YtNmZhZDljN2NhNTIzIiwiZW1haWwiOiJpcGhvbmUuYWxlOTNAZ21haWwuY29tIn0.UJPe2pmNjRtVMmFhVMEuEG1AGfpUhnS2IGtnFTguP-3ODcGlWF7bAcVLsempxygmyFVSTo8BP9sLc-pl6v6W26geMSQ7RcZFhGhf425gX5hCS2IyUtLs-AttVBgdSLMfbuAI4pjaTiW_bA7-QVeYVkA-P70miLKzI1R68yCui_EOHSAZaFWhP-7wxKidS6jRqZQVEg6LYyTOtuJti1QEqJ0px9bmI7DpzqItbsqlf0-lDTO64al-CMAb_Klgo_UCSYFesvT4lQIjc2q7laQ3aMA1Zi_2rapI1voOuMg_b1uIxVH3RqqgRWh8WpIhpjI8sEefUmpyNoFBudPZBidIOw


	echo %JWT_TOKEN%
    curl -X GET "%API_ENDPOINT%/documents?limit=1" ^
         -H "Authorization: Bearer !JWT_TOKEN!" ^
         -H "Content-Type: application/json" ^
         -w "\nHTTP Status: %%{http_code}\n" ^
         -s
) else (
    echo 4. SKIPPED - No JWT token found
    echo ================================
    echo Run get-cognito-token.bat first to test with valid token
)

echo.
echo ===============================================
echo Authorization Test Results Summary:
echo ===============================================
echo.
echo Expected results:
echo - Test 1 (no auth): 401 Unauthorized
echo - Test 2 (invalid): 401/403 Unauthorized/Forbidden  
echo - Test 3 (CORS): 200 OK with CORS headers
echo - Test 4 (valid): 200 OK with data
echo.
echo If you see different results:
echo.
echo 🔸 500 errors = Lambda function issues (check CloudWatch logs)
echo 🔸 403 errors = Cognito User Pool misconfiguration
echo 🔸 CORS errors = Missing CORS headers (check browser console)
echo 🔸 Timeout = API Gateway or Lambda timeout issues
echo.

echo Troubleshooting steps:
echo.
echo 1. Verify Cognito configuration:
echo    run verify-cognito-config.bat
echo.
echo 2. Check API Gateway logs:
echo    AWS Console ^> API Gateway ^> Your API ^> Stages ^> dev ^> Logs
echo.
echo 3. Check Lambda logs:
echo    AWS Console ^> CloudWatch ^> Log Groups ^> /aws/lambda/backoffice-list-documents
echo.
echo 4. Verify JWT token:
echo    Use jwt.io to decode and check claims
echo.
pause