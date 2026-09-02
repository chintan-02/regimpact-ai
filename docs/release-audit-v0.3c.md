# v0.3C release audit

## Scope delivered

- parameterized Bicep for staging and production;
- Azure Container Apps API, web, worker, dispatcher, scheduler, and migration job;
- managed PostgreSQL, Redis, Blob Storage, ACR, Key Vault, Log Analytics, and Application Insights;
- managed identities and least-purpose data-plane role assignments;
- GitHub Actions OIDC deployment with immutable commit-SHA images;
- Azure Blob implementation of the existing object-storage boundary;
- environment protection, deployment serialization, migration gate, and smoke verification;
- static infrastructure security validation and deployment documentation.

## Deliberately excluded

- live Azure provisioning or credential creation;
- AKS, Helm, and Kubernetes autoscaling;
- Entra workforce login migration;
- private endpoints and enterprise network topology;
- production malware-scanner integration.

No tag is created in this phase. v0.3.0 remains reserved until all intended v0.3 stages are merged
and accepted.
