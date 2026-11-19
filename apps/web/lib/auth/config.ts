import { isIP } from "node:net";

export type ConsoleEnvironment = "local" | "test" | "development" | "staging" | "production";

export type DisabledAuthConfig = {
  enabled: false;
  environment: ConsoleEnvironment;
};

export type EnabledAuthConfig = {
  enabled: true;
  environment: ConsoleEnvironment;
  baseUrl: URL;
  issuer: URL;
  tenantId: string;
  clientId: string;
  companionClientId: string;
  companionAudience: string;
  companionScope: string;
  redirectUri: string;
  postLogoutRedirectUri: string;
  redisUrl: string;
  cookieSecure: boolean;
  sessionIdleSeconds: number;
  sessionAbsoluteSeconds: number;
  transactionTtlSeconds: number;
  activeEncryptionKeyId: string;
  encryptionKeys: ReadonlyMap<string, Buffer>;
  storageHmacKey: Buffer;
  allowSyntheticAssertion: boolean;
};

export type AuthConfig = DisabledAuthConfig | EnabledAuthConfig;
export type EnvironmentValues = Record<string, string | undefined>;

const ENVIRONMENTS = new Set<ConsoleEnvironment>([
  "local",
  "test",
  "development",
  "staging",
  "production",
]);
const GUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const KEY_ID = /^[A-Za-z0-9._-]{1,64}$/;

export class AuthConfigurationError extends Error {
  constructor() {
    super("Console authentication is unavailable");
    this.name = "AuthConfigurationError";
  }
}

function required(env: EnvironmentValues, name: string): string {
  const value = env[name]?.trim();
  if (!value) throw new AuthConfigurationError();
  return value;
}

function boundedInteger(
  env: EnvironmentValues,
  name: string,
  fallback: number,
  minimum: number,
  maximum: number,
): number {
  const raw = env[name];
  if (raw === undefined) return fallback;
  const value = Number(raw);
  if (!Number.isSafeInteger(value) || value < minimum || value > maximum) {
    throw new AuthConfigurationError();
  }
  return value;
}

function boolean(env: EnvironmentValues, name: string, fallback = false): boolean {
  const raw = env[name];
  if (raw === undefined) return fallback;
  if (raw === "true") return true;
  if (raw === "false") return false;
  throw new AuthConfigurationError();
}

function decodeKey(value: string): Buffer {
  const decoded = Buffer.from(value, "base64");
  if (decoded.length !== 32 || decoded.toString("base64") !== value) {
    throw new AuthConfigurationError();
  }
  return decoded;
}

function parseKeyRing(env: EnvironmentValues): ReadonlyMap<string, Buffer> {
  let parsed: unknown;
  try {
    parsed = JSON.parse(required(env, "REGIMPACT_CONSOLE_ENCRYPTION_KEYS"));
  } catch {
    throw new AuthConfigurationError();
  }
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    throw new AuthConfigurationError();
  }
  const entries = Object.entries(parsed);
  if (entries.length < 1 || entries.length > 3) throw new AuthConfigurationError();
  const keys = new Map<string, Buffer>();
  for (const [keyId, value] of entries) {
    if (!KEY_ID.test(keyId) || typeof value !== "string") throw new AuthConfigurationError();
    keys.set(keyId, decodeKey(value));
  }
  return keys;
}

function isLoopback(hostname: string): boolean {
  return hostname === "localhost" || hostname === "127.0.0.1" || hostname === "::1";
}

function validateBaseUrl(url: URL, environment: ConsoleEnvironment): void {
  if (url.username || url.password || url.search || url.hash || url.pathname !== "/") {
    throw new AuthConfigurationError();
  }
  if (url.protocol === "https:") return;
  if (
    url.protocol !== "http:" ||
    !isLoopback(url.hostname) ||
    !["local", "test"].includes(environment)
  ) {
    throw new AuthConfigurationError();
  }
}

function validateIssuer(url: URL, tenantId: string, environment: ConsoleEnvironment): void {
  if (url.username || url.password || url.search || url.hash) throw new AuthConfigurationError();
  const normalized = url.toString().replace(/\/$/, "");
  if (normalized === `https://login.microsoftonline.com/${tenantId}/v2.0`) return;
  if (
    environment !== "test" ||
    url.protocol !== "http:" ||
    !isLoopback(url.hostname) ||
    url.pathname.replace(/\/$/, "") !== `/${tenantId}/v2.0`
  ) {
    throw new AuthConfigurationError();
  }
}

function validateRedisUrl(value: string, environment: ConsoleEnvironment): void {
  const url = new URL(value);
  if (url.protocol === "rediss:") return;
  if (
    url.protocol !== "redis:" ||
    !["local", "test"].includes(environment) ||
    !(isLoopback(url.hostname) || url.hostname === "console-redis")
  ) {
    throw new AuthConfigurationError();
  }
}

export function loadAuthConfig(env: EnvironmentValues = process.env): AuthConfig {
  const environmentRaw = required(env, "REGIMPACT_CONSOLE_ENVIRONMENT") as ConsoleEnvironment;
  if (!ENVIRONMENTS.has(environmentRaw)) throw new AuthConfigurationError();
  const enabled = boolean(env, "REGIMPACT_CONSOLE_ENTRA_ENABLED");
  if (!enabled) return { enabled: false, environment: environmentRaw };

  const tenantId = required(env, "REGIMPACT_CONSOLE_ENTRA_TENANT_ID");
  const clientId = required(env, "REGIMPACT_CONSOLE_ENTRA_CLIENT_ID");
  const companionClientId = required(env, "REGIMPACT_CONSOLE_COMPANION_CLIENT_ID");
  if (![tenantId, clientId, companionClientId].every((value) => GUID.test(value))) {
    throw new AuthConfigurationError();
  }
  const baseUrl = new URL(required(env, "REGIMPACT_CONSOLE_BASE_URL"));
  const issuer = new URL(required(env, "REGIMPACT_CONSOLE_ENTRA_ISSUER"));
  validateBaseUrl(baseUrl, environmentRaw);
  validateIssuer(issuer, tenantId, environmentRaw);

  const redirectUri = required(env, "REGIMPACT_CONSOLE_ENTRA_REDIRECT_URI");
  const expectedRedirectUri = new URL("/api/auth/entra/callback", baseUrl).toString();
  if (redirectUri !== expectedRedirectUri) throw new AuthConfigurationError();
  const postLogoutRedirectUri = required(env, "REGIMPACT_CONSOLE_POST_LOGOUT_REDIRECT_URI");
  const logoutUrl = new URL(postLogoutRedirectUri);
  if (logoutUrl.origin !== baseUrl.origin || logoutUrl.username || logoutUrl.password) {
    throw new AuthConfigurationError();
  }

  const companionAudience = companionClientId;
  const companionScope = `api://${companionClientId}/companion:access`;
  if (required(env, "REGIMPACT_CONSOLE_COMPANION_SCOPE") !== companionScope) {
    throw new AuthConfigurationError();
  }
  const redisUrl = required(env, "REGIMPACT_CONSOLE_REDIS_URL");
  validateRedisUrl(redisUrl, environmentRaw);
  const cookieSecure = boolean(env, "REGIMPACT_CONSOLE_COOKIE_SECURE");
  if (!["local", "test"].includes(environmentRaw) && !cookieSecure) {
    throw new AuthConfigurationError();
  }
  const allowSyntheticAssertion = boolean(
    env,
    "REGIMPACT_CONSOLE_ALLOW_SYNTHETIC_ASSERTION",
  );
  if (allowSyntheticAssertion && environmentRaw !== "test") throw new AuthConfigurationError();

  const encryptionKeys = parseKeyRing(env);
  const activeEncryptionKeyId = required(env, "REGIMPACT_CONSOLE_ACTIVE_ENCRYPTION_KEY_ID");
  if (!encryptionKeys.has(activeEncryptionKeyId)) throw new AuthConfigurationError();
  const storageHmacKey = decodeKey(required(env, "REGIMPACT_CONSOLE_STORAGE_HMAC_KEY"));
  if (isIP(baseUrl.hostname) === 0 && baseUrl.hostname.endsWith(".")) {
    throw new AuthConfigurationError();
  }

  return {
    enabled: true,
    environment: environmentRaw,
    baseUrl,
    issuer,
    tenantId,
    clientId,
    companionClientId,
    companionAudience,
    companionScope,
    redirectUri,
    postLogoutRedirectUri,
    redisUrl,
    cookieSecure,
    sessionIdleSeconds: boundedInteger(
      env,
      "REGIMPACT_CONSOLE_SESSION_IDLE_SECONDS",
      1800,
      60,
      1800,
    ),
    sessionAbsoluteSeconds: boundedInteger(
      env,
      "REGIMPACT_CONSOLE_SESSION_ABSOLUTE_SECONDS",
      28800,
      300,
      28800,
    ),
    transactionTtlSeconds: boundedInteger(
      env,
      "REGIMPACT_CONSOLE_AUTH_TRANSACTION_TTL_SECONDS",
      300,
      60,
      600,
    ),
    activeEncryptionKeyId,
    encryptionKeys,
    storageHmacKey,
    allowSyntheticAssertion,
  };
}

export function safeReturnDestination(candidate: string | null): string {
  if (!candidate) return "/";
  if (
    candidate.length > 512 ||
    !candidate.startsWith("/") ||
    candidate.startsWith("//") ||
    candidate.includes("\\") ||
    /[\u0000-\u001f\u007f]/.test(candidate)
  ) {
    return "/";
  }
  return candidate;
}
