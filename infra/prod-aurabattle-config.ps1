#!/usr/bin/env pwsh
# ============================================================
# prod-aurabattle Environment Configuration
# ============================================================
# GENERATO da: scripts/create-prod-aurabattle-prereqs.ps1
# NON modificare manualmente - rieseguire lo script prereqs
# ============================================================

$ProdAuraBattle_Environment = "prod-aurabattle"
$ProdAuraBattle_Region      = "eu-south-1"
$ProdAuraBattle_AccountId   = "881962383770"

# ---- Cognito User Pool ----
$ProdAuraBattle_UserPoolId  = "PLACEHOLDER_RUN_PREREQS"
$ProdAuraBattle_UserPoolArn = "PLACEHOLDER_RUN_PREREQS"
$ProdAuraBattle_ClientId    = "PLACEHOLDER_RUN_PREREQS"

# ---- S3 Buckets ----
$ProdAuraBattle_ArtifactsBucket = "aurabattle-prod-artifacts"

# ---- DynamoDB Tables (prefisso prod-aurabattle-*) ----
$ProdAuraBattle_UserProfilesTable   = "prod-aurabattle-UserProfiles"
$ProdAuraBattle_BattlesTable        = "prod-aurabattle-Battles"
$ProdAuraBattle_ParticipationsTable = "prod-aurabattle-Participations"
