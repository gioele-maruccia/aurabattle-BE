param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("dev", "dev-be", "prod")]
    [string]$Env,

    # Opzionali: se forniti, inviano la broadcast email agli utenti a fine deploy
    [string]$AppVersion   = "",
    [string]$ReleaseNotes = ""
)

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$services = @(
    "firebase-notifications",
    "chat",
    "bookings",
    "support-chat",
    "backoffice",
    "job-listings",
    "user-api",
    "email-notifications"
)

$success = @()
$failed  = @()
$skipped = @()

Write-Host ""
Write-Host "=== DEPLOY ALL SERVICES ($($Env.ToUpper())) ===" -ForegroundColor Cyan
Write-Host ""

# -------------------------------------------------------
# CONFERMA PRODUZIONE — una sola volta, qui nel main script
# -------------------------------------------------------
if ($Env -eq "prod") {
    Write-Host "============================================" -ForegroundColor Red
    Write-Host "   ATTENZIONE: DEPLOY IN PRODUZIONE!" -ForegroundColor Red
    Write-Host "============================================" -ForegroundColor Red
    Write-Host ""
    Write-Host "[WARNING] Stai per fare il deploy di TUTTI i servizi in PRODUZIONE!" -ForegroundColor Yellow
    Write-Host "Questo modificherà i servizi LIVE!" -ForegroundColor Yellow
    Write-Host ""
    $confirm = Read-Host "Sei sicuro di voler procedere? (digita 'yes' per confermare)"
    if ($confirm -ne "yes") {
        Write-Host ""
        Write-Host "[ABORT] Deploy annullato" -ForegroundColor Yellow
        exit 0
    }
    Write-Host ""
    Write-Host "[OK] Confermato, procedo con il deploy PROD di tutti i servizi..." -ForegroundColor Green
    Write-Host ""
}

# -------------------------------------------------------
# DEPLOY DI OGNI SERVIZIO
# -------------------------------------------------------
foreach ($svc in $services) {
    $scriptPath = Join-Path $root "$svc\deploy-$Env.ps1"

    if (-not (Test-Path $scriptPath)) {
        Write-Host ("  [SKIP]  " + $svc) -ForegroundColor Yellow
        $skipped += $svc
        continue
    }

    Write-Host -NoNewline ("  " + $svc.PadRight(42)) -ForegroundColor White

    $svcDir = Join-Path $root $svc
    Push-Location $svcDir

    if ($Env -eq "prod") {
        # Lancia il sotto-script in un processo separato con stdin reindirizzato
        # per rispondere automaticamente "yes" alla conferma prod (solo qui nel main script).
        # Legge stdout/stderr in modo asincrono per evitare blocchi da buffer pieno.
        $pwshExe = [System.Diagnostics.Process]::GetCurrentProcess().MainModule.FileName
        $psi = [System.Diagnostics.ProcessStartInfo]::new()
        $psi.FileName            = $pwshExe
        $psi.Arguments           = "-File `"$scriptPath`""
        $psi.RedirectStandardInput  = $true
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError  = $true
        $psi.UseShellExecute     = $false

        # Passa AppVersion/ReleaseNotes via env vars (ereditate dal processo figlio)
        if ($svc -eq "email-notifications") {
            $env:DEPLOY_APP_VERSION   = $AppVersion
            $env:DEPLOY_RELEASE_NOTES = $ReleaseNotes
        }

        $proc        = [System.Diagnostics.Process]::Start($psi)
        $stdoutTask  = $proc.StandardOutput.ReadToEndAsync()
        $stderrTask  = $proc.StandardError.ReadToEndAsync()

        # Risponde "yes" alla Read-Host di conferma prod, poi chiude stdin
        $proc.StandardInput.WriteLine("yes")
        $proc.StandardInput.Close()

        $proc.WaitForExit()
        $null = $stdoutTask.Result
        $null = $stderrTask.Result
        $code = $proc.ExitCode

    } else {
        # Per dev / dev-be: cattura tutto l'output (mostrato solo se fallisce)
        if ($svc -eq "email-notifications" -and $AppVersion -ne "") {
            $captured = & $scriptPath -AppVersion $AppVersion -ReleaseNotes $ReleaseNotes *>&1
        } else {
            $captured = & $scriptPath *>&1
        }
        $code = $LASTEXITCODE
    }

    Pop-Location

    if ($code -eq 0) {
        Write-Host "OK" -ForegroundColor Green
        $success += $svc
    } else {
        Write-Host "FAILED  (exit: $code)" -ForegroundColor Red
        $failed += $svc
        # Mostra l'output del sotto-script per facilitare il debug
        Write-Host ""
        Write-Host "--- OUTPUT $svc ---" -ForegroundColor DarkGray
        $captured | ForEach-Object { Write-Host $_ -ForegroundColor DarkGray }
        Write-Host "--- FINE OUTPUT $svc ---" -ForegroundColor DarkGray
        Write-Host ""
    }
}

# -------------------------------------------------------
# SOMMARIO
# -------------------------------------------------------
Write-Host ""
Write-Host "=== SOMMARIO ===" -ForegroundColor Cyan
Write-Host "  Successo: $($success.Count)" -ForegroundColor Green
if ($skipped.Count -gt 0) {
    Write-Host "  Saltati:  $($skipped.Count)  ($($skipped -join ', '))" -ForegroundColor Yellow
}
Write-Host "  Falliti:  $($failed.Count)" -ForegroundColor Red

if ($failed.Count -gt 0) {
    Write-Host ""
    Write-Host "Servizi falliti: $($failed -join ', ')" -ForegroundColor Red
    exit 1
}
exit 0
