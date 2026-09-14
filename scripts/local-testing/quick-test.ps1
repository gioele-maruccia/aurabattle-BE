<#
.SYNOPSIS
    Quick-start script per test API in locale

.DESCRIPTION
    Script PowerShell per eseguire facilmente test delle API in locale
    senza rischio di modificare il DB dev.

.PARAMETER Action
    Azione da eseguire: export, test, interactive

.PARAMETER Lambda
    Nome della Lambda da testare (es: user-api/update-profile)

.PARAMETER Event  
    Path all'evento JSON

.PARAMETER LoadData
    Carica dati dal dev nel mock locale

.EXAMPLE
    .\quick-test.ps1 export
    Esporta dati dal DB dev

.EXAMPLE
    .\quick-test.ps1 test -Lambda user-api/update-profile -Event events/test.json
    Testa una Lambda

.EXAMPLE
    .\quick-test.ps1 interactive
    Modalità interattiva

#>

param(
    [Parameter(Mandatory=$false)]
    [ValidateSet("export", "test", "interactive", "setup")]
    [string]$Action = "interactive",
    
    [Parameter(Mandatory=$false)]
    [string]$Lambda,
    
    [Parameter(Mandatory=$false)]
    [string]$Event,
    
    [Parameter(Mandatory=$false)]
    [switch]$LoadData,
    
    [Parameter(Mandatory=$false)]
    [switch]$Help
)

# Colors
function Write-Header {
    param([string]$Text)
    Write-Host "`n========================================================================" -ForegroundColor Cyan
    Write-Host "  $Text" -ForegroundColor Cyan
    Write-Host "========================================================================`n" -ForegroundColor Cyan
}

function Write-Success {
    param([string]$Text)
    Write-Host "✅ $Text" -ForegroundColor Green
}

function Write-Info {
    param([string]$Text)
    Write-Host "ℹ️  $Text" -ForegroundColor Cyan
}

function Write-Warning2 {
    param([string]$Text)
    Write-Host "⚠️  $Text" -ForegroundColor Yellow
}

function Write-ErrorMsg {
    param([string]$Text)
    Write-Host "❌ $Text" -ForegroundColor Red
}

# Check Python
function Test-Python {
    try {
        $pythonVersion = python --version 2>&1
        if ($pythonVersion -match "Python") {
            Write-Success "Python installato: $pythonVersion"
            return $true
        }
    } catch {
        Write-ErrorMsg "Python non trovato!"
        Write-Info "Installa Python da: https://www.python.org/"
        return $false
    }
}

# Check moto
function Test-Moto {
    try {
        $motoCheck = python -c "import moto; print('OK')" 2>&1
        if ($motoCheck -match "OK") {
            Write-Success "moto installato"
            return $true
        }
    } catch {}
    
    Write-Warning2 "moto non installato"
    Write-Info "Installazione in corso..."
    
    try {
        pip install moto boto3 --quiet
        Write-Success "moto installato correttamente"
        return $true
    } catch {
        Write-ErrorMsg "Errore nell'installazione di moto"
        Write-Info "Esegui manualmente: pip install moto boto3"
        return $false
    }
}

# Help
if ($Help) {
    Write-Header "QUICK TEST - Test API in Locale"
    Write-Host @"
Script rapido per testare le API in locale SENZA toccare il DB dev!

USO:
  .\quick-test.ps1 [action] [parametri]

AZIONI:
  export       Esporta dati dal DB dev (READ-ONLY)
  test         Testa una Lambda specifica
  interactive  Modalità interattiva (DEFAULT)
  setup        Setup iniziale

ESEMPI:
  # Setup iniziale
  .\quick-test.ps1 setup

  # Esporta dati dal dev
  .\quick-test.ps1 export

  # Test con DB vuoto
  .\quick-test.ps1 test -Lambda user-api/update-profile -Event events/test.json

  # Test con dati dal dev
  .\quick-test.ps1 test -Lambda user-api/update-profile -Event events/test.json -LoadData

  # Modalità interattiva
  .\quick-test.ps1 interactive

"@
    exit 0
}

# Main
Write-Header "QUICK TEST - Test API in Locale"
Write-Warning2 "🔒 SICURO: Il DB dev NON verrà MAI modificato!"
Write-Info "🔧 Test completamente in locale con moto"
Write-Host ""

# Check requirements
if (-not (Test-Python)) {
    exit 1
}

if (-not (Test-Moto)) {
    exit 1
}

Write-Host ""

# Execute action
switch ($Action) {
    "setup" {
        Write-Header "SETUP INIZIALE"
        Write-Info "Creazione directory e file..."
        
        # Create events directory
        $eventsDir = Join-Path $PSScriptRoot "events"
        if (-not (Test-Path $eventsDir)) {
            New-Item -ItemType Directory -Path $eventsDir | Out-Null
            Write-Success "Directory events creata"
        }
        
        # Create exported-data directory
        $dataDir = Join-Path $PSScriptRoot "exported-data"
        if (-not (Test-Path $dataDir)) {
            New-Item -ItemType Directory -Path $dataDir | Out-Null
            Write-Success "Directory exported-data creata"
        }
        
        # Create .gitignore
        $gitignorePath = Join-Path $PSScriptRoot ".gitignore"
        if (-not (Test-Path $gitignorePath)) {
            @"
# Ignore exported data
exported-data/
*.json
!config.json

# Ignore Python cache
__pycache__/
*.pyc
*.pyo

# Ignore local env info
.local-env-info.json
"@ | Set-Content $gitignorePath
            Write-Success ".gitignore creato"
        }
        
        Write-Host ""
        Write-Success "Setup completato!"
        Write-Info "Prossimo passo: .\quick-test.ps1 export"
    }
    
    "export" {
        Write-Header "EXPORT DATI DAL DB DEV (READ-ONLY)"
        Write-Info "Esportazione dati per test locali..."
        Write-Host ""
        
        python "$PSScriptRoot\export-dev-data.py" --scan-all
        
        if ($LASTEXITCODE -eq 0) {
            Write-Host ""
            Write-Success "Dati esportati con successo!"
            Write-Info "Usa: .\quick-test.ps1 test -LoadData"
        }
    }
    
    "test" {
        if (-not $Lambda -or -not $Event) {
            Write-ErrorMsg "Parametri mancanti!"
            Write-Info "Usa: .\quick-test.ps1 test -Lambda <nome> -Event <file.json>"
            Write-Info "Oppure: .\quick-test.ps1 interactive"
            exit 1
        }
        
        Write-Header "TEST API: $Lambda"
        
        # Build lambda path
        $lambdaPath = Join-Path $PSScriptRoot "..\..\..\src\lambdas\services\$Lambda"
        
        # Build command
        $cmd = "python `"$PSScriptRoot\test-api-local.py`" --lambda `"$lambdaPath`" --event `"$Event`""
        
        if ($LoadData) {
            $cmd += " --load-data"
        }
        
        Write-Info "Esecuzione: $cmd"
        Write-Host ""
        
        Invoke-Expression $cmd
    }
    
    "interactive" {
        Write-Header "MODALITÀ INTERATTIVA"
        Write-Info "Test rapido e facile delle API"
        Write-Host ""
        
        python "$PSScriptRoot\test-api-local.py" --interactive
    }
}

Write-Host ""
Write-Success "Fatto!"
Write-Info "Per aiuto: .\quick-test.ps1 -Help"
