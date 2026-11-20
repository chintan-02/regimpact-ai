import type { EnabledAuthConfig } from "../lib/auth/config";
import type { RedisCommands } from "../lib/auth/store";

export const TENANT_ID = "00000000-0000-4000-8000-000000000001";
export const CONSOLE_CLIENT_ID = "00000000-0000-4000-8000-000000000002";
export const COMPANION_CLIENT_ID = "00000000-0000-4000-8000-000000000003";

export function testConfig(overrides: Partial<EnabledAuthConfig> = {}): EnabledAuthConfig {
  const key = Buffer.alloc(32, 7);
  return {
    enabled: true,
    environment: "test",
    baseUrl: new URL("http://localhost:3000/"),
    issuer: new URL(`http://127.0.0.1:9876/${TENANT_ID}/v2.0`),
    tenantId: TENANT_ID,
    clientId: CONSOLE_CLIENT_ID,
    companionClientId: COMPANION_CLIENT_ID,
    companionAudience: COMPANION_CLIENT_ID,
    companionScope: `api://${COMPANION_CLIENT_ID}/companion:access`,
    redirectUri: "http://localhost:3000/api/auth/entra/callback",
    postLogoutRedirectUri: "http://localhost:3000/login",
    redisUrl: "redis://127.0.0.1:6380/0",
    cookieSecure: false,
    sessionIdleSeconds: 1800,
    sessionAbsoluteSeconds: 28800,
    transactionTtlSeconds: 300,
    activeEncryptionKeyId: "test-v1",
    encryptionKeys: new Map([["test-v1", key]]),
    storageHmacKey: Buffer.alloc(32, 9),
    allowSyntheticAssertion: true,
    ...overrides,
  };
}

type Entry = { value: string; expiresAt: number | null };

export class FakeRedis implements RedisCommands {
  readonly values = new Map<string, Entry>();
  readonly sets = new Map<string, Set<string>>();
  available = true;

  constructor(private readonly now: () => number) {}

  async get(key: string): Promise<string | null> {
    this.check();
    return this.read(key);
  }

  async getDel(key: string): Promise<string | null> {
    this.check();
    const value = this.read(key);
    this.values.delete(key);
    return value;
  }

  async set(key: string, value: string, ttlSeconds: number, nx: boolean): Promise<boolean> {
    this.check();
    if (nx && this.read(key) !== null) return false;
    this.values.set(key, { value, expiresAt: this.now() + ttlSeconds });
    return true;
  }

  async del(keys: string[]): Promise<number> {
    this.check();
    let deleted = 0;
    for (const key of keys) {
      if (this.values.delete(key)) deleted += 1;
      if (this.sets.delete(key)) deleted += 1;
    }
    return deleted;
  }

  async sAdd(key: string, value: string): Promise<number> {
    this.check();
    const values = this.sets.get(key) ?? new Set<string>();
    const size = values.size;
    values.add(value);
    this.sets.set(key, values);
    return values.size === size ? 0 : 1;
  }

  async sMembers(key: string): Promise<string[]> {
    this.check();
    return [...(this.sets.get(key) ?? [])];
  }

  async expire(_key: string, _ttlSeconds: number): Promise<boolean> {
    this.check();
    void _key;
    void _ttlSeconds;
    return true;
  }

  async compareAndTouch(
    key: string,
    expectedValue: string,
    replacementValue: string,
    ttlSeconds: number,
  ): Promise<boolean> {
    this.check();
    if (this.read(key) !== expectedValue) return false;
    this.values.set(key, { value: replacementValue, expiresAt: this.now() + ttlSeconds });
    return true;
  }

  async purgeIndexed(sessionKey: string, indexKey: string): Promise<number> {
    this.check();
    return this.del([sessionKey, indexKey, ...(this.sets.get(indexKey) ?? [])]);
  }

  async close(): Promise<void> {}

  corruptFirstValue(): void {
    const entry = this.values.entries().next().value as [string, Entry] | undefined;
    if (entry) this.values.set(entry[0], { ...entry[1], value: `${entry[1].value}tampered` });
  }

  private read(key: string): string | null {
    const entry = this.values.get(key);
    if (!entry) return null;
    if (entry.expiresAt !== null && entry.expiresAt <= this.now()) {
      this.values.delete(key);
      return null;
    }
    return entry.value;
  }

  private check(): void {
    if (!this.available) throw new Error("Redis unavailable");
  }
}
