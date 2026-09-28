#!/usr/bin/env pwsh
# ============================================================
# prod-aurabattle Environment Configuration
# ============================================================
# GENERATO da: scripts/create-aurabattle-prereqs.ps1
# NON modificare manualmente - rieseguire lo script prereqs
# ============================================================

$ProdAuraBattle_Environment = "prod-aurabattle"
$ProdAuraBattle_Region      = "eu-south-1"
$ProdAuraBattle_AccountId   = "881962383770"

# ---- Cognito User Pool ----
$ProdAuraBattle_UserPoolId  = "eu-south-1_BKPMyjxEF"
$ProdAuraBattle_UserPoolArn = "arn:aws:cognito-idp:eu-south-1:881962383770:userpool/eu-south-1_BKPMyjxEF"
$ProdAuraBattle_ClientId    = "b0l5i2khen7os0v2n60blonnj"

# ---- S3 Buckets ----
$ProdAuraBattle_ArtifactsBucket = "aurabattle-prod-artifacts"

# ---- DynamoDB Tables (prefisso prod-aurabattle-*) ----
$ProdAuraBattle_UserProfilesTable   = "prod-aurabattle-UserProfiles"
$ProdAuraBattle_BattlesTable        = "prod-aurabattle-Battles"
$ProdAuraBattle_ParticipationsTable = "prod-aurabattle-Participations"
