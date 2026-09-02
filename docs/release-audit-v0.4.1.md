# v0.4.1 alpha release audit

Scope: grouped and responsive navigation, an account menu, professional login presentation, a
development-only selector for real seeded RBAC identities, and a clear master-detail interaction
for the change register.

Dashboard change rows now select their matching preview in place through a refresh-safe URL. The
active row carries an explicit selection marker and light-blue treatment; the right-hand card shows
that row's evidence summary, while `Open investigation` remains the only route to the full detail
view. The Manage navigation trigger is vertically aligned with the other primary navigation items.

Security controls include disabled-by-default demo access, production startup rejection, a hidden
demo endpoint outside local mode, server-side credentials, fresh JWT issuance, explicit session
termination during switching, and login audit events.

Acceptance requires the complete Python suite, Ruff, MyPy, frontend lint, TypeScript validation,
the Next.js production build, archive integrity validation, and a live Docker review of admin,
analyst, viewer, desktop, narrow-screen navigation, and each dashboard change selection.
