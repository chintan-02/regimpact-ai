type AuthEvent =
  | "entra_login_started"
  | "entra_callback_succeeded"
  | "entra_callback_denied"
  | "entra_session_revoked"
  | "entra_dependency_unavailable";

export function logAuthEvent(event: AuthEvent): void {
  process.stdout.write(
    `${JSON.stringify({
      timestamp: new Date().toISOString(),
      level: event.endsWith("denied") || event.endsWith("unavailable") ? "warning" : "info",
      logger: "regimpact.console.auth",
      event,
      message: event,
    })}\n`,
  );
}
