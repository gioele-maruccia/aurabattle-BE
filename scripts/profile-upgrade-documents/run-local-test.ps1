# ============================================
# TEST LOCALE - Document Overwrite
# ============================================
# Testa la funzionalità di overwrite SENZA
# toccare il database AWS reale!
# ============================================

param(
    [switch]$InstallDeps = $false
)

$ErrorActionPreference = "Stop"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  TEST LOCALE - Document Overwrite" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check if Python is available
try {
    $pythonVersion = python --version 2>&1
    Write-Host "✅ Python: $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "❌ Python non trovato!" -ForegroundColor Red
    Write-Host "   Installa Python 3.8+ prima di continuare" -ForegroundColor Yellow
    exit 1
}

# Install dependencies if requested
if ($InstallDeps) {
    Write-Host ""
    Write-Host "📦 Installazione dipendenze..." -ForegroundColor Yellow
    pip install moto boto3 --quiet
    Write-Host "✅ Dipendenze installate" -ForegroundColor Green
}

# Check if moto is installed
Write-Host ""
Write-Host "🔍 Verifica dipendenze..." -ForegroundColor Yellow

$motoInstalled = python -c "import moto; print('OK')" 2>&1
if ($motoInstalled -notmatch "OK") {
    Write-Host "❌ moto non installato!" -ForegroundColor Red
    Write-Host ""
    Write-Host "Installa con:" -ForegroundColor Yellow
    Write-Host "   .\run-local-test.ps1 -InstallDeps" -ForegroundColor Cyan
    Write-Host "oppure:" -ForegroundColor Yellow
    Write-Host "   pip install moto boto3" -ForegroundColor Cyan
    exit 1
}

Write-Host "✅ Tutte le dipendenze sono installate" -ForegroundColor Green
Write-Host ""

# Run the test
Write-Host "🧪 Esecuzione test..." -ForegroundColor Yellow
Write-Host ""

$testScript = Join-Path $PSScriptRoot "test-overwrite-local.py"

python $testScript

$exitCode = $LASTEXITCODE

Write-Host ""
if ($exitCode -eq 0) {
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "  ✅ TUTTI I TEST SUPERATI!" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
} else {
    Write-Host "========================================" -ForegroundColor Red
    Write-Host "  ❌ ALCUNI TEST FALLITI" -ForegroundColor Red
    Write-Host "========================================" -ForegroundColor Red
}

exit $exitCode
