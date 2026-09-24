#!/usr/bin/env pwsh
# ============================================================
# Deploy ALL Services - PRODUCTION
# ============================================================
# Uso:
#   .\deploy-all-prod.ps1
#   .\deploy-all-prod.ps1 -AppVersion "2.5.0" -ReleaseNotes "<ul><li>Novità</li></ul>"
# ============================================================
param(
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

$Env     = "prod"
$success = @()
$failed  = @()
$skipped = @()

Write-Host ""
Write-Host "============================================" -ForegroundColor Red
Write-Host "   DEPLOY ALL SERVICES - PRODUCTION" -ForegroundColor Red
Write-Host "============================================" -ForegroundColor Red
Write-Host ""
Write-Host "[WARNING] Stai per fare il deploy di TUTTI i servizi in PRODUZIONE!" -ForegroundColor Yellow
Write-Host "Questo modificherà i servizi LIVE!" -ForegroundColor Yellow
if ($AppVersion -ne "") {
    Write-Host ""
    Write-Host "[BROADCAST] Al termine verrà inviata la email di aggiornamento app:" -ForegroundColor Cyan
    Write-Host "   Versione:  $AppVersion" -ForegroundColor Yellow
    Write-Host "   Note:      $ReleaseNotes" -ForegroundColor Yellow
}
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

$pwshExe = [System.Diagnostics.Process]::GetCurrentProcess().MainModule.FileName

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

    # Costruisce gli argomenti per il subprocess
    $scriptArgs = @("-Force")
    if ($svc -eq "email-notifications") {
        if ($AppVersion   -ne "") { $scriptArgs += "-AppVersion";   $scriptArgs += $AppVersion }
        if ($ReleaseNotes -ne "") { $scriptArgs += "-ReleaseNotes"; $scriptArgs += $ReleaseNotes }
    }

    $psi = [System.Diagnostics.ProcessStartInfo]::new()
    $psi.FileName               = $pwshExe
    $psi.Arguments              = "-File `"$scriptPath`" " + ($scriptArgs -join " ")
    $psi.WorkingDirectory       = $svcDir
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError  = $true
    $psi.UseShellExecute        = $false

    $proc       = [System.Diagnostics.Process]::Start($psi)
    $stdoutTask = $proc.StandardOutput.ReadToEndAsync()
    $stderrTask = $proc.StandardError.ReadToEndAsync()

    $proc.WaitForExit()
    $stdout = $stdoutTask.Result
    $stderr = $stderrTask.Result
    $code = $proc.ExitCode

    Pop-Location

    if ($code -eq 0) {
        Write-Host "OK" -ForegroundColor Green
        $success += $svc
    } else {
        Write-Host "FAILED  (exit: $code)" -ForegroundColor Red
        $failed += $svc
        if ($stdout) { Write-Host $stdout -ForegroundColor Gray }
        if ($stderr) { Write-Host $stderr -ForegroundColor Red }
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
