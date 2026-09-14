@echo off
REM ============================================
REM build.bat - Build del progetto SAM
REM ============================================

set environment=dev
REM set environment=prod

echo [INFO] Cleaning folder .aws-sam...
if exist .aws-sam rmdir /s /q .aws-sam

echo [INFO] Launching build with SAM...
REM ============================================ Environments: dev, prod ============================================
REM sam build --use-container --template-file infra\core\cognito-setup\template.yaml --config-file samconfig.toml --config-env %environment%
REM sam build --use-container --template-file infra\data\user-documents\template.yaml --config-file samconfig.toml --config-env %environment%
REM sam build --use-container --template-file infra\services\profile-upgrade-documents\template.yaml  --config-file samconfig.toml --config-env %environment%
REM sam build --use-container --template-file infra\services\profile-upgrade-request\template.yaml --config-file samconfig.toml --config-env %environment%
REM sam build --use-container --template-file infra\data\job-listings\template.yaml --config-file samconfig.toml --config-env %environment%
REM sam build --use-container --template-file infra\services\job-listings\template.yaml --config-file samconfig.toml --config-env %environment%
REM sam build --use-container --template-file infra\data\bookings\template.yaml --config-file samconfig.toml --config-env %environment%
REM sam build --use-container --template-file infra\services\bookings\template.yaml --config-file samconfig.toml --config-env %environment%
REM sam build --use-container --template-file infra\data\companies\template.yaml --config-file samconfig.toml --config-env %environment%
REM sam build --use-container --template-file infra\services\companies\template.yaml --config-file samconfig.toml --config-env %environment%
REM sam build --use-container --template-file infra\data\contracts\template.yaml --config-file samconfig.toml --config-env %environment%
REM sam build --use-container --template-file infra\services\contracts\template.yaml --config-file samconfig.toml --config-env %environment%
REM sam build --use-container --template-file infra\data\employment-types\template.yaml --config-file samconfig.toml --config-env %environment%
REM sam build --use-container --template-file infra\data\job-roles\template.yaml --config-file samconfig.toml --config-env %environment%
REM sam build --use-container --template-file infra\data\ateco-mapping\template.yaml --config-file samconfig.toml --config-env %environment%
REM sam build --use-container --template-file infra\services\reference-data-configuration\template.yaml --config-file samconfig.toml --config-env %environment%
REM sam build --use-container --template-file infra\services\backoffice\template.yaml --config-file samconfig.toml --config-env %environment%
REM sam build --use-container --template-file infra\data\user-profiles\template.yaml --config-file samconfig.toml --config-env %environment%
sam build --use-container --template-file infra\services\user-api\template.yaml --config-file samconfig.toml --config-env %environment%

if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] SAM build failed!
    exit /b %ERRORLEVEL%
)

echo [SUCCESS0] Build completed.