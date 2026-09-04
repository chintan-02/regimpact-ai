# v0.6C-2 corpus rights-review runbook

## Purpose and boundary

This workflow records a human decision about whether each acquired regulatory artifact may enter
the RegImpact annotation pipeline. It is an engineering control and evidence trail, not legal
advice. The software prepares and validates evidence but never decides that reuse is permitted.

The 25 artifacts are exact English XML files from the Justice Canada Laws XML repository at commit
`a782c13dbf0c710f33d8b2adc3e42377c94d0626`. The acquisition lock records each file's SHA-256 and
byte size. Raw XML remains outside Git.

## Authoritative review material

The reviewer must open and assess all four sources rather than relying on this summary:

1. [Open Government Licence – Canada](https://open.canada.ca/en/open-government-licence-canada)
2. [Reproduction of Federal Law Order](https://laws-lois.justice.gc.ca/eng/regulations/si-97-5/)
3. [Justice Laws Website frequently asked questions](https://laws-lois.justice.gc.ca/eng/faq/)
4. [Pinned Justice Canada repository licence](https://github.com/justicecanada/laws-lois-xml/blob/a782c13dbf0c710f33d8b2adc3e42377c94d0626/LICENSE.md)

The reviewer must also follow each record's official-law link and regulator portfolio link. That
confirms both document identity and the reason the document belongs in the selected regulatory
portfolio.

## Required human decision

Open `datasets/clause-classifier/v0.6c/rights-review-packet.json`. For every record:

1. Confirm the artifact refers to the expected official consolidated law.
2. Review whether the licence and reproduction order cover the intended annotation and model-
   development use.
3. Confirm the attribution plan.
4. Confirm downstream documentation will distinguish reproduced content from an official version.
5. Confirm accuracy checks and disclaimers will be retained.
6. Confirm the regulator portfolio assignment.
7. Set `decision` to `approved` or `rejected`.
8. Enter the reviewer's real name, an ISO 8601 timestamp with UTC offset, and a source-specific
   rationale of at least 20 characters.
9. Set each check to `true` only after personally completing it.

Do not use a script to bulk-approve the packet. If one source is rejected, revise the corpus through
a reviewed manifest change instead of deleting the record from the review packet.

## Validate work in progress

```bash
cd apps/api
python scripts/review_corpus_rights.py validate \
  --manifest ../../datasets/clause-classifier/v0.6c/corpus-manifest.json \
  --lock ../../datasets/clause-classifier/v0.6c/acquisition-lock.json \
  --review ../../datasets/clause-classifier/v0.6c/rights-review-packet.json
```

Validation confirms coverage and immutable evidence even while decisions remain pending. It does
not turn pending decisions into approvals.

CI adds `--require-pending` when it validates the checked-in packet. Do not add that flag when
validating a private, completed review file.

## Finalize after human approval

Keep finalized evidence outside Git if it includes reviewer information that should not be public.

```bash
export REGIMPACT_CORPUS_ROOT="$HOME/regimpact-corpus-v0.6"

cd apps/api
python scripts/review_corpus_rights.py finalize \
  --manifest ../../datasets/clause-classifier/v0.6c/corpus-manifest.json \
  --lock ../../datasets/clause-classifier/v0.6c/acquisition-lock.json \
  --review "$REGIMPACT_CORPUS_ROOT/rights-review.json" \
  --registry "$REGIMPACT_CORPUS_ROOT/approved-source-registry.json" \
  --approvals "$REGIMPACT_CORPUS_ROOT/source-approvals.json" \
  --receipt "$REGIMPACT_CORPUS_ROOT/rights-review-receipt.json"
```

Finalization succeeds only when all 25 sources are explicitly approved. It emits:

- an approved source registry compatible with the clause-annotation pipeline;
- source approvals compatible with real-corpus artifact verification; and
- a hash-bound review receipt authorizing annotation, but not model training.

## Acceptance criteria

- Review packet covers exactly the 25 manifest and lock entries.
- No evidence identity, URL, SHA-256 or size differs from acquisition evidence.
- Every completed record has a named human, aware timestamp, substantive rationale and six checks.
- All 25 decisions are approved before annotation admission.
- The final receipt keeps `model_training_authorized` set to `false`.
