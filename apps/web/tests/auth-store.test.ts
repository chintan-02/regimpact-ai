import { describe, expect, it } from "vitest";

import { RecordProtector } from "../lib/auth/crypto";
import { AuthStore, type ConsoleSession } from "../lib/auth/store";
import { FakeRedis, testConfig } from "./auth-helpers";

function session(now: number, csrfHash: string): ConsoleSession {
  return {
    createdAt: now,
    lastSeenAt: now,
    absoluteExpiresAt: now + 28800,
    tenantId: "00000000-0000-4000-8000-000000000001",
    objectId: "00000000-0000-4000-8000-000000000004",
    subject: "subject",
    csrfHash,
    idToken: "encrypted-id-token",
    refreshToken: "encrypted-refresh-token",
  };
}

describe("encrypted Redis authentication store", () => {
  it("atomically consumes a transaction once", async () => {
    let now = 1000;
    const redis = new FakeRedis(() => now);
    const store = new AuthStore(testConfig(), redis, undefined, () => now);
    await store.createTransaction("state-value", {
      nonce: "nonce",
      verifier: "verifier",
      returnTo: "/",
      createdAt: now,
      expiresAt: now + 300,
    });
    expect((await store.consumeTransaction("state-value")).nonce).toBe("nonce");
    await expect(store.consumeTransaction("state-value")).rejects.toThrow();
    now += 301;
  });

  it("enforces idle and absolute expiry and purges token records", async () => {
    let now = 1000;
    const config = testConfig({ sessionIdleSeconds: 30, sessionAbsoluteSeconds: 60 });
    const redis = new FakeRedis(() => now);
    const store = new AuthStore(config, redis, undefined, () => now);
    const csrf = "csrf-value";
    const record = { ...session(now, store.csrfFingerprint(csrf)), absoluteExpiresAt: now + 60 };
    await store.createSession("session-value", record);
    await store.cacheToken("session-value", record, {
      accessToken: "server-only-token",
      audience: config.companionAudience,
      scopes: [config.companionScope],
      expiresAt: now + 60,
    });
    expect(store.csrfMatches(await store.getSession("session-value"), csrf)).toBe(true);
    now += 31;
    await expect(store.getSession("session-value")).rejects.toThrow();
    await expect(
      store.getToken("session-value", record, config.companionAudience, [config.companionScope]),
    ).rejects.toThrow();
  });

  it("partitions cache keys by session user audience and canonical scopes", async () => {
    const now = 1000;
    const config = testConfig();
    const redis = new FakeRedis(() => now);
    const store = new AuthStore(config, redis, undefined, () => now);
    const record = session(now, store.csrfFingerprint("csrf"));
    await store.createSession("session-a", record);
    await store.cacheToken("session-a", record, {
      accessToken: "token-a",
      audience: config.companionAudience,
      scopes: [config.companionScope, "extra"],
      expiresAt: now + 600,
    });
    expect(
      (
        await store.getToken("session-a", record, config.companionAudience, [
          "extra",
          config.companionScope,
        ])
      ).accessToken,
    ).toBe("token-a");
    await expect(
      store.getToken("session-b", record, config.companionAudience, [
        config.companionScope,
        "extra",
      ]),
    ).rejects.toThrow();
  });

  it("rejects tampered ciphertext and missing rotation keys", async () => {
    const now = 1000;
    const config = testConfig();
    const redis = new FakeRedis(() => now);
    const store = new AuthStore(config, redis, undefined, () => now);
    await store.createSession("session", session(now, store.csrfFingerprint("csrf")));
    redis.corruptFirstValue();
    await expect(store.getSession("session")).rejects.toThrow();

    const protector = new RecordProtector(config);
    const key = protector.storageKey("record", "one");
    const encrypted = protector.encrypt({ value: true }, key, "record");
    const rotated = new RecordProtector(
      testConfig({ encryptionKeys: new Map([["other", Buffer.alloc(32, 1)]]) }),
    );
    expect(() => rotated.decrypt(encrypted, key, "record")).toThrow();
  });

  it("fails closed when Redis is unavailable", async () => {
    const now = 1000;
    const redis = new FakeRedis(() => now);
    const store = new AuthStore(testConfig(), redis, undefined, () => now);
    redis.available = false;
    await expect(store.getSession("session")).rejects.toThrow("Redis unavailable");
    await expect(
      store.createTransaction("state", {
        nonce: "nonce",
        verifier: "verifier",
        returnTo: "/",
        createdAt: now,
        expiresAt: now + 300,
      }),
    ).rejects.toThrow("Redis unavailable");
  });

  it("does not resurrect a session removed during an idle-time refresh", async () => {
    const now = 1000;
    const redis = new FakeRedis(() => now);
    const store = new AuthStore(testConfig(), redis, undefined, () => now);
    await store.createSession("session", session(now, store.csrfFingerprint("csrf")));
    const originalCompareAndTouch = redis.compareAndTouch.bind(redis);
    redis.compareAndTouch = async (key, expected, replacement, ttl) => {
      await redis.del([key]);
      return originalCompareAndTouch(key, expected, replacement, ttl);
    };

    await expect(store.getSession("session")).rejects.toThrow("Session unavailable");
    await expect(store.getSession("session")).rejects.toThrow("Session unavailable");
  });
});
