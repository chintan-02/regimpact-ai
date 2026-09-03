# Screenshot guide

This directory is reserved for sanitized RegImpact AI v0.5.0 portfolio captures. Do not add broken
image references to the root README before the corresponding files exist.

## Capture standard

- Source: the verified Azure staging release at commit
  `3b3d90ade4b75c845395a390b00cd3d0ba20d1d0`.
- Viewport: 1440 × 900 desktop unless a responsive view is being demonstrated.
- Format: optimized PNG or WebP; target less than 600 KB per image.
- Theme: use one consistent theme, browser zoom, and window size.
- Data: use synthetic demonstration records only.
- Redaction: remove credentials, tokens, tenant identifiers, personal data, subscription IDs,
  internal hostnames, and browser/account chrome.
- Framing: show the product state and a small amount of navigation context; avoid large empty areas.
- Accessibility: provide a specific alt description for every image.

## Planned assets

| Order | Filename | Purpose |
| --- | --- | --- |
| 01 | `01-operations-overview.png` | Deployment health, queues, and operational status |
| 02 | `02-source-registry.png` | Monitored source and immutable version history |
| 03 | `03-change-evidence.png` | Old-versus-new section comparison with citations |
| 04 | `04-obligation-review.png` | Evidence, confidence, and review routing |
| 05 | `05-control-mapping.png` | Ranked control candidates and ambiguity state |
| 06 | `06-reviewer-decision.png` | Human decision, rationale, and audit history |
| 07 | `07-azure-release-evidence.png` | Successful deployment workflow and retained artifact |

## README layout

After the assets exist, replace the walkthrough table in the root README with a two-column gallery:

```html
<table>
  <tr>
    <td width="50%">
      <img src="docs/screenshots/03-change-evidence.png"
           alt="RegImpact old-versus-new regulatory section comparison with source citations">
    </td>
    <td width="50%">
      <img src="docs/screenshots/05-control-mapping.png"
           alt="RegImpact ranked obligation-to-control mapping candidates with review state">
    </td>
  </tr>
</table>
```

Use no more than two screenshots per row. Follow each row with one short sentence explaining the
engineering or user outcome; do not repeat visible interface labels.
