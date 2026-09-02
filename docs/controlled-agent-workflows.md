# Controlled agent workflows

## Safety contract

RegImpact AI v0.4 uses a bounded, tenant-scoped state machine. The system may collect evidence,
rank existing control candidates, and propose an impact assessment. It does not mutate controls,
publish findings, notify external parties, or execute recommended actions.

Every proposal records:

- the exact obligation, regulation version, section, page, source URI, content hash, and quote;
- a deterministic plan and versioned agent identifier;
- proposed control actions that explicitly require human approval;
- the result of each policy gate and a reproducible evaluation score;
- creator identity, idempotency key, timestamps, and append-only human decisions.

## State transitions

`awaiting_approval` is produced only when evidence, tenant, confidence, and control-candidate gates
pass. Failed required gates produce `blocked`. An administrator may record `approved`, `rejected`,
or `changes_requested`. A blocked run cannot be approved, and a high-risk run cannot be approved
by the same identity that created it.

## Authorization

Admins and analysts may create proposals. Viewers may inspect them. Only admins may record human
decisions. Tenant identity is derived from the validated access token and never from request data.

`automatic_execution_disabled` is a positive safeguard and must evaluate to `true`. This keeps the
policy score aligned with the safety meaning shown to reviewers.

## Non-goals

This milestone does not provide open-ended tool use, background autonomous execution, external
notifications, control mutation, or model-generated uncited regulatory conclusions.
