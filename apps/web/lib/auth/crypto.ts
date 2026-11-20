import {
  createCipheriv,
  createDecipheriv,
  createHmac,
  randomBytes,
  timingSafeEqual,
} from "node:crypto";

import type { EnabledAuthConfig } from "./config";

type Envelope = {
  v: 1;
  kid: string;
  iv: string;
  tag: string;
  ciphertext: string;
};

export class ProtectedRecordError extends Error {
  constructor() {
    super("Protected record is unavailable");
    this.name = "ProtectedRecordError";
  }
}

export class RecordProtector {
  constructor(private readonly config: EnabledAuthConfig) {}

  storageKey(kind: string, ...parts: string[]): string {
    const material = [this.config.environment, kind, ...parts].join("\u0000");
    const digest = createHmac("sha256", this.config.storageHmacKey).update(material).digest("hex");
    return `ri-console:${this.config.environment}:${kind}:${digest}`;
  }

  fingerprint(value: string): string {
    return createHmac("sha256", this.config.storageHmacKey).update(value).digest("base64url");
  }

  equalFingerprint(value: string, expected: string): boolean {
    const actual = Buffer.from(this.fingerprint(value));
    const reference = Buffer.from(expected);
    return actual.length === reference.length && timingSafeEqual(actual, reference);
  }

  encrypt(record: unknown, storageKey: string, kind: string): string {
    const key = this.config.encryptionKeys.get(this.config.activeEncryptionKeyId);
    if (!key) throw new ProtectedRecordError();
    const iv = randomBytes(12);
    const cipher = createCipheriv("aes-256-gcm", key, iv);
    cipher.setAAD(this.aad(storageKey, kind));
    const plaintext = Buffer.from(JSON.stringify(record), "utf8");
    const ciphertext = Buffer.concat([cipher.update(plaintext), cipher.final()]);
    const envelope: Envelope = {
      v: 1,
      kid: this.config.activeEncryptionKeyId,
      iv: iv.toString("base64url"),
      tag: cipher.getAuthTag().toString("base64url"),
      ciphertext: ciphertext.toString("base64url"),
    };
    return JSON.stringify(envelope);
  }

  decrypt<T>(value: string, storageKey: string, kind: string): T {
    try {
      const envelope = JSON.parse(value) as Partial<Envelope>;
      if (
        envelope.v !== 1 ||
        typeof envelope.kid !== "string" ||
        typeof envelope.iv !== "string" ||
        typeof envelope.tag !== "string" ||
        typeof envelope.ciphertext !== "string"
      ) {
        throw new ProtectedRecordError();
      }
      const key = this.config.encryptionKeys.get(envelope.kid);
      if (!key) throw new ProtectedRecordError();
      const decipher = createDecipheriv("aes-256-gcm", key, Buffer.from(envelope.iv, "base64url"));
      decipher.setAAD(this.aad(storageKey, kind));
      decipher.setAuthTag(Buffer.from(envelope.tag, "base64url"));
      const plaintext = Buffer.concat([
        decipher.update(Buffer.from(envelope.ciphertext, "base64url")),
        decipher.final(),
      ]);
      return JSON.parse(plaintext.toString("utf8")) as T;
    } catch {
      throw new ProtectedRecordError();
    }
  }

  randomOpaqueIdentifier(): string {
    return randomBytes(32).toString("base64url");
  }

  private aad(storageKey: string, kind: string): Buffer {
    return Buffer.from(`${this.config.environment}\u0000${kind}\u0000${storageKey}`, "utf8");
  }
}
