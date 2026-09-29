using './main.bicep'

param environmentName = 'staging'
param namePrefix = 'regimpact'
param location = 'canadacentral'
param apiImage = 'replace.azurecr.io/regimpact-api:bootstrap'
param webImage = 'replace.azurecr.io/regimpact-web:bootstrap'
param applicationMinReplicas = 0
param postgresAdminPassword = readEnvironmentVariable('POSTGRES_ADMIN_PASSWORD')
param jwtSecret = readEnvironmentVariable('REGIMPACT_JWT_SECRET')
param tags = { owner: 'platform', managedBy: 'bicep', costProfile: 'scale-to-zero' }
