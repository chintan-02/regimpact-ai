targetScope = 'resourceGroup'

@allowed(['staging', 'production'])
param environmentName string
param location string = resourceGroup().location
@minLength(3)
param namePrefix string = 'regimpact'
param apiImage string
param webImage string
param deployWorkloads bool = true
@minValue(0)
@maxValue(1)
param applicationMinReplicas int = 1
@secure()
param postgresAdminPassword string
@secure()
param jwtSecret string
param postgresAdminUser string = 'regimpactadmin'
param tags object = {}

var suffix = uniqueString(subscription().subscriptionId, resourceGroup().id, environmentName)
var baseName = '${namePrefix}-${environmentName}'
var resourceTags = union(tags, { application: 'regimpact-ai', environment: environmentName })

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${baseName}-logs'
  location: location
  tags: resourceTags
  properties: {
    retentionInDays: 30
    sku: { name: 'PerGB2018' }
  }
}

resource insights 'Microsoft.Insights/components@2020-02-02' = {
  name: '${baseName}-insights'
  location: location
  kind: 'web'
  tags: resourceTags
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logs.id
  }
}

resource registry 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' = {
  name: 'ri${suffix}'
  location: location
  tags: resourceTags
  sku: { name: 'Basic' }
  properties: { adminUserEnabled: false }
}

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${baseName}-workload'
  location: location
  tags: resourceTags
}

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: 'ri${suffix}'
  location: location
  tags: resourceTags
  sku: { name: environmentName == 'production' ? 'Standard_GRS' : 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    allowBlobPublicAccess: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
  properties: {
    deleteRetentionPolicy: { enabled: true, days: 7 }
    containerDeleteRetentionPolicy: { enabled: true, days: 7 }
  }
}

resource documents 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'documents'
  properties: { publicAccess: 'None' }
}

resource vault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: take('${baseName}-${suffix}', 24)
  location: location
  tags: resourceTags
  properties: {
    tenantId: tenant().tenantId
    enableRbacAuthorization: true
    enablePurgeProtection: environmentName == 'production' ? true : null
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
    sku: { family: 'A', name: 'standard' }
  }
}

resource postgres 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: '${baseName}-pg-${suffix}'
  location: location
  tags: resourceTags
  sku: {
    name: environmentName == 'production' ? 'Standard_D2ds_v5' : 'Standard_B1ms'
    tier: environmentName == 'production' ? 'GeneralPurpose' : 'Burstable'
  }
  properties: {
    administratorLogin: postgresAdminUser
    administratorLoginPassword: postgresAdminPassword
    version: '17'
    storage: { storageSizeGB: 32 }
    backup: {
      backupRetentionDays: environmentName == 'production' ? 14 : 7
      geoRedundantBackup: environmentName == 'production' ? 'Enabled' : 'Disabled'
    }
    highAvailability: { mode: environmentName == 'production' ? 'ZoneRedundant' : 'Disabled' }
  }
}

resource postgresExtensions 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-08-01' = if (!deployWorkloads) {
  parent: postgres
  name: 'azure.extensions'
  properties: {
    value: 'VECTOR'
    source: 'user-override'
  }
}

resource database 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-08-01' = {
  parent: postgres
  name: 'regimpact'
  properties: { charset: 'UTF8', collation: 'en_US.utf8' }
}

resource postgresFirewall 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2024-08-01' = {
  parent: postgres
  name: 'AllowAzureServices'
  properties: { startIpAddress: '0.0.0.0', endIpAddress: '0.0.0.0' }
}

resource redis 'Microsoft.Cache/redis@2024-11-01' = {
  name: '${baseName}-redis-${suffix}'
  location: location
  tags: resourceTags
  properties: {
    enableNonSslPort: false
    minimumTlsVersion: '1.2'
    publicNetworkAccess: 'Enabled'
    sku: { name: 'Basic', family: 'C', capacity: 0 }
  }
}

resource jwtSecretResource 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: vault
  name: 'jwt-secret'
  properties: { value: jwtSecret }
}

resource databaseSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: vault
  name: 'database-url'
  properties: {
    value: 'postgresql+psycopg://${postgresAdminUser}:${postgresAdminPassword}@${postgres.properties.fullyQualifiedDomainName}:5432/regimpact?sslmode=require'
  }
  dependsOn: [database]
}

resource redisSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: vault
  name: 'redis-url'
  properties: {
    value: 'rediss://:${redis.listKeys().primaryKey}@${redis.properties.hostName}:${redis.properties.sslPort}/0'
  }
}

resource blobRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, identity.id, 'blob-contributor')
  scope: storage
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
  }
}

resource vaultRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(vault.id, identity.id, 'secret-user')
  scope: vault
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4633458b-17de-408a-b874-0445c86b69e6')
  }
}

resource acrRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, identity.id, 'acr-pull')
  scope: registry
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d')
  }
}

resource containerEnvironment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: '${baseName}-cae'
  location: location
  tags: resourceTags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
  }
}

var commonSecrets = [
  { name: 'database-url', keyVaultUrl: databaseSecret.properties.secretUriWithVersion, identity: identity.id }
  { name: 'redis-url', keyVaultUrl: redisSecret.properties.secretUriWithVersion, identity: identity.id }
  { name: 'jwt-secret', keyVaultUrl: jwtSecretResource.properties.secretUriWithVersion, identity: identity.id }
]
var commonEnv = [
  { name: 'REGIMPACT_ENVIRONMENT', value: environmentName }
  { name: 'REGIMPACT_DATABASE_URL', secretRef: 'database-url' }
  { name: 'REGIMPACT_REDIS_URL', secretRef: 'redis-url' }
  { name: 'REGIMPACT_JWT_SECRET', secretRef: 'jwt-secret' }
  { name: 'REGIMPACT_OBJECT_STORAGE_BACKEND', value: 'azure_blob' }
  { name: 'REGIMPACT_AZURE_STORAGE_ACCOUNT_URL', value: storage.properties.primaryEndpoints.blob }
  { name: 'REGIMPACT_AZURE_STORAGE_CONTAINER', value: documents.name }
  { name: 'REGIMPACT_MALWARE_SCANNER_MODE', value: 'unavailable' }
  { name: 'REGIMPACT_LOG_LEVEL', value: 'INFO' }
  { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: insights.properties.ConnectionString }
]

resource api 'Microsoft.App/containerApps@2024-03-01' = if (deployWorkloads) {
  name: '${baseName}-api'
  location: location
  tags: resourceTags
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${identity.id}': {} } }
  properties: {
    managedEnvironmentId: containerEnvironment.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: { external: false, targetPort: 8000, transport: 'http', allowInsecure: false }
      registries: [{ server: registry.properties.loginServer, identity: identity.id }]
      secrets: commonSecrets
    }
    template: {
      containers: [{
        name: 'api'
        image: apiImage
        env: commonEnv
        resources: { cpu: json('0.5'), memory: '1Gi' }
        probes: [
          { type: 'Liveness', httpGet: { path: '/health', port: 8000 }, periodSeconds: 30 }
          { type: 'Readiness', httpGet: { path: '/ready', port: 8000 }, periodSeconds: 10 }
          { type: 'Startup', httpGet: { path: '/startup', port: 8000 }, periodSeconds: 5, failureThreshold: 12 }
        ]
      }]
      scale: { minReplicas: applicationMinReplicas, maxReplicas: environmentName == 'production' ? 5 : 2 }
    }
  }
  dependsOn: [blobRole, vaultRole, acrRole]
}

resource web 'Microsoft.App/containerApps@2024-03-01' = if (deployWorkloads) {
  name: '${baseName}-web'
  location: location
  tags: resourceTags
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${identity.id}': {} } }
  properties: {
    managedEnvironmentId: containerEnvironment.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: { external: true, targetPort: 3000, transport: 'http', allowInsecure: false }
      registries: [{ server: registry.properties.loginServer, identity: identity.id }]
    }
    template: {
      containers: [{
        name: 'web'
        image: webImage
        env: [
          { name: 'REGIMPACT_API_BASE_URL', value: 'https://${api!.properties.configuration.ingress.fqdn}' }
          { name: 'REGIMPACT_COOKIE_SECURE', value: 'true' }
          { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: insights.properties.ConnectionString }
        ]
        resources: { cpu: json('0.5'), memory: '1Gi' }
        probes: [
          { type: 'Liveness', httpGet: { path: '/login', port: 3000 }, periodSeconds: 30, timeoutSeconds: 5, failureThreshold: 3 }
          { type: 'Readiness', httpGet: { path: '/api/platform/readiness', port: 3000 }, periodSeconds: 10, timeoutSeconds: 5, failureThreshold: 6 }
          { type: 'Startup', httpGet: { path: '/login', port: 3000 }, periodSeconds: 5, timeoutSeconds: 5, failureThreshold: 12 }
        ]
      }]
      scale: { minReplicas: applicationMinReplicas, maxReplicas: environmentName == 'production' ? 5 : 2 }
    }
  }
  dependsOn: [acrRole]
}

resource worker 'Microsoft.App/containerApps@2024-03-01' = if (deployWorkloads) {
  name: '${baseName}-worker'
  location: location
  tags: resourceTags
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${identity.id}': {} } }
  properties: {
    managedEnvironmentId: containerEnvironment.id
    configuration: {
      activeRevisionsMode: 'Single'
      registries: [{ server: registry.properties.loginServer, identity: identity.id }]
      secrets: commonSecrets
    }
    template: {
      containers: [{
        name: 'worker'
        image: apiImage
        command: ['dramatiq', 'regimpact.tasks', '--processes', '1', '--threads', '4']
        env: commonEnv
        resources: { cpu: json('0.5'), memory: '1Gi' }
      }]
      scale: { minReplicas: applicationMinReplicas, maxReplicas: environmentName == 'production' ? 5 : 2 }
    }
  }
  dependsOn: [blobRole, vaultRole, acrRole]
}

resource dispatcher 'Microsoft.App/containerApps@2024-03-01' = if (deployWorkloads) {
  name: '${baseName}-dispatcher'
  location: location
  tags: resourceTags
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${identity.id}': {} } }
  properties: {
    managedEnvironmentId: containerEnvironment.id
    configuration: {
      activeRevisionsMode: 'Single'
      registries: [{ server: registry.properties.loginServer, identity: identity.id }]
      secrets: commonSecrets
    }
    template: {
      containers: [{
        name: 'dispatcher'
        image: apiImage
        command: ['python', '-m', 'regimpact.dispatcher']
        env: commonEnv
        resources: { cpu: json('0.25'), memory: '0.5Gi' }
      }]
      scale: { minReplicas: applicationMinReplicas, maxReplicas: 1 }
    }
  }
  dependsOn: [vaultRole, acrRole]
}

resource scheduler 'Microsoft.App/containerApps@2024-03-01' = if (deployWorkloads) {
  name: '${baseName}-scheduler'
  location: location
  tags: resourceTags
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${identity.id}': {} } }
  properties: {
    managedEnvironmentId: containerEnvironment.id
    configuration: {
      activeRevisionsMode: 'Single'
      registries: [{ server: registry.properties.loginServer, identity: identity.id }]
      secrets: commonSecrets
    }
    template: {
      containers: [{
        name: 'scheduler'
        image: apiImage
        command: ['python', '-m', 'regimpact.scheduler']
        env: commonEnv
        resources: { cpu: json('0.25'), memory: '0.5Gi' }
      }]
      scale: { minReplicas: applicationMinReplicas, maxReplicas: 1 }
    }
  }
  dependsOn: [vaultRole, acrRole]
}

resource migrationJob 'Microsoft.App/jobs@2024-03-01' = if (deployWorkloads) {
  name: '${baseName}-migrate'
  location: location
  tags: resourceTags
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${identity.id}': {} } }
  properties: {
    environmentId: containerEnvironment.id
    configuration: {
      triggerType: 'Manual'
      replicaTimeout: 600
      replicaRetryLimit: 1
      registries: [{ server: registry.properties.loginServer, identity: identity.id }]
      secrets: commonSecrets
      manualTriggerConfig: { parallelism: 1, replicaCompletionCount: 1 }
    }
    template: {
      containers: [{
        name: 'migrate'
        image: apiImage
        command: ['alembic', 'upgrade', 'head']
        env: commonEnv
        resources: { cpu: json('0.5'), memory: '1Gi' }
      }]
    }
  }
  dependsOn: [vaultRole, acrRole]
}

output registryName string = registry.name
output apiUrl string = deployWorkloads ? 'https://${api!.properties.configuration.ingress.fqdn}' : ''
output webUrl string = deployWorkloads ? 'https://${web!.properties.configuration.ingress.fqdn}' : ''
output migrationJobName string = deployWorkloads ? migrationJob!.name : ''
output keyVaultName string = vault.name
output logAnalyticsWorkspaceId string = logs.id
output applicationInsightsName string = insights.name
output postgresServerName string = postgres.name
output redisName string = redis.name
output storageAccountName string = storage.name
output workloadIdentityName string = identity.name
