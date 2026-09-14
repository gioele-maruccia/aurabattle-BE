@echo off
REM ============================================
REM deploy-dev.bat - Deploy environment DEV
REM ============================================

REM ====================================================================
set environment=dev
REM set environment=prod

REM ====================================================================
set FOLDER=services
REM set FOLDER=core
REM set FOLDER=data

REM ==================================================================== CORE
REM set STACK_NAME=cognito-setup

REM ==================================================================== DATA
REM set STACK_NAME=user-documents
REM set STACK_NAME=job-listings
REM set STACK_NAME=bookings
REM set STACK_NAME=companies
REM set STACK_NAME=contracts
REM set STACK_NAME=employment-types
REM set STACK_NAME=job-roles
REM set STACK_NAME=ateco-mapping
REM set STACK_NAME=user-profiles

REM ==================================================================== SERVICES
REM set STACK_NAME=profile-upgrade-documents
REM set STACK_NAME=profile-upgrade-request
REM set STACK_NAME=job-listings
REM set STACK_NAME=bookings
REM set STACK_NAME=companies
REM set STACK_NAME=contracts
REM set STACK_NAME=reference-data-configuration
REM set STACK_NAME=backoffice
REM set STACK_NAME=user-api
set STACK_NAME=chat

REM ==================================================================== 

REM ====================================================================
set REGION=eu-south-1

REM echo Eliminando lo stack %STACK_NAME%...
REM aws cloudformation delete-stack --stack-name %STACK_NAME% --region %REGION%

REM echo Aspettando che lo stack sia completamente eliminato...
REM aws cloudformation wait stack-delete-complete --stack-name %STACK_NAME% --region %REGION%

echo [INFO] Deploy stack %STACK_NAME% in region %REGION%...

sam deploy  --config-file infra\%FOLDER%\%STACK_NAME%\samconfig.toml --config-env %environment%

if %ERRORLEVEL% NEQ 0 (
    echo [ERRORE] Deploy failed!
    exit /b %ERRORLEVEL%
)

echo [SUCCESSO] Deploy completed in stack %STACK_NAME%.