# Demo access and navigation

## Navigation model

The primary rail contains Changes, Obligations, Reviews, and Workflows. Controls, Sources, and
Ingestion are grouped under Manage. Operations remains admin-only. At narrower widths the same
destinations move into a keyboard-accessible menu without changing authorization behavior.

The account menu displays organization and role, provides sign-out, and exposes demo account
switching only when local demo mode is enabled. Switching first terminates the current session and
then returns to the login page; it never mutates a user's database role or impersonates another
identity inside an existing session.

## Demo authentication boundary

Set `REGIMPACT_DEMO_MODE=true` only for an isolated local demonstration. The role selector calls a
server-side endpoint that resolves deterministic seeded credentials, authenticates the real database
user, issues a normal short-lived JWT, and records the login in the audit trail. Passwords are never
returned to or embedded in browser code.

Demo mode is disabled by default. Production configuration validation rejects demo mode, and the
demo endpoint returns `404` when disabled. Production login therefore exposes only the normal
email/password flow.
