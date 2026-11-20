import { UnavailableAssertionProvider } from "./assertion";
import { AuthConfigurationError, loadAuthConfig } from "./config";
import { ConsoleAuthService } from "./oidc";
import { AuthStore, NodeRedisCommands } from "./store";

let runtime: ConsoleAuthService | undefined;

export function getConsoleAuthService(): ConsoleAuthService {
  if (runtime) return runtime;
  const config = loadAuthConfig();
  if (!config.enabled) throw new AuthConfigurationError();
  const store = new AuthStore(config, new NodeRedisCommands(config.redisUrl));
  runtime = new ConsoleAuthService(config, store, new UnavailableAssertionProvider());
  return runtime;
}
