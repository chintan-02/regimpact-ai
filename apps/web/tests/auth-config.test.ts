import { describe, expect, it } from "vitest";

import {
  AuthConfigurationError,
  type EnvironmentValues,
  loadAuthConfig,
  safeReturnDestination,
} from "../lib/auth/config";
import { COMPANION_CLIENT_ID, CONSOLE_CLIENT_ID, TENANT_ID } from "./auth-helpers";

function environment(overrides: EnvironmentValues = {}): EnvironmentValues {
  const key = Buffer.alloc(32, 3).toString("base64");
  return {
    REGIMPACT_CONSOLE_ENVIRONMENT: "test",
    REGIMPACT_CONSOLE_ENTRA_ENABLED: "true",
    REGIMPACT_CONSOLE_BASE_URL: "http://localhost:3000/",
    REGIMPACT_CONSOLE_ENTRA_TENANT_ID: TENANT_ID,
    REGIMPACT_CONSOLE_ENTRA_CLIENT_ID: CONSOLE_CLIENT_ID,
    REGIMPACT_CONSOLE_ENTRA_ISSUER: `http://127.0.0.1:9876/${TENANT_ID}/v2.0`,
    REGIMPACT_CONSOLE_ENTRA_REDIRECT_URI: "http://localhost:3000/api/auth/entra/callback",
    REGIMPACT_CONSOLE_POST_LOGOUT_REDIRECT_URI: "http://localhost:3000/login",
    REGIMPACT_CONSOLE_COMPANION_CLIENT_ID: COMPANION_CLIENT_ID,
    REGIMPACT_CONSOLE_COMPANION_SCOPE: `api://${COMPANION_CLIENT_ID}/companion:access`,
    REGIMPACT_CONSOLE_REDIS_URL: "redis://127.0.0.1:6380/0",
    REGIMPACT_CONSOLE_COOKIE_SECURE: "false",
    REGIMPACT_CONSOLE_ALLOW_SYNTHETIC_ASSERTION: "true",
    REGIMPACT_CONSOLE_ENCRYPTION_KEYS: JSON.stringify({ "test-v1": key }),
    REGIMPACT_CONSOLE_ACTIVE_ENCRYPTION_KEY_ID: "test-v1",
    REGIMPACT_CONSOLE_STORAGE_HMAC_KEY: key,
    ...overrides,
  };
}

describe("console authentication configuration", () => {
  it("loads a complete explicit test configuration", () => {
    const config = loadAuthConfig(environment());
    expect(config.enabled).toBe(true);
    if (config.enabled) {
      expect(config.companionScope).toBe(`api://${COMPANION_CLIENT_ID}/companion:access`);
      expect(config.sessionIdleSeconds).toBe(1800);
      expect(config.sessionAbsoluteSeconds).toBe(28800);
    }
  });

  it("is disabled rather than partially configured when explicitly off", () => {
    expect(
      loadAuthConfig({
        REGIMPACT_CONSOLE_ENVIRONMENT: "local",
        REGIMPACT_CONSOLE_ENTRA_ENABLED: "false",
      }),
    ).toEqual({ enabled: false, environment: "local" });
  });

  it.each([
    ["missing environment", {}],
    ["wrong scope", { REGIMPACT_CONSOLE_COMPANION_SCOPE: "companion:access" }],
    ["open redirect", { REGIMPACT_CONSOLE_POST_LOGOUT_REDIRECT_URI: "https://evil.test/" }],
    ["shared redis", { REGIMPACT_CONSOLE_REDIS_URL: "redis://backend-redis:6379/0" }],
    ["mock in production", { REGIMPACT_CONSOLE_ENVIRONMENT: "production" }],
    [
      "arbitrary development issuer",
      {
        REGIMPACT_CONSOLE_ENVIRONMENT: "development",
        REGIMPACT_CONSOLE_ENTRA_ISSUER: `https://issuer.example.test/${TENANT_ID}/v2.0`,
      },
    ],
    [
      "wrong mock tenant path",
      { REGIMPACT_CONSOLE_ENTRA_ISSUER: "http://127.0.0.1:9876/common/v2.0" },
    ],
  ])("fails closed for %s", (_name, override) => {
    const input = _name === "missing environment" ? {} : environment(override);
    expect(() => loadAuthConfig(input)).toThrow(AuthConfigurationError);
  });

  it("rejects staging wildcard/non-tenant issuer and insecure cookies", () => {
    expect(() =>
      loadAuthConfig(
        environment({
          REGIMPACT_CONSOLE_ENVIRONMENT: "staging",
          REGIMPACT_CONSOLE_BASE_URL: "https://console.example.test/",
          REGIMPACT_CONSOLE_ENTRA_REDIRECT_URI:
            "https://console.example.test/api/auth/entra/callback",
          REGIMPACT_CONSOLE_POST_LOGOUT_REDIRECT_URI: "https://console.example.test/login",
          REGIMPACT_CONSOLE_ENTRA_ISSUER: "https://login.microsoftonline.com/common/v2.0",
          REGIMPACT_CONSOLE_REDIS_URL: "rediss://cache.example.test:6380/0",
          REGIMPACT_CONSOLE_ALLOW_SYNTHETIC_ASSERTION: "false",
          REGIMPACT_CONSOLE_COOKIE_SECURE: "false",
        }),
      ),
    ).toThrow(AuthConfigurationError);
  });

  it("bounds return destinations to local relative paths", () => {
    expect(safeReturnDestination("/review?item=1")).toBe("/review?item=1");
    expect(safeReturnDestination("https://evil.test/")).toBe("/");
    expect(safeReturnDestination("//evil.test/")).toBe("/");
    expect(safeReturnDestination("/\\evil.test")).toBe("/");
  });
});
