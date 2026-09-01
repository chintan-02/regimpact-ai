# ADR 0001: Product and visual direction

Status: accepted

## Decision

RegImpact will use a regulatory operations-desk interface rather than the dark-sidebar dashboard composition used by TriageAI and PolicyGPT.

The interface uses:

- a narrow horizontal command rail instead of a full-height navy sidebar;
- warm mineral surfaces rather than a cool gray application canvas;
- graphite text, cobalt actions and amber change/risk semantics;
- dense change registers and document timelines instead of oversized KPI-card rows;
- a three-pane investigation workbench for source diff, obligation analysis and evidence;
- restrained 6–10 px radii, fine rules and tabular data styling;
- Source Serif 4 for high-level editorial headings and Inter for operational UI text.

## Rejected pattern

We will not reproduce the combination of dark navy navigation, white rounded cards, teal status chips, large dashboard counters and generic overview grids visible in the two earlier projects.

## Accessibility

Colour will never be the only carrier of change type or review status. Focus states, keyboard navigation, minimum contrast and reduced-motion support are release requirements.
