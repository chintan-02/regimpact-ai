import { createHash } from "node:crypto";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";

import { exportJWK, generateKeyPair, SignJWT } from "jose";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { SyntheticAssertionProvider } from "../lib/auth/assertion";
import { ConsoleAuthService } from "../lib/auth/oidc";
import { AuthStore } from "../lib/auth/store";
import {
  COMPANION_CLIENT_ID,
  CONSOLE_CLIENT_ID,
  FakeRedis,
  TENANT_ID,
  testConfig,
} from "./auth-helpers";

type TokenMode =
  | "valid"
  | "wrong_nonce"
  | "wrong_audience"
  | "expired"
  | "wrong_signature"
  | "unknown_key";

class MockIdentityProvider {
  private server = createServer((request, response) => void this.handle(request, response));
  private privateKey!: CryptoKey;
  private publicJwk!: Record<string, unknown>;
  private otherPrivateKey!: CryptoKey;
  origin = "";
  issuer = "";
  expectedNonce = "";
  expectedChallenge = "";
  mode: TokenMode = "valid";
  jwksUnavailable = false;
  tokenRequests = 0;

  async start(): Promise<void> {
    const primary = await generateKeyPair("RS256", { extractable: true });
    const other = await generateKeyPair("RS256", { extractable: true });
    this.privateKey = primary.privateKey;
    this.otherPrivateKey = other.privateKey;
    this.publicJwk = {
      ...(await exportJWK(primary.publicKey)),
      kid: "test-key",
      alg: "RS256",
      use: "sig",
    };
    await new Promise<void>((resolve) => this.server.listen(0, "127.0.0.1", resolve));
    const address = this.server.address();
    if (address === null || typeof address === "string") throw new Error("mock issuer unavailable");
    this.origin = `http://127.0.0.1:${address.port}`;
    this.issuer = `${this.origin}/${TENANT_ID}/v2.0`;
  }

  async stop(): Promise<void> {
    await new Promise<void>((resolve, reject) =>
      this.server.close((error) => (error ? reject(error) : resolve())),
    );
  }

  private async handle(request: IncomingMessage, response: ServerResponse): Promise<void> {
    const url = new URL(request.url ?? "/", this.origin);
    if (url.pathname === `/${TENANT_ID}/v2.0/.well-known/openid-configuration`) {
      return this.json(response, 200, {
        issuer: this.issuer,
        authorization_endpoint: `${this.origin}/${TENANT_ID}/oauth2/v2.0/authorize`,
        token_endpoint: `${this.origin}/${TENANT_ID}/oauth2/v2.0/token`,
        jwks_uri: `${this.origin}/${TENANT_ID}/discovery/v2.0/keys`,
        response_types_supported: ["code"],
        subject_types_supported: ["pairwise"],
        id_token_signing_alg_values_supported: ["RS256"],
        token_endpoint_auth_methods_supported: ["private_key_jwt"],
        code_challenge_methods_supported: ["S256"],
      });
    }
    if (url.pathname === `/${TENANT_ID}/discovery/v2.0/keys`) {
      if (this.jwksUnavailable) return this.json(response, 503, { error: "unavailable" });
      return this.json(response, 200, { keys: [this.publicJwk] });
    }
    if (url.pathname === `/${TENANT_ID}/oauth2/v2.0/token` && request.method === "POST") {
      this.tokenRequests += 1;
      const body = new URLSearchParams(await readBody(request));
      const verifier = body.get("code_verifier") ?? "";
      const challenge = createHash("sha256").update(verifier).digest("base64url");
      if (
        body.get("client_id") !== CONSOLE_CLIENT_ID ||
        body.get("client_assertion") !== "synthetic-client-assertion" ||
        body.get("client_assertion_type") !==
          "urn:ietf:params:oauth:client-assertion-type:jwt-bearer" ||
        body.get("redirect_uri") !== "http://localhost:3000/api/auth/entra/callback" ||
        body.get("code") !== "valid-code" ||
        challenge !== this.expectedChallenge
      ) {
        return this.json(response, 400, { error: "invalid_grant" });
      }
      const now = Math.floor(Date.now() / 1000);
      const nonce = this.mode === "wrong_nonce" ? "wrong-nonce" : this.expectedNonce;
      const audience = this.mode === "wrong_audience" ? COMPANION_CLIENT_ID : CONSOLE_CLIENT_ID;
      const expiration = this.mode === "expired" ? now - 600 : now + 600;
      const signingKey = this.mode === "wrong_signature" ? this.otherPrivateKey : this.privateKey;
      const idToken = await new SignJWT({
        tid: TENANT_ID,
        oid: "00000000-0000-4000-8000-000000000004",
        ver: "2.0",
        nonce,
      })
        .setProtectedHeader({
          alg: "RS256",
          kid: this.mode === "unknown_key" ? "unknown-key" : "test-key",
          typ: "JWT",
        })
        .setIssuer(this.issuer)
        .setAudience(audience)
        .setSubject("synthetic-subject")
        .setIssuedAt(now)
        .setNotBefore(now - 1)
        .setExpirationTime(expiration)
        .sign(signingKey);
      return this.json(response, 200, {
        token_type: "Bearer",
        access_token: "server-only-companion-access-token",
        refresh_token: "server-only-refresh-token",
        id_token: idToken,
        expires_in: 600,
        scope: `openid profile offline_access api://${COMPANION_CLIENT_ID}/companion:access`,
      });
    }
    this.json(response, 404, { error: "not_found" });
  }

  private json(response: ServerResponse, status: number, body: object): void {
    response.writeHead(status, { "Content-Type": "application/json" });
    response.end(JSON.stringify(body));
  }
}

function readBody(request: IncomingMessage): Promise<string> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    request.on("data", (chunk: Buffer) => chunks.push(chunk));
    request.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
    request.on("error", reject);
  });
}

describe("console OIDC and protected session flow", () => {
  let provider: MockIdentityProvider;

  beforeEach(async () => {
    provider = new MockIdentityProvider();
    await provider.start();
  });

  afterEach(async () => {
    await provider.stop();
  });

  function service(now = Math.floor(Date.now() / 1000)) {
    const config = testConfig({ issuer: new URL(provider.issuer) });
    const redis = new FakeRedis(() => now);
    const store = new AuthStore(config, redis, undefined, () => now);
    const assertion = new SyntheticAssertionProvider(config, async () => "synthetic-client-assertion");
    return { config, redis, store, auth: new ConsoleAuthService(config, store, assertion, () => now) };
  }

  async function login(auth: ConsoleAuthService): Promise<{ state: string; url: URL }> {
    const result = await auth.beginLogin("/review?item=1");
    const state = result.authorizationUrl.searchParams.get("state");
    const nonce = result.authorizationUrl.searchParams.get("nonce");
    const challenge = result.authorizationUrl.searchParams.get("code_challenge");
    if (!state || !nonce || !challenge) throw new Error("login transaction incomplete");
    provider.expectedNonce = nonce;
    provider.expectedChallenge = challenge;
    return { state, url: result.authorizationUrl };
  }

  it("completes PKCE, rotates the session, and keeps every token server-side", async () => {
    const { config, store, auth } = service();
    const oldSession = "old-session-value-that-is-long-enough-1234567890";
    const oldCsrf = "old-csrf-value-that-is-long-enough-1234567890";
    const now = Math.floor(Date.now() / 1000);
    await store.createSession(oldSession, {
      createdAt: now,
      lastSeenAt: now,
      absoluteExpiresAt: now + 1000,
      tenantId: TENANT_ID,
      objectId: "00000000-0000-4000-8000-000000000004",
      subject: "old",
      csrfHash: store.csrfFingerprint(oldCsrf),
      idToken: "old-token",
    });
    const { state, url } = await login(auth);
    expect(url.searchParams.get("code_challenge_method")).toBe("S256");
    expect(url.searchParams.get("scope")).toContain(config.companionScope);
    expect(url.toString()).not.toContain("server-only");

    const callback = new URL(config.redirectUri);
    callback.searchParams.set("code", "valid-code");
    callback.searchParams.set("state", state);
    const result = await auth.completeCallback(callback, oldSession);
    expect(result.returnTo).toBe("/review?item=1");
    expect(JSON.stringify(result)).not.toContain("server-only");
    expect(result.sessionId).not.toBe(oldSession);
    await expect(store.getSession(oldSession)).rejects.toThrow();
    expect(await auth.getCompanionAccessToken(result.sessionId)).toBe(
      "server-only-companion-access-token",
    );
    await expect(auth.logout(result.sessionId, "wrong-csrf-value-that-is-long-enough-123456")).rejects.toThrow();
    await auth.logout(result.sessionId, result.csrfToken);
    await expect(auth.getSession(result.sessionId)).rejects.toThrow();
  });

  it("atomically rejects callback replay and races", async () => {
    const { config, auth } = service();
    const { state } = await login(auth);
    const callback = new URL(config.redirectUri);
    callback.searchParams.set("code", "valid-code");
    callback.searchParams.set("state", state);
    const outcomes = await Promise.allSettled([
      auth.completeCallback(callback),
      auth.completeCallback(callback),
    ]);
    expect(outcomes.filter((item) => item.status === "fulfilled")).toHaveLength(1);
    expect(outcomes.filter((item) => item.status === "rejected")).toHaveLength(1);
    expect(provider.tokenRequests).toBe(1);
  });

  it.each<TokenMode>([
    "wrong_nonce",
    "wrong_audience",
    "expired",
    "wrong_signature",
    "unknown_key",
  ])(
    "fails closed for %s ID token",
    async (mode) => {
      const { config, auth } = service();
      provider.mode = mode;
      const { state } = await login(auth);
      const callback = new URL(config.redirectUri);
      callback.searchParams.set("code", "valid-code");
      callback.searchParams.set("state", state);
      await expect(auth.completeCallback(callback)).rejects.toThrow("Authentication failed");
    },
  );

  it("fails closed when JWKS retrieval is unavailable", async () => {
    const { config, auth } = service();
    const { state } = await login(auth);
    provider.jwksUnavailable = true;
    const callback = new URL(config.redirectUri);
    callback.searchParams.set("code", "valid-code");
    callback.searchParams.set("state", state);
    await expect(auth.completeCallback(callback)).rejects.toThrow("Authentication failed");
  });

  it("fails closed when confidential-client assertion acquisition fails", async () => {
    const { config, store } = service();
    const auth = new ConsoleAuthService(config, store, {
      getAssertion: async () => {
        throw new Error("confidential proof unavailable");
      },
    });
    const { state } = await login(auth);
    const callback = new URL(config.redirectUri);
    callback.searchParams.set("code", "valid-code");
    callback.searchParams.set("state", state);
    await expect(auth.completeCallback(callback)).rejects.toThrow("Authentication failed");
    expect(provider.tokenRequests).toBe(0);
  });

  it("rejects invalid state, authorization errors, PKCE mismatch, and callback origins", async () => {
    const { config, store, auth } = service();
    const { state } = await login(auth);
    const foreign = new URL(`http://evil.test/api/auth/entra/callback?code=valid-code&state=${state}`);
    await expect(auth.completeCallback(foreign)).rejects.toThrow();

    const errorCallback = new URL(config.redirectUri);
    errorCallback.searchParams.set("state", state);
    errorCallback.searchParams.set("error", "access_denied");
    await expect(auth.completeCallback(errorCallback)).rejects.toThrow();
    await expect(auth.completeCallback(errorCallback)).rejects.toThrow();

    const manualState = "manual-state-value-that-is-long-enough-1234567890";
    provider.expectedChallenge = "not-the-actual-challenge";
    await store.createTransaction(manualState, {
      nonce: "nonce-value",
      verifier: "wrong-verifier-value-that-is-long-enough-1234567890",
      returnTo: "/",
      createdAt: Math.floor(Date.now() / 1000),
      expiresAt: Math.floor(Date.now() / 1000) + 300,
    });
    const pkceCallback = new URL(config.redirectUri);
    pkceCallback.searchParams.set("code", "valid-code");
    pkceCallback.searchParams.set("state", manualState);
    await expect(auth.completeCallback(pkceCallback)).rejects.toThrow();
  });

  it("rejects a synthetic assertion provider outside explicit test configuration", () => {
    const config = testConfig({ environment: "staging", allowSyntheticAssertion: false });
    expect(
      () => new SyntheticAssertionProvider(config, async () => "synthetic-client-assertion"),
    ).toThrow("test-only");
  });

  it("does not log tokens, claims, authorization codes, or assertions", async () => {
    const writes: string[] = [];
    const original = process.stdout.write.bind(process.stdout);
    process.stdout.write = ((chunk: string | Uint8Array) => {
      writes.push(chunk.toString());
      return true;
    }) as typeof process.stdout.write;
    try {
      const { config, auth } = service();
      const { state } = await login(auth);
      const callback = new URL(config.redirectUri);
      callback.searchParams.set("code", "valid-code");
      callback.searchParams.set("state", state);
      await auth.completeCallback(callback);
    } finally {
      process.stdout.write = original;
    }
    const output = writes.join("");
    for (const sensitive of [
      "server-only-companion-access-token",
      "server-only-refresh-token",
      "synthetic-subject",
      "synthetic-client-assertion",
      "valid-code",
    ]) {
      expect(output).not.toContain(sensitive);
    }
    for (const line of output.trim().split("\n")) expect(() => JSON.parse(line)).not.toThrow();
  });
});
