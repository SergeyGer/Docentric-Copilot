# ADR-0015 — Independent label adjudication and evidence-backed candidate filtering

| Field | Value |
| --- | --- |
| Status | Accepted |
| Date | 2026-11-05 |
| Deciders | Project maintainers |
| Related | [Gold labels](../GOLD_LABELS.md), [Evaluation](../EVALUATION.md), [ADR-0014](0014-gold-dataset-and-reference-benchmark.md), [ADR-0002](0002-llm-compiler-separation.md), [Architecture](../ARCHITECTURE.md) |

## Context

The v0.10 gold benchmark produced 32 cases and 288 runs. Recall was essentially saturated
(0.996–1.000) while precision was 0.18–0.23. The image family passed 0% semantically for every
provider. The audit that opened v0.11 (issues #24 and #25) made two points:

1. The labels were authored by one person. A deterministic rule pass checked mechanics, but not
   business correctness. A high recall combined with low precision is also a label-quality signal:
   extra bindings only count as false positives if the labels say they are extra.
2. The planner sent the whole normalized schema to the provider. A model could bind every plausible
   field, and no deterministic gate distinguished an evidence-backed binding from a schema-valid
   guess. Sending fewer, better candidates is a product decision, not only a benchmark tweak.

The 0% image result was investigated before being interpreted as a model capability: the required
image path existed, and the raw v0.10 runs bound it; the failures were forbidden-scope hits around
it. A label gap would have been dishonest to invent, and loosening the forbidden guards to make
models pass would have hidden a real precision problem.

## Decision

### Label adjudication (#24)

- Add `benchmarks/adjudicate_labels.py`, a deterministic second pass that re-derives required paths,
  alternatives, forbidden guards and blocks from each prompt plus schema evidence. It does not
  import the planner's candidate retrieval, so it is independent of the code path it checks.
- Publish `benchmarks/adjudication_report.json` with per-case and per-label provenance:
  `author`, `adjudicator`, `agreement`, notes, derived paths, forbidden comparison and block
  comparison. The report states that this is a **deterministic proxy**, not a second human.
- Upgrade `benchmarks/gold_cases.json` to schema `gold-cases/v2`, version `2.0.0`. Every case has
  `label_status` and provenance; every binding, forbidden path and block has provenance. A `gap`
  label would be excluded from semantic denominators; no current case is a gap.
- Fix genuine label errors by making the prompt state what the label already requires:
  `cc-nested-service-tasks` now asks for the line description, and `cc-nested-task-effort` now asks
  for a table. The alternative would have been to weaken a required block or path, which this ADR
  rejects.
- Keep AT-07 **partial** until a real second human annotator exists. The adjudicator improves the
  record but cannot be described as human double review.

### Semantic precision (#25)

- Add a deterministic pre-filter in the planner:
  `packages/planner/src/docentric_copilot/planner/candidates.py`.
  It decomposes the brief into typed requirements (entity, attribute, type, collection scope,
  condition, placement), retrieves only schema nodes that satisfy hard constraints (existence, type,
  namespace/party scope, collection, explicit exclusions), ranks them deterministically and bounds
  the list (24 total, 4 per requirement).
- Replace the full-schema prompt with a `<candidate_bindings>` table when evidence exists. The system
  prompt gains candidate-mode rules: bind only listed paths, do not add unrequested blocks, omit a
  `NO SUPPORTED BINDING` requirement, choose one `AMBIGUOUS` path, and keep the body non-empty.
- Re-validate every emitted binding after generation: existence is already enforced by the sanitizer;
  the planner now also checks type and collection scope against candidate evidence and records
  `needs_review` for a schema-valid but unsupported path. Ambiguous candidates and unsatisfiable
  requirements produce explicit review/abstention rows instead of a guessed path.
- Keep the pre-filter and post-validation deterministic and provider-agnostic. The LLM still chooses
  among candidates and writes the document; it does not create schema paths.

### Measurement (#24)

- Report `pass@k`, `abstention_rate`, `review_rate`, family-level semantic pass and an explicit
  `governance.at07_status`. Publish the image family as a separate scorecard.
- Re-run only the affected 12 cases × 3 providers × 2 repeats (72 runs) with a $4 cap and a $3
  warning; do not rerun the 288-run matrix. Keep the v0.10 full report as a historical artifact and
  publish the new subset report separately.

## Consequences

Positive:

- A second, independent code path checks the labels and leaves a machine-readable journal. Label
  errors are found before a live run instead of being inferred from a suspicious score.
- Precision improves by construction: the provider cannot bind a field that was not retrieved as
  evidence, and post-validation marks any path outside the candidate set for review.
- The planner now has an explicit abstention/review state. Ambiguity is a first-class outcome rather
  than a silent guess.
- The image-family question is answered with evidence: the label was expressible; the failure was
  scope pollution. The scorecard prevents the aggregate from hiding a family.
- The counters make planned, executed, skipped, succeeded, failed and excluded runs auditable.

Negative and open:

- The adjudicator is deterministic and was developed against this fixture set. It can share the
  author's blind spots and cannot establish business correctness. AT-07 remains partial.
- Candidate filtering can hurt recall if the decomposition misses a legitimate field. The v0.11
  offline check covers all 98 committed expected paths, but a new domain may need lexicon work; a
  missing candidate becomes an honest review row, not a silent binding.
- A model may still ignore candidate-mode instructions and bind an unlisted path. Post-validation
  exposes it; the IR is not silently rewritten to make the metric look better.
- The subset measurement is 72 runs, not a new 288-run ranking. It is a scoped before/after check on
  the changed families, not statistical evidence.
- Product image, image collection, optional image and absence/wrong-scope image cases are not yet in
  the dataset; only company logo is covered.
