#!/usr/bin/env pwsh
# ============================================================
# dev-be Environment Configuration
# ============================================================
# GENERATO da: scripts/create-dev-be-prereqs.ps1
# NON modificare manualmente - rieseguire lo script prereqs
# ============================================================

$DevBe_Environment = "dev-be"
$DevBe_Region      = "eu-south-1"
$DevBe_AccountId   = "881962383770"

# ---- Cognito User Pool ----
$DevBe_UserPoolId  = "eu-south-1_1uXj751D4"
$DevBe_UserPoolArn = "arn:aws:cognito-idp:eu-south-1:881962383770:userpool/eu-south-1_1uXj751D4"
$DevBe_ClientId    = "79l74qkvsu0sdm58lfdsdvk6qo"

# ---- S3 Buckets ----
$DevBe_ArtifactsBucket       = "beezey-dev-be"
$DevBe_CompaniesAssetsBucket = "beezey-dev-be-companies-assets"
$DevBe_UserDocsBucket        = "beezey-dev-be-user-documents"
$DevBe_DocumentsBucket       = "beezey-dev-be-documents"

# ---- DynamoDB Tables (prefisso dev-be-*) ----
$DevBe_UserProfilesTable    = "dev-be-UserProfiles"
$DevBe_UserDocumentsTable   = "dev-be-UserDocuments"
$DevBe_CompaniesTable       = "dev-be-Companies"
$DevBe_JobListingsTable     = "dev-be-JobListings"
$DevBe_JobRolesTable        = "dev-be-JobRoles"
$DevBe_ContractsTable       = "dev-be-Contracts"
$DevBe_JobCategoriesTable   = "dev-be-JobCategories"
$DevBe_EmploymentTypesTable = "dev-be-EmploymentTypes"

# ---- KMS Key (creato da infra/data/user-documents dopo il deploy) ----
# Viene auto-rilevato dai deploy script tramite CloudFormation outputs.
# Se necessario, compilare manualmente dopo il deploy del data layer:
$DevBe_KmsKeyId  = "PLACEHOLDER_DEPLOY_DATA_LAYER"
$DevBe_KmsKeyArn = "PLACEHOLDER_DEPLOY_DATA_LAYER"

# ---- Chat Layer (creato dal deploy chat, auto-rilevato da bookings) ----
# Viene auto-rilevato da bookings/deploy-dev-be.ps1 tramite CloudFormation outputs.
$DevBe_ChatSharedLayerArn = "PLACEHOLDER_DEPLOY_CHAT"
