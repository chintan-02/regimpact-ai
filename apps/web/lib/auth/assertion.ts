import type { EnabledAuthConfig } from "./config";

export const CLIENT_ASSERTION_TYPE = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer";

export interface ConfidentialClientAssertionProvider {
  getAssertion(): Promise<string>;
}

export class UnavailableAssertionProvider implements ConfidentialClientAssertionProvider {
  async getAssertion(): Promise<string> {
    throw new Error("Confidential client proof is unavailable");
  }
}

export class SyntheticAssertionProvider implements ConfidentialClientAssertionProvider {
  constructor(
    config: EnabledAuthConfig,
    private readonly factory: () => Promise<string>,
  ) {
    if (config.environment !== "test" || !config.allowSyntheticAssertion) {
      throw new Error("Synthetic client assertions are test-only");
    }
  }

  async getAssertion(): Promise<string> {
    const assertion = await this.factory();
    if (!assertion || assertion.length > 16_384) throw new Error("Synthetic assertion unavailable");
    return assertion;
  }
}
