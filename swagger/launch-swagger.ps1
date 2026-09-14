#####################################################################
#         SWAGGER UI LAUNCHER (Windows PowerShell)                  #
#####################################################################

param(
    [string]$Environment = "dev"
)

$ErrorActionPreference = "Stop"

# Colors
function Write-Success { param($msg) Write-Host $msg -ForegroundColor Green }
function Write-Info { param($msg) Write-Host $msg -ForegroundColor Cyan }
function Write-Warning-Custom { param($msg) Write-Host $msg -ForegroundColor Yellow }
function Write-Error-Custom { param($msg) Write-Host $msg -ForegroundColor Red }

Write-Host ""
Write-Info "==============================================================="
Write-Info "          SWAGGER UI LAUNCHER - $Environment Environment"
Write-Info "==============================================================="
Write-Host ""

# Navigate to swagger directory
$swaggerDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $swaggerDir

# Check if swagger-bundled.yml exists
if (-not (Test-Path "swagger-bundled.yml")) {
    Write-Warning-Custom "swagger-bundled.yml not found. Bundling swagger files..."
    
    # Install swagger-cli if not present
    $swaggerCli = Get-Command swagger-cli -ErrorAction SilentlyContinue
    if (-not $swaggerCli) {
        Write-Info "Installing swagger-cli..."
        npm install -g @apidevtools/swagger-cli
    }
    
    # Bundle swagger files
    Write-Info "Bundling swagger.yml..."
    swagger-cli bundle swagger.yml -o swagger-bundled.yml -t yaml
    Write-Success "Bundled swagger-bundled.yml created successfully!"
}

# Check if Docker is running
try {
    docker ps | Out-Null
} catch {
    Write-Error-Custom "Docker is not running. Please start Docker Desktop."
    exit 1
}

# Container configuration
$containerName = "swagger-ui-docs-$Environment"
$port = if ($Environment -eq "dev") { 8080 } else { 8081 }

# Stop existing container if running
$existingContainer = docker ps -a --format "{{.Names}}" | Where-Object { $_ -eq $containerName }
if ($existingContainer) {
    Write-Info "Stopping existing container: $containerName"
    docker stop $containerName 2>&1 | Out-Null
    docker rm $containerName 2>&1 | Out-Null
}

# Run Swagger UI container
Write-Info "Starting Swagger UI on http://localhost:$port"
Write-Info "Container: $containerName"
Write-Info "Swagger file: swagger-bundled.yml"

docker run -d `
    --name $containerName `
    -p ${port}:8080 `
    -e SWAGGER_JSON=/swagger/swagger-bundled.yml `
    -v "${pwd}:/swagger" `
    swaggerapi/swagger-ui

if ($LASTEXITCODE -eq 0) {
    Start-Sleep 3
    Write-Host ""
    Write-Success "==============================================================="
    Write-Success "          SWAGGER UI RUNNING SUCCESSFULLY!"
    Write-Success "==============================================================="
    Write-Host ""
    Write-Info "Access Swagger UI at:"
    Write-Host "  http://localhost:$port" -ForegroundColor Yellow
    Write-Host ""
    Write-Info "To stop the container:"
    Write-Host "  docker stop $containerName" -ForegroundColor Gray
    Write-Host ""
} else {
    Write-Error-Custom "Failed to start Swagger UI container"
    exit 1
}
