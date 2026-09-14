#!/usr/bin/env pwsh
<#
.SYNOPSIS
Ricrea i gruppi Cognito e riassegna tutti gli utenti in base al loro profile_type.

.DESCRIPTION
Questo script:
1. Crea i gruppi mancanti (workers, admins, basic, companies)
2. Legge tutti gli utenti dal pool Cognito
3. Assegna ogni utente al gruppo corretto in base a custom:profile_type

.PARAMETER Environment
Ambiente: 'dev' o 'prod' (default: prod)

.EXAMPLE
.\fix-cognito-groups.ps1 -Environment prod
#>

param(
    [Parameter(Mandatory = $false)]
    [ValidateSet('dev', 'prod')]
    [string]$Environment = 'prod'
)

$ErrorActionPreference = 'Stop'

# Importa configurazione Cognito
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$rootDir = Split-Path -Parent $scriptDir
$configPath = Join-Path $rootDir "cognito_config.py"

Write-Host "=============================================================" -ForegroundColor Cyan
Write-Host "  FIX COGNITO GROUPS - $Environment" -ForegroundColor Cyan
Write-Host "=============================================================" -ForegroundColor Cyan
Write-Host ""

# Leggi configurazione
$config = switch ($Environment) {
    'dev' {
        @{
            UserPoolId = 'eu-south-1_0oK9agPYd'
            Region = 'eu-south-1'
        }
    }
    'prod' {
        @{
            UserPoolId = 'eu-south-1_iCBtUlJO6'
            Region = 'eu-south-1'
        }
    }
}

Write-Host "User Pool ID: $($config.UserPoolId)" -ForegroundColor White
Write-Host "Region: $($config.Region)" -ForegroundColor White
Write-Host ""

# Definisci i gruppi da creare
$groups = @(
    @{
        Name = 'basic_users'
        Description = 'Basic users - utenti base senza profilo specializzato'
        Precedence = 10
    },
    @{
        Name = 'pending_review'
        Description = 'Pending review - utenti con documenti in revisione'
        Precedence = 8
    },
    @{
        Name = 'workers'
        Description = 'Workers - lavoratori verificati'
        Precedence = 5
    },
    @{
        Name = 'companies'
        Description = 'Companies - aziende verificate'
        Precedence = 5
    },
    @{
        Name = 'admins'
        Description = 'Admins - amministratori della piattaforma'
        Precedence = 1
    }
)

# STEP 1: Crea i gruppi
Write-Host "STEP 1: Creazione gruppi Cognito" -ForegroundColor Yellow
Write-Host "-------------------------------------------------------------" -ForegroundColor DarkGray

foreach ($group in $groups) {
    Write-Host "  Creazione gruppo '$($group.Name)'... " -NoNewline
    
    $output = aws cognito-idp create-group `
        --user-pool-id $config.UserPoolId `
        --group-name $group.Name `
        --description $group.Description `
        --precedence $group.Precedence `
        --region $config.Region `
        --output json 2>&1
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "OK" -ForegroundColor Green
    } elseif ($output -like "*GroupExistsException*" -or $output -like "*already exists*") {
        Write-Host "Esiste gia" -ForegroundColor Yellow
    } else {
        Write-Host "ERRORE" -ForegroundColor Red
        Write-Host "    $output" -ForegroundColor DarkGray
    }
}

Write-Host ""

# STEP 2: Leggi tutti gli utenti
Write-Host "STEP 2: Lettura utenti dal pool Cognito" -ForegroundColor Yellow
Write-Host "-------------------------------------------------------------" -ForegroundColor DarkGray

$usersJson = aws cognito-idp list-users `
    --user-pool-id $config.UserPoolId `
    --region $config.Region `
    --output json

if ($LASTEXITCODE -ne 0) {
    Write-Host "Errore nel recuperare gli utenti!" -ForegroundColor Red
    exit 1
}

$users = ($usersJson | ConvertFrom-Json).Users
Write-Host "  Trovati $($users.Count) utenti" -ForegroundColor White
Write-Host ""

# STEP 3: Assegna ogni utente al gruppo corretto
Write-Host "STEP 3: Assegnazione utenti ai gruppi" -ForegroundColor Yellow
Write-Host "-------------------------------------------------------------" -ForegroundColor DarkGray

$stats = @{
    basic_users = 0
    pending_review = 0
    workers = 0
    companies = 0
    admins = 0
    unknown = 0
    errors = 0
}

foreach ($user in $users) {
    $username = $user.Username
    $attrs = $user.Attributes
    $email = ($attrs | Where-Object { $_.Name -eq "email" }).Value
    $profileType = ($attrs | Where-Object { $_.Name -eq "custom:profile_type" }).Value
    $verificationStatus = ($attrs | Where-Object { $_.Name -eq "custom:verification_status" }).Value
    
    # Default: basic user se non specificato
    if (-not $profileType) {
        $profileType = 'basic'
    }
    
    # Determina il gruppo in base al profile_type e verification_status
    $groupName = $null
    
    if ($profileType -eq 'admin') {
        $groupName = 'admins'
    }
    elseif ($profileType -eq 'worker') {
        if ($verificationStatus -eq 'approved') {
            $groupName = 'workers'
        }
        elseif ($verificationStatus -in @('in_review', 'rejected', 'pending')) {
            $groupName = 'pending_review'
        }
        else {
            # Default: se worker ma senza verification_status, assume approvato (legacy)
            $groupName = 'workers'
        }
    }
    elseif ($profileType -eq 'company') {
        if ($verificationStatus -eq 'approved') {
            $groupName = 'companies'
        }
        elseif ($verificationStatus -in @('in_review', 'rejected', 'pending')) {
            $groupName = 'pending_review'
        }
        else {
            # Default: se company ma senza verification_status, assume approvato (legacy)
            $groupName = 'companies'
        }
    }
    elseif ($profileType -eq 'basic') {
        $groupName = 'basic_users'
    }
    else {
        Write-Host "  WARN: $email - ProfileType sconosciuto: '$profileType'" -ForegroundColor Yellow
        $stats.unknown++
        continue
    }
    
    Write-Host "  $email ($profileType/$verificationStatus) -> $groupName... " -NoNewline
    
    aws cognito-idp admin-add-user-to-group `
        --user-pool-id $config.UserPoolId `
        --username $username `
        --group-name $groupName `
        --region $config.Region `
        --output json 2>$null | Out-Null
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "OK" -ForegroundColor Green
        $stats[$groupName]++
    } else {
        Write-Host "ERRORE" -ForegroundColor Red
        $stats.errors++
    }
}

Write-Host ""
Write-Host "=============================================================" -ForegroundColor Cyan
Write-Host "  RIEPILOGO" -ForegroundColor Cyan
Write-Host "=============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Basic users:    $($stats.basic_users)" -ForegroundColor White
Write-Host "  Workers:        $($stats.workers)" -ForegroundColor White
Write-Host "  Companies:      $($stats.companies)" -ForegroundColor White
Write-Host "  Pending review: $($stats.pending_review)" -ForegroundColor White
Write-Host "  Admins:         $($stats.admins)" -ForegroundColor White
Write-Host ""
Write-Host "  Sconosciuti: $($stats.unknown)" -ForegroundColor Yellow
Write-Host "  Errori:      $($stats.errors)" -ForegroundColor Red
Write-Host ""

if ($stats.errors -eq 0 -and $stats.unknown -eq 0) {
    Write-Host "TUTTI GLI UTENTI SONO STATI ASSEGNATI CON SUCCESSO!" -ForegroundColor Green
} else {
    Write-Host "Completato con alcuni problemi" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "=============================================================" -ForegroundColor Cyan
