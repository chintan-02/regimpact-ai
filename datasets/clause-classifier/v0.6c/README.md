# v0.6C real corpus execution workspace

This directory defines the checked-in contracts for executing the v0.6 pipeline on genuine
regulatory documents. Raw source bytes, extracted text, annotations, adjudications, datasets and
model weights remain outside Git because they may contain redistribution-restricted material.

`source-approval-template.json` records the human rights review that binds each approved registry
entry to the exact downloaded artifact. `run-manifest-template.json` records the external storage
locations and immutable identifiers for the annotation, training and model-review evidence.

The milestone is complete only when all of the following are true:

1. At least 25 document/version groups from at least three regulators have approved reuse evidence.
2. The real-corpus command emits a hash-bound candidate queue and receipt.
3. Two independent humans annotate every admitted clause; a third human adjudicates disagreements.
4. The v0.6A audit admits at least 500 resolved examples and 30 examples per class.
5. The v0.6B baseline and encoder run on that audit-bound dataset.
6. A human reviews the test, calibration, slice and abstention reports before explicit promotion.

No empty template, synthetic fixture, candidate queue, notebook execution or unreviewed model may
be described as genuine model training completion.
