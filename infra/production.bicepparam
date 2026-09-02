using './main.bicep'

param environmentName = 'production'
param namePrefix = 'regimpact'
param location = 'canadacentral'
param apiImage = 'replace.azurecr.io/regimpact-api:bootstrap'
param webImage = 'replace.azurecr.io/regimpact-web:bootstrap'
param postgresAdminPassword = readEnvironmentVariable('POSTGRES_ADMIN_PASSWORD')
param jwtSecret = readEnvironmentVariable('REGIMPACT_JWT_SECRET')
param tags = { owner: 'platform', managedBy: 'bicep' }
