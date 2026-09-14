@echo off
setlocal enabledelayedexpansion

REM ============================================================================
REM Script per esportare TUTTA la configurazione di un User Pool Cognito
REM ============================================================================

set REGION=eu-south-1
set USER_POOL_ID=eu-south-1_MsYUCFinM
set OUTPUT_DIR=cognito_export_%date:~-4%%date:~3,2%%date:~0,2%_%time:~0,2%%time:~3,2%%time:~6,2%
set OUTPUT_DIR=%OUTPUT_DIR: =0%

echo.
echo ============================================================================
echo   EXPORT CONFIGURAZIONE COGNITO USER POOL
echo ============================================================================
echo   User Pool ID: %USER_POOL_ID%
echo   Region: %REGION%
echo   Output Directory: %OUTPUT_DIR%
echo ============================================================================
echo.

REM Crea la directory di output
mkdir "%OUTPUT_DIR%" 2>nul

REM ============================================================================
REM 1. CONFIGURAZIONE PRINCIPALE USER POOL
REM ============================================================================
echo [1/10] Esportazione configurazione principale User Pool...
aws cognito-idp describe-user-pool ^
    --user-pool-id %USER_POOL_ID% ^
    --region %REGION% ^
    > "%OUTPUT_DIR%\01_user_pool_config.json"

if %errorlevel% equ 0 (
    echo    [OK] Configurazione principale salvata
) else (
    echo    [ERRORE] Impossibile recuperare la configurazione principale
)

REM ============================================================================
REM 2. SCHEMA ATTRIBUTI
REM ============================================================================
echo [2/10] Esportazione schema attributi...
aws cognito-idp describe-user-pool ^
    --user-pool-id %USER_POOL_ID% ^
    --region %REGION% ^
    --query "UserPool.SchemaAttributes" ^
    > "%OUTPUT_DIR%\02_schema_attributes.json"

echo    [OK] Schema attributi salvato

REM ============================================================================
REM 3. USER POOL CLIENTS
REM ============================================================================
echo [3/10] Esportazione User Pool Clients...
aws cognito-idp list-user-pool-clients ^
    --user-pool-id %USER_POOL_ID% ^
    --region %REGION% ^
    --max-results 60 ^
    > "%OUTPUT_DIR%\03_user_pool_clients_list.json"

echo    [OK] Lista clients salvata

REM Estrai i dettagli di ogni client
echo [3/10] Esportazione dettagli di ogni client...
for /f "tokens=*" %%i in ('aws cognito-idp list-user-pool-clients --user-pool-id %USER_POOL_ID% --region %REGION% --query "UserPoolClients[*].ClientId" --output text') do (
    echo    - Esportazione client: %%i
    aws cognito-idp describe-user-pool-client ^
        --user-pool-id %USER_POOL_ID% ^
        --client-id %%i ^
        --region %REGION% ^
        > "%OUTPUT_DIR%\03_client_%%i.json"
)

REM ============================================================================
REM 4. GRUPPI
REM ============================================================================
echo [4/10] Esportazione gruppi...
aws cognito-idp list-groups ^
    --user-pool-id %USER_POOL_ID% ^
    --region %REGION% ^
    > "%OUTPUT_DIR%\04_groups.json"

echo    [OK] Gruppi salvati

REM ============================================================================
REM 5. IDENTITY PROVIDERS
REM ============================================================================
echo [5/10] Esportazione Identity Providers...
aws cognito-idp list-identity-providers ^
    --user-pool-id %USER_POOL_ID% ^
    --region %REGION% ^
    --max-results 60 ^
    > "%OUTPUT_DIR%\05_identity_providers.json" 2>nul

echo    [OK] Identity providers salvati

REM ============================================================================
REM 6. RESOURCE SERVERS
REM ============================================================================
echo [6/10] Esportazione Resource Servers...
aws cognito-idp list-resource-servers ^
    --user-pool-id %USER_POOL_ID% ^
    --region %REGION% ^
    --max-results 50 ^
    > "%OUTPUT_DIR%\06_resource_servers.json"

echo    [OK] Resource servers salvati

REM ============================================================================
REM 7. USER IMPORT JOBS (se presenti)
REM ============================================================================
echo [7/10] Esportazione User Import Jobs...
aws cognito-idp list-user-import-jobs ^
    --user-pool-id %USER_POOL_ID% ^
    --region %REGION% ^
    --max-results 60 ^
    > "%OUTPUT_DIR%\07_user_import_jobs.json"

echo    [OK] User import jobs salvati

REM ============================================================================
REM 8. STATISTICHE UTENTI
REM ============================================================================
echo [8/10] Esportazione statistiche utenti...
aws cognito-idp list-users ^
    --user-pool-id %USER_POOL_ID% ^
    --region %REGION% ^
    --limit 60 ^
    > "%OUTPUT_DIR%\08_users_sample.json"

echo    [OK] Sample utenti salvato (primi 60)

REM ============================================================================
REM 9. TAGS
REM ============================================================================
echo [9/10] Esportazione tags...
aws cognito-idp list-tags-for-resource ^
    --resource-arn arn:aws:cognito-idp:%REGION%:%aws sts get-caller-identity --query Account --output text%:userpool/%USER_POOL_ID% ^
    --region %REGION% ^
    > "%OUTPUT_DIR%\09_tags.json" 2>nul

echo    [OK] Tags salvati

REM ============================================================================
REM 10. CONFIGURAZIONE MFA
REM ============================================================================
echo [10/10] Esportazione configurazione MFA...
aws cognito-idp get-user-pool-mfa-config ^
    --user-pool-id %USER_POOL_ID% ^
    --region %REGION% ^
    > "%OUTPUT_DIR%\10_mfa_config.json"

echo    [OK] Configurazione MFA salvata

REM ============================================================================
REM CREAZIONE REPORT RIASSUNTIVO
REM ============================================================================
echo.
echo Creazione report riassuntivo...

(
echo ============================================================================
echo   REPORT CONFIGURAZIONE COGNITO USER POOL
echo ============================================================================
echo   User Pool ID: %USER_POOL_ID%
echo   Region: %REGION%
echo   Data Export: %date% %time%
echo ============================================================================
echo.
echo.
echo CONFIGURAZIONE PRINCIPALE:
echo ----------------------------
type "%OUTPUT_DIR%\01_user_pool_config.json"
echo.
echo.
echo SCHEMA ATTRIBUTI:
echo ----------------------------
type "%OUTPUT_DIR%\02_schema_attributes.json"
echo.
echo.
echo USER POOL CLIENTS:
echo ----------------------------
type "%OUTPUT_DIR%\03_user_pool_clients_list.json"
echo.
echo.
echo GRUPPI:
echo ----------------------------
type "%OUTPUT_DIR%\04_groups.json"
echo.
echo.
echo IDENTITY PROVIDERS:
echo ----------------------------
type "%OUTPUT_DIR%\05_identity_providers.json"
echo.
echo.
echo RESOURCE SERVERS:
echo ----------------------------
type "%OUTPUT_DIR%\06_resource_servers.json"
echo.
echo.
echo MFA CONFIGURATION:
echo ----------------------------
type "%OUTPUT_DIR%\10_mfa_config.json"
echo.
) > "%OUTPUT_DIR%\00_FULL_REPORT.txt"

echo    [OK] Report riassuntivo creato

REM ============================================================================
REM SUMMARY
REM ============================================================================
echo.
echo ============================================================================
echo   EXPORT COMPLETATO!
echo ============================================================================
echo   Tutti i file sono stati salvati in: %OUTPUT_DIR%
echo.
echo   File principali:
echo   - 00_FULL_REPORT.txt        : Report completo
echo   - 01_user_pool_config.json  : Configurazione principale
echo   - 02_schema_attributes.json : Schema attributi
echo   - 03_*.json                 : Clients
echo   - 04_groups.json            : Gruppi
echo   - 08_users_sample.json      : Sample utenti
echo.
echo   Apri la cartella per vedere tutti i dettagli!
echo ============================================================================
echo.

REM Apri la cartella di output
start "" "%OUTPUT_DIR%"

pause