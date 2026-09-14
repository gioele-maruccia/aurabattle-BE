# Deploy all services dev-be
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$services = @("firebase-notifications","chat","bookings","support-chat","backoffice","companies","contracts","job-listings","profile-upgrade-documents","profile-upgrade-request","reference-data-configuration","user-api")
$success = @()
$failed = @()

Write-Host ""
Write-Host "=== DEPLOY ALL SERVICES (dev-be) ===" -ForegroundColor Cyan
Write-Host ""

foreach ($svc in $services) {
    $scriptPath = Join-Path $root "$svc\deploy-dev-be.ps1"
    
    if (-not (Test-Path $scriptPath)) {
        Write-Host "SKIP: $svc (script not found)" -ForegroundColor Yellow
        continue
    }
    
    Write-Host "Deploying: $svc" -ForegroundColor Yellow
    Push-Location (Join-Path $root $svc)
    & $scriptPath
    $code = $LASTEXITCODE
    Pop-Location
    
    if ($code -eq 0) {
        Write-Host "OK: $svc" -ForegroundColor Green
        $success += $svc
    } else {
        Write-Host "FAILED: $svc (code: $code)" -ForegroundColor Red
        $failed += $svc
    }
    Write-Host ""
}

Write-Host "=== SUMMARY ===" -ForegroundColor Cyan
Write-Host "Success: $($success.Count)" -ForegroundColor Green
Write-Host "Failed: $($failed.Count)" -ForegroundColor Red

if ($failed.Count -gt 0) {
    Write-Host "Failed services: $($failed -join ';')" -ForegroundColor Red
    exit 1
}
exit 0
