import { randomBytes } from "node:crypto";

import { createClient } from "redis";
import { describe, expect, it } from "vitest";

import { AuthStore, NodeRedisCommands } from "../lib/auth/store";
import { testConfig } from "./auth-helpers";

const redisUrl = process.env.REGIMPACT_TEST_CONSOLE_REDIS_URL;
const integration = redisUrl ? describe : describe.skip;

integration("dedicated Redis authentication store", () => {
  it("uses atomic single-use records, bounded TTL, encryption, and purge", async () => {
    if (!redisUrl) throw new Error("REGIMPACT_TEST_CONSOLE_REDIS_URL is required");
    const suffix = randomBytes(12).toString("base64url");
    const config = testConfig({ redisUrl, transactionTtlSeconds: 60 });
    const adapter = new NodeRedisCommands(redisUrl);
    const store = new AuthStore(config, adapter);
    const state = `state-${suffix}-value-that-is-long-enough`;
    const now = Math.floor(Date.now() / 1000);
    await store.createTransaction(state, {
      nonce: `nonce-${suffix}`,
      verifier: `verifier-${suffix}`,
      returnTo: "/",
      createdAt: now,
      expiresAt: now + 60,
    });
    const results = await Promise.allSettled([
      store.consumeTransaction(state),
      store.consumeTransaction(state),
    ]);
    expect(results.filter((result) => result.status === "fulfilled")).toHaveLength(1);

    const sessionId = `session-${suffix}-value-that-is-long-enough`;
    const csrf = `csrf-${suffix}-value-that-is-long-enough`;
    const session = {
      createdAt: now,
      lastSeenAt: now,
      absoluteExpiresAt: now + 600,
      tenantId: "00000000-0000-4000-8000-000000000001",
      objectId: "00000000-0000-4000-8000-000000000004",
      subject: `subject-${suffix}`,
      csrfHash: store.csrfFingerprint(csrf),
      idToken: `id-token-${suffix}`,
      refreshToken: `refresh-token-${suffix}`,
    };
    await store.createSession(sessionId, session);
    await store.cacheToken(sessionId, session, {
      accessToken: `access-token-${suffix}`,
      audience: config.companionAudience,
      scopes: [config.companionScope],
      expiresAt: now + 600,
    });

    const inspector = createClient({ url: redisUrl });
    await inspector.connect();
    try {
      const keys = await inspector.keys("ri-console:test:*");
      const matchingValues = (
        await Promise.all(
          keys.map(async (key) => ((await inspector.type(key)) === "string" ? inspector.get(key) : null)),
        )
      ).filter((value): value is string => value !== null);
      const serialized = matchingValues.join("\n");
      for (const sensitive of [sessionId, csrf, session.subject, session.idToken, session.refreshToken, `access-token-${suffix}`]) {
        expect(keys.join("\n")).not.toContain(sensitive);
        expect(serialized).not.toContain(sensitive);
      }
    } finally {
      await inspector.close();
    }

    expect((await store.getToken(sessionId, session, config.companionAudience, [config.companionScope])).accessToken).toBe(`access-token-${suffix}`);
    await store.purgeSession(sessionId);
    await expect(store.getSession(sessionId)).rejects.toThrow();
    await adapter.close();
  });
});
