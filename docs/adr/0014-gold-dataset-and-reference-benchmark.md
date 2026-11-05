# ADR-0014 — Gold dataset and reference benchmark

| Field | Value |
| --- | --- |
| Status | Accepted |
| Date | 2026-11-05 |
| Deciders | Project maintainers |
| Related | [Gold labels](../GOLD_LABELS.md), [Evaluation](../EVALUATION.md), [Benchmarks](../BENCHMARKS.md), [ADR-0012](0012-reference-diff-and-evaluation.md), [ADR-0006](0006-provider-gateway.md), [Docentric AX Compatibility](../DOCENTRIC_AX_COMPATIBILITY.md) |

## Context

v0.9 shipped a semantic evaluation with 20 synthetic cases and three repeats, but the case set was
too small and too easy to support a product-level claim. It had no holdout split, no versioned
dataset hash, no per-family breakdown and no adjudication record. The labels were also authored and
consumed in the same commit, which makes accidental overfitting invisible.

The v0.10 P0 specification (section 4) asks for at least 30 gold cases, a fixed
calibration/holdout split before the first experiment, at least three runs per case and model,
precision/recall/F1, requirement coverage, context accuracy, an error taxonomy, validation success
kept separate, and cost per correct result. It also asks for labels reviewed by at least two people
with an adjudication journal. The repository has one implementer and no second independent reviewer;
that constraint is a fact, not something to paper over.

A second constraint is legal and ethical: the Docentric example archive is vendor material. The
committed benchmark must use synthetic fixtures only. The benchmark is also not a Docentric runtime
test; `runtime_compatibility` stays `not_tested`.

## Decision

### Dataset

- Add `benchmarks/gold_cases.json` with **32 cases** in schema `gold-cases/v1`, dataset version
  `1.0.0`. The cases cover ten families (flat fields, images, collections, nested lists, conditions,
  missing, ambiguous, multilingual, long tables, forbidden scope) and the four specification
  categories (10 purchase order, 10 sales order, 6 conditional/complex, 6 adversarial).
- Every case declares `required_bindings` (concept, expected paths, allowed alternatives, required,
  optional type/context, satisfiability), `forbidden_paths`, `expected_blocks`, `family`,
  `category`, `difficulty`, `split`, `labels`, `language` and a short rationale.
- The dataset uses only committed synthetic fixtures under `examples/` and `benchmarks/fixtures/`.
  No Docentric corpus content, vendor template, raw trace or licensed artifact is committed.
- The canonical cases array is hashed with SHA-256 and the version, hash and file hash are recorded
  in every report. Labels cannot be changed without a new version and a new report.

### Split and adjudication

- The split is **20 calibration / 12 holdout**, fixed before the first live run, stratified by family
  and category. Both splits contain all ten families. Holdout cases must not be used to tune
  prompts, routing or decoding.
- Labels are authored by the implementer and validated by a deterministic rule pass in
  `benchmarks/gold_dataset.py`. The pass checks schema paths, types, contexts, forbidden scope, block
  kinds, family invariants, exact split sizes and that no case points at private corpus material.
- **No independent human double review was available.** The dataset is therefore an honest
  single-annotator artifact. The adjudication record in [Gold labels](../GOLD_LABELS.md) lists the
  contested calls and the reason for each. AT-07 is reported as **partial**, not passed.

### Scoring and runner

- Add `benchmarks/gold_evaluation.py`. It uses the existing pure scorer
  (`benchmarks/semantic_scoring.py`) at the concept level: precision/recall/F1, requirement coverage,
  type/context correctness and block coverage are computed from gold labels; deterministic
  validation and generic DOCX compilation produce `valid_template_rate` separately.
- An ambiguous concept can have several acceptable paths. When a plan produces more than one
  acceptable variant, the duplicates are marked used rather than charged as false positives. They
  are not extra true positives, and forbidden paths are never exempted.
- The runner supports the requested flags `--providers`, `--repeats`, `--split`, `--max-spend`,
  `--warn-spend` and `--allow-unpriced`, plus `--paid-repeats` for a budget-constrained fallback.
  Gemini uses compact v2 with two repair calls; the priced providers use the full IR contract and
  the product default of one repair call.
- Cost is three-valued: `verified` (usage + published price), `estimated` (unpriced model with a
  documented proxy) and `unavailable`. Gemini 3.6-flash is unpriced and is never reported as $0.00.
  The budget guard prints a running known + estimated spend, warns at `--warn-spend` and aborts
  before a call whose worst case could cross `--max-spend`.
- Per-run records go to the git-ignored `benchmarks/gold_runs.jsonl`, containing paths, statuses,
  usage and cost but no prompt text, credentials or raw provider output. Committed aggregates are
  `benchmarks/gold_report.json`, `.csv` and a self-contained `.html` with dataset hash, split, model
  versions, settings, sample sizes, calibration/holdout sections, per-family rows and the explicit
  "observations, not significance" note.

### Live run

<!-- LIVE_RESULTS -->

## Consequences

Positive:

- The semantic benchmark is now large enough to compare task families and to report a holdout
  separately from calibration. The hash and version make every number attributable.
- The label contract is explicit and mechanically checked. Typos, stale paths, wrong collection
  scopes and split drift fail the rule pass before a paid run starts.
- Semantic correctness and technical validity stay separate, so a model cannot hide a wrong binding
  behind a 100% compilation rate.
- The benchmark is reproducible without committing private artifacts: the fixtures are synthetic,
  the dataset is committed, the runner is deterministic in its scoring, and the raw per-run file is
  ignored.

Negative and open:

- **No independent human double review.** This is the main limitation. The rule pass validates
  mechanics, not business judgement. A second reviewer could disagree with the ambiguity,
  forbidden-scope or long-table decisions; until then AT-07 is partial.
- The dataset is small and synthetic. Twelve holdout cases cannot support a confidence interval or a
  generalisation claim, and the fixtures are the project's own construction.
- Three repeats are repeated observations of the same prompt, not independent samples. Provider
  model drift makes old reports historical, not current.
- Path-level precision is strict: extra bindings are false positives even when harmless. The
  benchmark measures adherence to the request, not document aesthetics.
- The live run costs real money. The budget guard bounds the worst case but cannot make a provider
  price stable; reports must keep the pricing version and the cost status.
- Runtime compatibility remains `not_tested`. A high semantic score is not evidence that a template
  executes in Docentric AX.

## Alternatives considered

- **Keep the 20-case semantic set and add more repeats.** Rejected: more repeats do not fix missing
  families, no holdout and no versioned labels. The specification's minimum is 30 cases.
- **Wait for two independent reviewers before publishing.** Rejected for this increment: no second
  reviewer is available, and withholding the dataset would also withhold the evidence. The honest
  choice is to publish the single-annotator limitation and keep the gate partial.
- **Add Docentric corpus cases to increase realism.** Rejected: the archive is vendor material and
  cannot be committed. Local corpus mode remains a separate, ignored diagnostic.
- **Score only `valid_template_rate`.** Rejected: a template can compile while binding the company
  VAT number for the customer. That is exactly the failure the semantic metrics exist to expose.
- **Fold cost into the quality score and declare one winner.** Rejected: cost status and quality are
  different axes, and the sample is too small for a single ranking. The report shows per-metric
  leaders and ties instead.
- **Keep three repeats for every provider regardless of budget.** Rejected as a rule: the runner
  documents `--paid-repeats` so a budget-constrained run can use two repeats for priced providers
  while Gemini keeps three, rather than silently truncating the matrix.

## Follow-up

1. Find an independent reviewer for the 12 holdout cases and record genuine adjudications; then
   AT-07 can move from partial to passed.
2. Re-run the gold benchmark when a provider changes its model id or price, and keep the old report
   with its dataset/pricing hash.
3. Use calibration cases only for routing or prompt changes; treat any holdout-tuning use as a
   disclosure event and move the case to calibration.
4. Extend the holdout only in a new major dataset version, never by relabelling existing cases.
5. Keep the benchmark separate from Docentric AX compatibility. The runtime gate remains blocked
   until licensed evidence exists.
