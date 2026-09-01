# Document ingestion security

## Implemented controls

- Accept only PDF and HTML.
- Verify content signatures instead of trusting filename or `Content-Type`.
- Require the extension, declared type and detected type to agree.
- Enforce byte limits before parsing and page limits before full PDF extraction.
- Reject encrypted, structurally invalid and textless PDFs.
- Remove active HTML elements before text extraction.
- Sanitize filenames and never use them as storage paths.
- Address immutable objects by SHA-256 within the organization namespace.
- Deduplicate ingestion jobs by organization, regulation and content hash.
- Preserve queued, processing, completed and failed states with audit events.
- Fail closed outside local development when malware scanning is unavailable.
- Require HTTPS, an exact hostname allowlist and public DNS results for monitored sources.
- Disable redirects and enforce byte limits while streaming conditional HTTP responses.

## Deliberately pending

- Production malware scanner adapter and quarantine container
- Azure Blob Storage adapter with managed identity
- Archive/bomb protection if ZIP-based formats are introduced
- OCR sandbox for image-only PDFs
- Worker time and memory limits
- Parser isolation for hostile documents
- Egress proxy or network policy that prevents DNS-rebinding bypasses at connect time
- Retention, legal hold and deletion policy

The current release must not be advertised as production-secure until the pending controls relevant to the deployment environment are implemented and verified.
