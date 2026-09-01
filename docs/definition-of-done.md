# Definition of done

A feature is not complete because it appears in the UI. It is complete only when:

- domain rules and failure states are explicit;
- organization isolation and authorization implications are reviewed;
- API contracts are typed and versioned;
- database changes have reversible migrations;
- idempotency and retry behaviour are defined for background work;
- unit and relevant integration tests pass;
- structured logs, metrics and traces expose the operation;
- evidence lineage and audit events are preserved;
- keyboard access, focus, contrast, empty, loading and error states are verified;
- documentation and a reproducible demo fixture are updated;
- no capability is claimed publicly before it is verified.

## Visual differentiation gate

Every new RegImpact screen must be rejected during review if it falls back to the existing portfolio pattern of a navy full-height sidebar, pale-gray dashboard canvas, a row of large rounded KPI cards, teal operational pills, or generic card-grid composition.
