import { createClient, type RedisClientType } from "redis";

import type { EnabledAuthConfig } from "./config";
import { ProtectedRecordError, RecordProtector } from "./crypto";

export type AuthorizationTransaction = {
  nonce: string;
  verifier: string;
  returnTo: string;
  createdAt: number;
  expiresAt: number;
};

export type ConsoleSession = {
  createdAt: number;
  lastSeenAt: number;
  absoluteExpiresAt: number;
  tenantId: string;
  objectId: string;
  subject: string;
  csrfHash: string;
  idToken: string;
  refreshToken?: string;
};

export type CachedAccessToken = {
  accessToken: string;
  audience: string;
  scopes: string[];
  expiresAt: number;
};

export interface RedisCommands {
  get(key: string): Promise<string | null>;
  getDel(key: string): Promise<string | null>;
  set(key: string, value: string, ttlSeconds: number, onlyIfAbsent: boolean): Promise<boolean>;
  del(keys: string[]): Promise<number>;
  sAdd(key: string, value: string): Promise<number>;
  sMembers(key: string): Promise<string[]>;
  expire(key: string, ttlSeconds: number): Promise<boolean>;
  compareAndTouch(
    key: string,
    expectedValue: string,
    replacementValue: string,
    ttlSeconds: number,
  ): Promise<boolean>;
  purgeIndexed(sessionKey: string, indexKey: string): Promise<number>;
  close(): Promise<void>;
}

export class NodeRedisCommands implements RedisCommands {
  private readonly client: RedisClientType;
  private connecting: Promise<unknown> | null = null;

  constructor(url: string) {
    this.client = createClient({
      url,
      socket: {
        connectTimeout: 1_000,
        reconnectStrategy: false,
      },
    });
    this.client.on("error", () => undefined);
  }

  async get(key: string): Promise<string | null> {
    await this.ready();
    return this.client.get(key);
  }

  async getDel(key: string): Promise<string | null> {
    await this.ready();
    return this.client.getDel(key);
  }

  async set(
    key: string,
    value: string,
    ttlSeconds: number,
    onlyIfAbsent: boolean,
  ): Promise<boolean> {
    await this.ready();
    const result = onlyIfAbsent
      ? await this.client.set(key, value, { EX: ttlSeconds, NX: true })
      : await this.client.set(key, value, { EX: ttlSeconds });
    return result === "OK";
  }

  async del(keys: string[]): Promise<number> {
    if (keys.length === 0) return 0;
    await this.ready();
    return this.client.del(keys);
  }

  async sAdd(key: string, value: string): Promise<number> {
    await this.ready();
    return this.client.sAdd(key, value);
  }

  async sMembers(key: string): Promise<string[]> {
    await this.ready();
    return this.client.sMembers(key);
  }

  async expire(key: string, ttlSeconds: number): Promise<boolean> {
    await this.ready();
    return (await this.client.expire(key, ttlSeconds)) === 1;
  }

  async compareAndTouch(
    key: string,
    expectedValue: string,
    replacementValue: string,
    ttlSeconds: number,
  ): Promise<boolean> {
    await this.ready();
    const result = await this.client.eval(
      "if redis.call('GET', KEYS[1]) == ARGV[1] then redis.call('SET', KEYS[1], ARGV[2], 'EX', ARGV[3]); return 1 else return 0 end",
      {
        keys: [key],
        arguments: [expectedValue, replacementValue, String(ttlSeconds)],
      },
    );
    return result === 1;
  }

  async purgeIndexed(sessionKey: string, indexKey: string): Promise<number> {
    await this.ready();
    const result = await this.client.eval(
      "local keys = redis.call('SMEMBERS', KEYS[2]); table.insert(keys, KEYS[1]); table.insert(keys, KEYS[2]); return redis.call('DEL', unpack(keys))",
      { keys: [sessionKey, indexKey], arguments: [] },
    );
    return typeof result === "number" ? result : 0;
  }

  async close(): Promise<void> {
    if (this.client.isOpen) await this.client.close();
  }

  private async ready(): Promise<void> {
    if (this.client.isReady) return;
    this.connecting ??= this.client.connect().finally(() => {
      this.connecting = null;
    });
    await this.connecting;
    if (!this.client.isReady) throw new Error("Session store unavailable");
  }
}

export class AuthStore {
  constructor(
    private readonly config: EnabledAuthConfig,
    private readonly redis: RedisCommands,
    private readonly protector = new RecordProtector(config),
    private readonly now: () => number = () => Math.floor(Date.now() / 1000),
  ) {}

  async createTransaction(state: string, transaction: AuthorizationTransaction): Promise<void> {
    const key = this.protector.storageKey("transaction", state);
    const value = this.protector.encrypt(transaction, key, "transaction");
    const created = await this.redis.set(
      key,
      value,
      this.config.transactionTtlSeconds,
      true,
    );
    if (!created) throw new Error("Authentication transaction unavailable");
  }

  async consumeTransaction(state: string): Promise<AuthorizationTransaction> {
    const key = this.protector.storageKey("transaction", state);
    const value = await this.redis.getDel(key);
    if (value === null) throw new Error("Authentication transaction unavailable");
    const transaction = this.protector.decrypt<AuthorizationTransaction>(value, key, "transaction");
    if (transaction.expiresAt <= this.now()) throw new Error("Authentication transaction unavailable");
    return transaction;
  }

  async createSession(sessionId: string, session: ConsoleSession): Promise<void> {
    const key = this.sessionKey(sessionId);
    const ttl = this.sessionTtl(session);
    if (ttl <= 0) throw new Error("Session unavailable");
    const created = await this.redis.set(
      key,
      this.protector.encrypt(session, key, "session"),
      ttl,
      true,
    );
    if (!created) throw new Error("Session unavailable");
  }

  async getSession(sessionId: string): Promise<ConsoleSession> {
    const key = this.sessionKey(sessionId);
    const value = await this.redis.get(key);
    if (value === null) throw new Error("Session unavailable");
    let session: ConsoleSession;
    try {
      session = this.protector.decrypt<ConsoleSession>(value, key, "session");
    } catch (error) {
      await this.redis.del([key]);
      throw error;
    }
    const now = this.now();
    if (
      session.absoluteExpiresAt <= now ||
      now - session.lastSeenAt >= this.config.sessionIdleSeconds
    ) {
      await this.purgeSession(sessionId);
      throw new Error("Session unavailable");
    }
    const touched = { ...session, lastSeenAt: now };
    const ttl = this.sessionTtl(touched);
    if (
      !(await this.redis.compareAndTouch(
        key,
        value,
        this.protector.encrypt(touched, key, "session"),
        ttl,
      ))
    ) {
      throw new Error("Session unavailable");
    }
    return touched;
  }

  async cacheToken(
    sessionId: string,
    session: ConsoleSession,
    token: CachedAccessToken,
  ): Promise<void> {
    const scopes = canonicalScopes(token.scopes);
    const key = this.tokenKey(sessionId, session, token.audience, scopes);
    const ttl =
      Math.min(
        token.expiresAt,
        session.absoluteExpiresAt,
        session.lastSeenAt + this.config.sessionIdleSeconds,
      ) - this.now();
    if (ttl <= 0) throw new Error("Token unavailable");
    const normalized = { ...token, scopes };
    if (!(await this.redis.set(key, this.protector.encrypt(normalized, key, "token"), ttl, false))) {
      throw new Error("Token unavailable");
    }
    const indexKey = this.indexKey(sessionId);
    await this.redis.sAdd(indexKey, key);
    await this.redis.expire(indexKey, this.sessionTtl(session));
  }

  async getToken(
    sessionId: string,
    session: ConsoleSession,
    audience: string,
    scopes: string[],
  ): Promise<CachedAccessToken> {
    const key = this.tokenKey(sessionId, session, audience, canonicalScopes(scopes));
    const value = await this.redis.get(key);
    if (value === null) throw new Error("Token unavailable");
    try {
      const token = this.protector.decrypt<CachedAccessToken>(value, key, "token");
      if (token.expiresAt <= this.now()) {
        await this.redis.del([key]);
        throw new Error("Token unavailable");
      }
      return token;
    } catch (error) {
      if (error instanceof ProtectedRecordError) await this.redis.del([key]);
      throw error;
    }
  }

  async purgeSession(sessionId: string): Promise<void> {
    const indexKey = this.indexKey(sessionId);
    await this.redis.purgeIndexed(this.sessionKey(sessionId), indexKey);
  }

  csrfMatches(session: ConsoleSession, csrfToken: string): boolean {
    return this.protector.equalFingerprint(csrfToken, session.csrfHash);
  }

  csrfFingerprint(csrfToken: string): string {
    return this.protector.fingerprint(csrfToken);
  }

  randomOpaqueIdentifier(): string {
    return this.protector.randomOpaqueIdentifier();
  }

  private sessionKey(sessionId: string): string {
    return this.protector.storageKey("session", sessionId);
  }

  private indexKey(sessionId: string): string {
    return this.protector.storageKey("token-index", sessionId);
  }

  private tokenKey(
    sessionId: string,
    session: ConsoleSession,
    audience: string,
    scopes: string[],
  ): string {
    return this.protector.storageKey(
      "token",
      sessionId,
      session.tenantId,
      session.objectId,
      this.config.clientId,
      audience,
      scopes.join(" "),
    );
  }

  private sessionTtl(session: ConsoleSession): number {
    const now = this.now();
    return Math.max(
      0,
      Math.min(session.absoluteExpiresAt - now, this.config.sessionIdleSeconds),
    );
  }
}

export function canonicalScopes(scopes: string[]): string[] {
  return [...new Set(scopes)].sort();
}
