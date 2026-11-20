import { randomBytes } from "node:crypto";

import {
  None,
  allowInsecureRequests,
  authorizationCodeGrant,
  buildAuthorizationUrl,
  calculatePKCECodeChallenge,
  customFetch,
  discovery,
  enableNonRepudiationChecks,
  randomNonce,
  randomPKCECodeVerifier,
  randomState,
  type ClientAuth,
  type Configuration,
  type CustomFetch,
} from "openid-client";

import {
  CLIENT_ASSERTION_TYPE,
  type ConfidentialClientAssertionProvider,
} from "./assertion";
import type { EnabledAuthConfig } from "./config";
import { safeReturnDestination } from "./config";
import { logAuthEvent } from "./logging";
import { AuthStore, type ConsoleSession } from "./store";

const OPAQUE_VALUE = /^[A-Za-z0-9_-]{32,256}$/;

export class ConsoleAuthenticationError extends Error {
  constructor() {
    super("Authentication failed");
    this.name = "ConsoleAuthenticationError";
  }
}

export type LoginResult = { authorizationUrl: URL };
export type CallbackResult = { sessionId: string; csrfToken: string; returnTo: string };

export class ConsoleAuthService {
  constructor(
    private readonly config: EnabledAuthConfig,
    private readonly store: AuthStore,
    private readonly assertionProvider: ConfidentialClientAssertionProvider,
    private readonly clock: () => number = () => Math.floor(Date.now() / 1000),
  ) {}

  async beginLogin(returnToCandidate: string | null): Promise<LoginResult> {
    try {
      const state = randomState();
      const nonce = randomNonce();
      const verifier = randomPKCECodeVerifier();
      const challenge = await calculatePKCECodeChallenge(verifier);
      const now = this.clock();
      await this.store.createTransaction(state, {
        nonce,
        verifier,
        returnTo: safeReturnDestination(returnToCandidate),
        createdAt: now,
        expiresAt: now + this.config.transactionTtlSeconds,
      });
      const client = await this.clientConfiguration(None());
      if (!client.serverMetadata().supportsPKCE("S256")) throw new ConsoleAuthenticationError();
      const authorizationUrl = buildAuthorizationUrl(client, {
        redirect_uri: this.config.redirectUri,
        response_type: "code",
        scope: `openid profile offline_access ${this.config.companionScope}`,
        state,
        nonce,
        code_challenge: challenge,
        code_challenge_method: "S256",
      });
      logAuthEvent("entra_login_started");
      return { authorizationUrl };
    } catch {
      logAuthEvent("entra_dependency_unavailable");
      throw new ConsoleAuthenticationError();
    }
  }

  async completeCallback(callbackUrl: URL, previousSessionId?: string): Promise<CallbackResult> {
    let state: string | null = null;
    try {
      this.validateCallbackUrl(callbackUrl);
      state = callbackUrl.searchParams.get("state");
      if (state === null || !OPAQUE_VALUE.test(state)) throw new ConsoleAuthenticationError();
      const transaction = await this.store.consumeTransaction(state);
      if (callbackUrl.searchParams.has("error")) throw new ConsoleAuthenticationError();
      const assertion = await this.assertionProvider.getAssertion();
      const client = await this.clientConfiguration(assertionClientAuth(assertion));
      const tokens = await authorizationCodeGrant(client, callbackUrl, {
        expectedState: state,
        expectedNonce: transaction.nonce,
        pkceCodeVerifier: transaction.verifier,
        idTokenExpected: true,
      });
      const claims = tokens.claims();
      const accessToken = tokens.access_token;
      const idToken = tokens.id_token;
      const expiresIn = tokens.expires_in;
      const grantedScopes = (tokens.scope ?? "").split(" ").filter(Boolean);
      if (
        claims === undefined ||
        typeof accessToken !== "string" ||
        typeof idToken !== "string" ||
        typeof expiresIn !== "number" ||
        !Number.isFinite(expiresIn) ||
        expiresIn <= 0 ||
        expiresIn > 86400 ||
        !grantedScopes.includes(this.config.companionScope)
      ) {
        throw new ConsoleAuthenticationError();
      }
      const tenantId = claimString(claims.tid);
      const objectId = claimString(claims.oid);
      const subject = claimString(claims.sub);
      if (
        claims.ver !== "2.0" ||
        tenantId !== this.config.tenantId ||
        !guid(objectId) ||
        subject.length > 255
      ) {
        throw new ConsoleAuthenticationError();
      }

      if (previousSessionId && OPAQUE_VALUE.test(previousSessionId)) {
        await this.store.purgeSession(previousSessionId);
      }
      const now = this.clock();
      const sessionId = randomOpaqueValue();
      const csrfToken = randomOpaqueValue();
      const session: ConsoleSession = {
        createdAt: now,
        lastSeenAt: now,
        absoluteExpiresAt: now + this.config.sessionAbsoluteSeconds,
        tenantId,
        objectId,
        subject,
        csrfHash: this.store.csrfFingerprint(csrfToken),
        idToken,
        ...(tokens.refresh_token ? { refreshToken: tokens.refresh_token } : {}),
      };
      await this.store.createSession(sessionId, session);
      try {
        await this.store.cacheToken(sessionId, session, {
          accessToken,
          audience: this.config.companionAudience,
          scopes: [this.config.companionScope],
          expiresAt: Math.min(now + Math.floor(expiresIn), session.absoluteExpiresAt),
        });
      } catch (error) {
        await this.store.purgeSession(sessionId);
        throw error;
      }
      logAuthEvent("entra_callback_succeeded");
      return { sessionId, csrfToken, returnTo: transaction.returnTo };
    } catch {
      logAuthEvent("entra_callback_denied");
      throw new ConsoleAuthenticationError();
    }
  }

  async getSession(sessionId: string): Promise<ConsoleSession> {
    if (!OPAQUE_VALUE.test(sessionId)) throw new ConsoleAuthenticationError();
    try {
      return await this.store.getSession(sessionId);
    } catch {
      throw new ConsoleAuthenticationError();
    }
  }

  async getCompanionAccessToken(sessionId: string): Promise<string> {
    const session = await this.getSession(sessionId);
    try {
      const token = await this.store.getToken(
        sessionId,
        session,
        this.config.companionAudience,
        [this.config.companionScope],
      );
      return token.accessToken;
    } catch {
      throw new ConsoleAuthenticationError();
    }
  }

  async logout(sessionId: string, csrfToken: string): Promise<void> {
    try {
      const session = await this.getSession(sessionId);
      if (!OPAQUE_VALUE.test(csrfToken) || !this.store.csrfMatches(session, csrfToken)) {
        throw new ConsoleAuthenticationError();
      }
      await this.store.purgeSession(sessionId);
      logAuthEvent("entra_session_revoked");
    } catch {
      throw new ConsoleAuthenticationError();
    }
  }

  private async clientConfiguration(clientAuth: ClientAuth): Promise<Configuration> {
    const execute = [enableNonRepudiationChecks];
    if (this.config.issuer.protocol === "http:") execute.push(allowInsecureRequests);
    return discovery(
      this.config.issuer,
      this.config.clientId,
      {
        redirect_uris: [this.config.redirectUri],
        response_types: ["code"],
        token_endpoint_auth_method: "private_key_jwt",
      },
      clientAuth,
      {
        [customFetch]: this.restrictedFetch(),
        timeout: 5,
        execute,
      },
    );
  }

  private restrictedFetch(): CustomFetch {
    const issuer = this.config.issuer;
    return async (url, options) => {
      const target = new URL(url);
      if (
        target.origin !== issuer.origin ||
        target.username ||
        target.password ||
        target.protocol !== issuer.protocol
      ) {
        throw new ConsoleAuthenticationError();
      }
      const response = await fetch(target, {
        method: options.method,
        headers: options.headers,
        body: options.body as BodyInit | null | undefined,
        signal: options.signal,
        redirect: "manual",
      });
      if (response.status >= 300 && response.status < 400) throw new ConsoleAuthenticationError();
      return response;
    };
  }

  private validateCallbackUrl(callbackUrl: URL): void {
    const expected = new URL(this.config.redirectUri);
    if (
      callbackUrl.origin !== expected.origin ||
      callbackUrl.pathname !== expected.pathname ||
      callbackUrl.hash
    ) {
      throw new ConsoleAuthenticationError();
    }
  }
}

function assertionClientAuth(assertion: string): ClientAuth {
  return (_server, client, body) => {
    body.set("client_id", client.client_id);
    body.set("client_assertion_type", CLIENT_ASSERTION_TYPE);
    body.set("client_assertion", assertion);
  };
}

function randomOpaqueValue(): string {
  return randomBytes(32).toString("base64url");
}

function claimString(value: unknown): string {
  if (typeof value !== "string" || value.length === 0) throw new ConsoleAuthenticationError();
  return value;
}

function guid(value: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(
    value,
  );
}
