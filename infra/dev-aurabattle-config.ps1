#!/usr/bin/env pwsh
# ============================================================
# dev-aurabattle Environment Configuration
# ============================================================
# GENERATO da: scripts/create-aurabattle-prereqs.ps1
# NON modificare manualmente - rieseguire lo script prereqs
# ============================================================

$DevAuraBattle_Environment = "dev-aurabattle"
$DevAuraBattle_Region      = "eu-south-1"
$DevAuraBattle_AccountId   = "881962383770"

# ---- Cognito User Pool ----
$DevAuraBattle_UserPoolId  = "eu-south-1_ULXAFvzY9"
$DevAuraBattle_UserPoolArn = "arn:aws:cognito-idp:eu-south-1:881962383770:userpool/eu-south-1_ULXAFvzY9"
$DevAuraBattle_ClientId    = "1si0vr079rbrvtck9ht4cpob78"

# ---- S3 Buckets ----
$DevAuraBattle_ArtifactsBucket = "aurabattle-dev-artifacts"

# ---- DynamoDB Tables (prefisso dev-aurabattle-*) ----
$DevAuraBattle_UserProfilesTable   = "dev-aurabattle-UserProfiles"
$DevAuraBattle_BattlesTable        = "dev-aurabattle-Battles"
$DevAuraBattle_ParticipationsTable = "dev-aurabattle-Participations"
