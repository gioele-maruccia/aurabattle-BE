@echo off
REM ============================================
REM Pre-deployment verification for Chat system
REM ============================================

echo.
echo ============================================
echo   CHAT SYSTEM - PRE-DEPLOYMENT CHECK
echo ============================================
echo.

set ERROR_COUNT=0

REM Check Lambda functions exist
echo [1/5] Checking Lambda functions...
set LAMBDAS=create-chat get-my-chats get-messages send-message update-message-state set-sticker get-upload-url request-beezey-help

for %%L in (%LAMBDAS%) do (
    if exist "src\lambdas\services\chat\%%L\app.py" (
        echo   [OK] %%L
    ) else (
        echo   [ERROR] %%L missing!
        set /a ERROR_COUNT+=1
    )
)

REM Check Layer files
echo.
echo [2/5] Checking shared layer...
if exist "src\lambdas\layers\chat-shared\python\models.py" (
    echo   [OK] models.py
) else (
    echo   [ERROR] models.py missing!
    set /a ERROR_COUNT+=1
)

if exist "src\lambdas\layers\chat-shared\python\db_manager.py" (
    echo   [OK] db_manager.py
) else (
    echo   [ERROR] db_manager.py missing!
    set /a ERROR_COUNT+=1
)

if exist "src\lambdas\layers\chat-shared\python\requirements.txt" (
    echo   [OK] requirements.txt
) else (
    echo   [ERROR] requirements.txt missing!
    set /a ERROR_COUNT+=1
)

REM Check infrastructure templates
echo.
echo [3/5] Checking infrastructure templates...
if exist "infra\data\chat\template.yaml" (
    echo   [OK] data/chat/template.yaml
) else (
    echo   [ERROR] data/chat/template.yaml missing!
    set /a ERROR_COUNT+=1
)

if exist "infra\data\chat\samconfig.toml" (
    echo   [OK] data/chat/samconfig.toml
) else (
    echo   [ERROR] data/chat/samconfig.toml missing!
    set /a ERROR_COUNT+=1
)

if exist "infra\services\chat\template.yaml" (
    echo   [OK] services/chat/template.yaml
) else (
    echo   [ERROR] services/chat/template.yaml missing!
    set /a ERROR_COUNT+=1
)

if exist "infra\services\chat\samconfig.toml" (
    echo   [OK] services/chat/samconfig.toml
) else (
    echo   [ERROR] services/chat/samconfig.toml missing!
    set /a ERROR_COUNT+=1
)

REM Check test scripts
echo.
echo [4/5] Checking test scripts...
set TESTS=complete-test-setup test-file-upload test-set-sticker test-get-my-chats worker-chat company-chat

for %%T in (%TESTS%) do (
    if exist "scripts\chat\%%T.ps1" (
        echo   [OK] %%T.ps1
    ) else (
        echo   [ERROR] %%T.ps1 missing!
        set /a ERROR_COUNT+=1
    )
)

REM Check Swagger documentation
echo.
echo [5/5] Checking Swagger documentation...
if exist "swagger\swagger-bundled.yml" (
    echo   [OK] swagger-bundled.yml
) else (
    echo   [ERROR] swagger-bundled.yml missing!
    set /a ERROR_COUNT+=1
)

if exist "swagger\paths\chat\get-my-chats.yml" (
    echo   [OK] paths/chat/get-my-chats.yml
) else (
    echo   [ERROR] paths/chat/get-my-chats.yml missing!
    set /a ERROR_COUNT+=1
)

REM Summary
echo.
echo ============================================
if %ERROR_COUNT% EQU 0 (
    echo   [SUCCESS] All checks passed!
    echo   Ready to deploy with: scripts\deploy-chat.bat
    echo ============================================
    exit /b 0
) else (
    echo   [FAILED] Found %ERROR_COUNT% errors
    echo   Please fix errors before deploying
    echo ============================================
    exit /b 1
)
