# Evaluation

| Field | Value |
| --- | --- |
| Purpose | Measure planner quality and cost on a fixed, reproducible case set |
| Harness | [metrics.py](../packages/evaluation/src/docentric_copilot/evaluation/metrics.py), [reporting.py](../packages/evaluation/src/docentric_copilot/evaluation/reporting.py), [run_evaluation.py](../benchmarks/run_evaluation.py), [live_evaluation.py](../benchmarks/live_evaluation.py) |
| Cases | [benchmarks/evaluation_cases.json](../benchmarks/evaluation_cases.json) (3 synthetic fixtures), [benchmarks/live_cases.json](../benchmarks/live_cases.json) (12 live cases) |
| Default provider | `mock` (deterministic baseline, no credentials) |
| Related | [BENCHMARKS](BENCHMARKS.md), [PRICING](PRICING.md), [ROUTING](ROUTING.md), [SRS](SRS.md), [DDSP_COMPATIBILITY](DDSP_COMPATIBILITY.md) |

This document defines the metrics, describes the harness as implemented, and separates what has been
measured from what is still open. It contains **no** invented numbers: every value comes from a
committed run of the harness, quoted with its command and caveats.

## 1. What the evaluation is (and is not)

It **is** a small, reproducible comparison of planners on fixed synthetic fixtures with a hand-written
ground truth. It answers: "does the planner bind the fields a human would expect, does the template
compile, and what did generation cost?"

It is **not**:

- a statistically significant benchmark (3 cases, one run, one machine);
- a measure of document quality, visual fidelity or business correctness;
- evidence of Docentric AX compatibility (that metric is 0 while the gate is blocked);
- a substitute for customer acceptance testing.

## 2. Harness as implemented

### 2.1 Data model

`EvaluationCase` fields (all persisted in `benchmarks/evaluation.json`):

| Field | Meaning |
| --- | --- |
| `case_id` | Fixture identifier (`quotation`, `invoice`, `purchase-order`) |
| `schema_id` | Normalized schema identifier |
| `prompt` | Requirement text used for the plan |
| `expected_paths` | Ground-truth absolute schema paths a correct plan should bind (≤ 200) |
| `actual_paths` | Absolute paths actually bound by the produced IR (≤ 200) |
| `requirements` | Number of requirement clauses in the mapping report |
| `covered_requirements` | Clauses with status `resolved` |
| `compiled` | True when V1–V3 pass **and** the generic compiler succeeds |
| `clarifications` | Clauses with status `ambiguous` |
| `corrections` | 1 when bindings were removed or any mapping is `invalid`, else 0 |
| `verified_compatible` | Always `false` in this build (gate blocked) |
| `cost_usd` | Provider `estimated_cost_usd` for the plan (0 for mock) |

`evaluate(cases, provider=..., model=...)` returns a `MetricsReport` containing the cases and a
`dict[str, MetricValue]`. Each `MetricValue` carries `name`, `value`, `numerator`, `denominator` and a
human-readable `definition`; `value` is `None` when the denominator is zero (displayed as `n/a`).
`MetricsReport.summary()` returns display strings.

### 2.2 Flow

```text
for each definition in benchmarks/evaluation_cases.json:
    parse the DDSP package
    plan with the selected provider (default mock)
    validate the IR (with sample data)
    if V1–V3 pass: compile a generic DOCX (success recorded)
    ground truth: expected_paths from the case file
    actual: absolute paths of every field/image binding in the IR
    metrics: evaluate(cases)
write benchmarks/evaluation.json
```

Run it:

```bash
make eval
# or
python benchmarks/run_evaluation.py
python benchmarks/run_evaluation.py --provider openai --model gpt-4o-mini
python benchmarks/run_evaluation.py --cases path/to/cases.json --output path/to/out.json
```

Without credentials the hosted-provider invocation fails with a provider error; it is never silently
replaced by the mock.

### 2.3 Live multi-provider harness (VID-02)

| Item | Value |
| --- | --- |
| Runner | [benchmarks/live_evaluation.py](../benchmarks/live_evaluation.py) |
| Cases | [benchmarks/live_cases.json](../benchmarks/live_cases.json) (12 cases) |
| Reports | `benchmarks/live_report.json` and `benchmarks/live_report.md` |
| Traces | `docs/media/runs/` (git-ignored; sanitized, no prompt text) |
| Providers | `--providers openai:gpt-6-sol,anthropic:claude-sonnet-5-5,gemini:gemini-3.1-flash-lite` |
| Compact IR | `--compact-ir auto|on|off` (default `auto`: Gemini uses the compact wire format) |
| Budget | `--max-spend-usd` (default 3.0); pre-flight worst-case guard, abort with a partial report |

The dataset covers the six requested families: simple fields, repeats, conditionals, ambiguous
binding, missing field and multi-line items. Each case is planned **once** per provider with the
identical prompt and schema; `max_repair_attempts` is 0 and transport retries are disabled, so a
failure is recorded rather than retried.

```bash
.venv/bin/python benchmarks/live_evaluation.py \
  --providers openai:gpt-6-sol,anthropic:claude-sonnet-5-5,gemini:gemini-3.1-flash-lite \
  --limit 4 --max-spend-usd 2.5
```

The harness measures field precision/recall against `expected_paths`, requirement coverage from the
mapping report, validation pass, compilation success, latency p50/p95, tokens and cost. An unknown
price is reported as `N/A`; if any run is unpriced the aggregate cost is `N/A` and the known subtotal
is kept separately. The report metadata records `pricing_version`, `pricing_as_of` and
`pricing_source` from [PRICING](PRICING.md).

The recommendation function is
`docentric_copilot.evaluation.reporting.recommend_provider`: **quality first** (weighted precision
0.4, recall 0.4, coverage 0.2, multiplied by the validation pass rate), **then known cost**, **then
p50 latency**. An unpriced provider sorts after every priced provider on the budget criterion; a
provider with no validating plan scores 0 and is never recommended. The policy is lexicographic and
deterministic, not learned.

### 2.4 Known measurement limitations

These are properties of the current harness, not of the product. They must be fixed before recall
numbers are used for decisions.

1. **Alias bindings are resolved through the planner's scope walker.** The collector uses
   `docentric_copilot.planner.service.absolute_bindings`, which walks the IR with the alias scope in
   force, so `line.ItemId` inside a table repeat is counted as its absolute schema path. Earlier
   drafts used a root-scope collector and understated recall; the numbers in §4 are post-fix.
2. **Ground truth includes collection paths** (e.g. `MainData.QuotationLines.Line`) and condition-only
   fields (e.g. `Customer.IsEU`). The IR uses collection paths in `repeat`/`table.repeat` rather than as
   scalar bindings, and condition fields are not "bindings", so a correct plan can still miss them.
3. **Ground truth is authored by the project** for synthetic fixtures. It reflects this team's notion
   of a correct plan, not a customer's.
4. **Single run, three cases.** No repetitions, confidence intervals or variance analysis.
5. **`corrections` is a 0/1 flag per case**, not a count of edits; `correction_rate` is therefore
   "share of plans needing at least one correction", not edits per plan.
6. **Cost is an estimate** from a static price table; unknown models report 0 while the price is
   unknown, so cost-per-template is understated for unpriced models.
7. **`verified_compatibility_rate` is structurally 0** until a licensed Docentric environment is used;
   it measures the gate, not the planner.

Improving items 1–2 changes the metric values and must be accompanied by a re-generated baseline and a
note in this document.

## 3. Metric definitions

Let `TP = |expected ∩ actual|` summed over cases, `S = |actual|` summed, `E = |expected|` summed,
`R` = total requirement clauses, `C` = number of cases.

| Metric | Formula (implementation) | Interpretation | Desired direction |
| --- | --- | --- | --- |
| Field selection precision | `TP / S`; `None` if `S = 0` | Of the fields the planner bound, how many were expected? | Higher (1.0 ideal) |
| Field selection recall | `TP / E`; `None` if `E = 0` | Of the expected fields, how many did the planner bind? | Higher (1.0 ideal) |
| Requirement coverage | `Σ covered_requirements / Σ requirements` | Share of requirement clauses resolved in the mapping report | Higher |
| Compilation success rate | `count(compiled) / C` | Share of plans that pass V1–V3 and compile | Higher (1.0 ideal) |
| Clarification rate | `Σ clarifications / Σ requirements` | Ambiguous clauses per requirement: how often the system asks a human | Lower is not automatically better: an ambiguous status is the honest outcome when evidence is weak |
| Correction rate | `count(corrections) / C` | Share of plans where the deterministic repair removed something or a mapping was invalid | Lower |
| Verified compatibility rate | `count(verified_compatible) / C` | Share of templates **proven** to execute in Docentric AX | 0 until the gate passes; never inferred from compilation |
| Cost per valid template (USD) | `Σ cost_usd / max(1, count(compiled))` | Estimated provider spend per successfully compiled template | Lower |

Precision and recall deliberately use field *paths*, not values. Requirement coverage is a coarser
signal derived from the mapping report, and the two can disagree (for example, a clause can be marked
resolved because the document title satisfies it).

`field_selection_precision`, `field_selection_recall`, `requirement_coverage`,
`compilation_success_rate`, `clarification_rate`, `correction_rate`, `verified_compatibility_rate` and
`cost_per_valid_template_usd` are the exact metric keys emitted by the harness.

The live harness reuses these field definitions and adds:

| Metric | Formula (implementation) | Notes |
| --- | --- | --- |
| Validation pass rate | `count(validation_passed) / successful_runs` | `ValidationReport.can_compile` on the produced IR |
| Latency p50 / p95 | Linear-interpolated percentile over successful runs (`reporting.percentile`) | One sample per case/provider; not a load test |
| Token totals | Sum of `prompt_tokens` + `completion_tokens` returned by each provider | Provider-reported |
| Cost aggregate | `aggregate_cost`: sum of known `estimated_cost_usd`; `None` if any run is unpriced | `N/A`, never `$0.00`, for unpriced models |
| Quality score | `0.4×precision + 0.4×recall + 0.2×coverage`, multiplied by validation pass rate | `0.0` when nothing validates |
| Recommendation | Lexicographic `(-quality, cost or ∞, p50)` | `recommend_provider`; unpriced loses the budget tie |

Cases with an empty expected set (the `missing-field` case) have an undefined precision/recall
denominator and are excluded from those aggregates; requirement coverage still records whether the
planner admitted the requirement was missing.

## 4. Mock baseline vs LLM comparison

The mock provider is a deterministic, explainable heuristic (`heuristic-baseline-v1`). It exists so
that:

- the pipeline and evaluation can run without credentials and reproducibly;
- an LLM has a control to beat: a model that does not improve on a rule-based mapping has no product
  value;
- regressions in the deterministic path are visible.

Comparison protocol:

1. Run `make eval` (mock) and record the machine, Python version, commit and output file.
2. Run the same cases with a hosted provider and a fixed model:
   `python benchmarks/run_evaluation.py --provider openai --model <model>`.
3. Record provider, model, `attempts`, token usage and estimated cost from the generated IR's
   `generation` metadata (or the evaluation JSON).
4. Compare per-case and aggregate metrics; investigate every case where the LLM is worse, not only
   the average.
5. Repeat the LLM run at least 3 times (temperature is 0 by default, but providers may still vary) and
   report variance. The harness currently performs one run per invocation; repetition is manual.

Do not compare an LLM run on one case set with a mock run on another. Do not average away
`verified_compatibility_rate`: it is 0 for both until the gate passes.

## 5. Results

### 5.1 Committed baseline run (measured)

Source: [benchmarks/evaluation.json](../benchmarks/evaluation.json), generated by
`benchmarks/run_evaluation.py` with the default `mock` provider. These values are reproducible by
running `make eval` on the same fixtures, although exact timings are not part of this file.

| Metric | Value | Numerator / denominator |
| --- | --- | --- |
| Field selection precision | 0.932 | 55 / 59 |
| Field selection recall | 0.965 | 55 / 57 |
| Requirement coverage | 1.000 | 27 / 27 |
| Compilation success rate | 1.000 | 3 / 3 |
| Clarification rate | 0.000 | 0 / 27 |
| Correction rate | 0.000 | 0 / 3 |
| Verified compatibility rate | 0.000 | 0 / 3 |
| Cost per valid template (USD) | 0.000 | 0.0 / 3 |

Interpretation with the limitations in §2.4:

- **Precision 0.932** means almost every path the baseline bound was in the ground truth; the extra
  bindings are legitimate fields (for example bank `Swift` and payment terms) that the ground-truth
  list does not require.
- **Recall 0.965** is measured after the collector was switched to the scope-aware walker (§2.4), so
  table and nested-repeat bindings are counted. The remaining misses are condition-only fields
  (`Customer.IsEU`, `ReverseCharge`), which are used in expressions rather than as scalar bindings.
- **Requirement coverage 1.0** means every extracted clause got a `resolved` mapping. The mapping
  report is lenient in two documented ways: a clause matched by the document title is `resolved`, and a
  clause whose best field is bound is `resolved` even if other clauses reuse the same field.
- **Clarification 0.0** means the baseline never returned `ambiguous` on these fixtures. On a small,
  well-named synthetic schema that is expected; it is not evidence that the baseline recognises
  ambiguity in general.
- **Compilation 1.0** means the three fixtures compile. Golden and integration tests assert the same.
- **Compatibility 0.0** is the gate, not a failure of the compiler. No compatibility is claimed.

### 5.2 Hosted-provider comparison (superseded by the gold benchmark)

The three-case field-selection table was never run against hosted providers; only the mock row was
measured. That comparison is superseded by the 32-case gold benchmark in
[§2.7](#27-gold-semantic-benchmark-v010-pr-05), which reports precision, recall, F1, requirement
coverage, type/context correctness, block coverage, a separate valid-template rate, cost and the
error taxonomy for OpenAI, Anthropic and Gemini, with calibration and holdout shown separately.

| Provider | Evidence |
| --- | --- |
| mock (3-case baseline) | `benchmarks/evaluation.json`; precision 0.932, recall 0.965, coverage 1.000, compilation 1.000 |
| OpenAI `gpt-6-sol` | [gold_report.json](../benchmarks/gold_report.json), §2.7 |
| Anthropic `claude-sonnet-5-5` | [gold_report.json](../benchmarks/gold_report.json), §2.7 |
| Gemini `gemini-3.6-flash` | [gold_report.json](../benchmarks/gold_report.json), §2.7; cost estimated with the documented proxy |

The old three-case harness remains useful as a deterministic smoke test and as the mock control. It
is not a hosted-provider comparison, and its `TBD` rows were removed rather than left as stale text.

## 6. Reproducibility checklist

For every result published in this file or in a PR:

1. Command executed verbatim.
2. Provider and exact model identifier; whether an API key was configured.
3. Commit hash and Python version.
4. Cases file version (the JSON is part of the repository).
5. Raw output file path (`benchmarks/evaluation.json` or an alternative).
6. Number of repetitions and how variance was handled.
7. Known limitations that apply (§2.4) and whether any were fixed for this run.

Results without these are anecdotes and must not be presented as metrics.

## 7. Threats to validity

| Threat | Effect | Mitigation |
| --- | --- | --- |
| Tiny, synthetic case set | Overstates generalisation | Add permitted real fixtures; report per-case results |
| Ground truth authored by the same team | Confirmation bias | Independent review of `expected_paths`; publish the cases |
| Alias/collection accounting (§2.4) | Recall understated | **Resolved**: scope-aware collector; re-baselined in the 0.2.0 tree |
| Single run, temperature 0 | Cannot show variance | Repeat runs; report range |
| Cost table drift | Cost metric wrong | Record actual provider billing when available; mark unpriced models |
| Compiled ≠ correct | Compilation metric is necessary, not sufficient | Pair with precision/recall and human review |
| Compatibility metric is untested | 0 is not a quality signal | Treat as gate status; see [DOCENTRIC_AX_COMPATIBILITY](DOCENTRIC_AX_COMPATIBILITY.md) |
| Provider changes over time | Non-reproducible LLM results | Record model id/date; re-run when provider updates |

## 8. Adding cases

1. Add a definition to `benchmarks/evaluation_cases.json`: `case_id`, `package`, `prompt_file`,
   `expected_paths` (absolute, alias-free scalar paths where possible).
2. Keep the package synthetic and regenerate it deterministically (`python scripts/build_examples.py`).
3. Run `make eval` and review both the metrics and the per-case JSON.
4. If the expected paths include collection or condition fields, either fix the collector first or
   document why recall will be affected.
5. Never edit an expected path merely to raise a metric; every change to ground truth is a product
   decision and must be reviewable in the diff.

For a live case in `benchmarks/live_cases.json`, also record `category` (`simple`, `repeat`,
`conditional`, `ambiguous`, `missing`, `multiline`) and a `notes` field explaining the ground truth.
The `ambiguous-address` case intentionally puts both defensible paths in `expected_paths`, so a
single-address plan scores recall 0.5; the `missing-field` case has an empty expected set because no
correct binding exists, so it is excluded from precision/recall and judged by requirement coverage.

## 2.5 Semantic quality evaluation (P0)

The live harness above answers "did the provider produce a valid template?".
The semantic harness answers a different question: **did it bind the right
things?** A payload can pass V1–V3 and compile while binding the company VAT
number for a customer VAT requirement. That is a semantic failure and must be
visible even when `valid_template_rate` is 1.0.

| Item | Value |
| --- | --- |
| Runner | [benchmarks/semantic_evaluation.py](../benchmarks/semantic_evaluation.py) |
| Scoring | [benchmarks/semantic_scoring.py](../benchmarks/semantic_scoring.py) (pure functions) |
| Dataset | [benchmarks/semantic_cases.json](../benchmarks/semantic_cases.json) (20 cases) |
| Runs | `benchmarks/semantic_runs.jsonl` (one JSON object per run, no credentials or raw output) |
| Reports | [semantic_report.json](../benchmarks/semantic_report.json), `.csv`, [semantic_report.html](../benchmarks/semantic_report.html) |
| Providers | `openai:gpt-6-sol`, `anthropic:claude-sonnet-5-5`, `gemini:gemini-3.6-flash` |
| Wire format | Gemini compact **v2**; other providers full IR; `max_repair_attempts=2` |
| Repeats | 3 per case × provider (180 runs) |

The 32-case gold benchmark in [§2.7](#27-gold-semantic-benchmark-v010-pr-05) is the larger,
versioned successor. This 20-case set remains a compact regression harness and is not the source of
the PR-05 product metrics.

### Ground truth

Each case declares `required_bindings`:

| Field | Meaning |
| --- | --- |
| `id`, `concept` | Semantic identity, independent of the planner's own clause ids |
| `expected_paths` | Absolute schema paths a correct plan may bind |
| `allowed_alternatives` | Additional domain-acceptable paths (counted as a true positive) |
| `required` | False means a miss lowers coverage but not recall |
| `expected_type`, `expected_context` | Optional type/placement checks (`body`, `header`, `footer`, `repeat`, `conditional`) |
| `satisfiable` | False marks a request the schema cannot express; excluded from recall/coverage, and a hallucinated binding is charged as `wrong_binding` |

`forbidden_paths` are deliberate scope guards (for example the company VAT
number when the customer VAT number was requested, or bank details in a
"customer name only" case). `expected_blocks` covers repeats/tables,
conditionals and images.

The dataset covers flat fields, images, collections, nested lists, conditions,
missing and ambiguous requirements, multilingual briefs, footer placement and
forbidden fields. Case families and language counts are in the generated report
metadata.

### Metrics

Let `TP` be matched requirements, `FP` produced bindings that no requirement
accepts (including forbidden paths), `FN` required requirements that remain
unmatched, `R` required satisfiable requirements, `S` satisfiable requirements.

| Metric | Definition |
| --- | --- |
| `precision` | `TP / (TP + FP)`; extra or forbidden bindings reduce it |
| `recall` | matched required / `R` |
| `requirement_coverage` | matched satisfiable / `S` (optional requirements count in the denominator) |
| `type_context_correctness` | correct type/context checks / performed checks; an object or collection used as a scalar is an error |
| `block_coverage` | satisfied `expected_blocks` / declared expected blocks |
| `semantic_pass_rate` | runs where every required requirement and block is satisfied, no forbidden path is hit, and no type/context error is recorded |
| `valid_template_rate` | deterministic V1–V3 + compilation success; **reported separately** |

A missing table where the brief asked for a table is a block failure, not a
precision accident: the score records `wrong_context` and the block remains
unsatisfied. A condition field used by an expression is `role="condition"`; it
can satisfy a conditional requirement but is not charged as an extra content
field when unused.

### Error taxonomy

Every run carries `error_codes` from the fixed set `provider_api`, `quota`,
`timeout`, `structured_output`, `missing_field`, `wrong_binding`,
`wrong_context`, `unsupported_expression`, `compilation`, `renderer` and
`harness`. A run can carry several semantic codes; `primary_error` records one
dominant code for every run that has at least one code, including semantic
misses that still produced a valid template. The report counts both "runs with
code" and primary codes; the primary counts are not the failed-run count.

### Cost

Cost status is `verified` (provider-reported usage and a published price),
`estimated` (unpriced model with a documented proxy rate) or `unavailable`
(neither). Gemini 3.6-flash is unpriced: its cost uses the documented
Gemini 3.8-flash proxy and is never rendered as $0.00. The budget guard aborts
before a call whose worst case could cross `--max-spend`.

### Reproduce

```bash
.venv/bin/python benchmarks/semantic_evaluation.py \
  --providers openai:gpt-6-sol,anthropic:claude-sonnet-5-5,gemini:gemini-3.6-flash \
  --repeats 3 --repair-attempts 2 --allow-unpriced --max-spend 6 --warn-spend 5
```

The HTML report is self-contained, shows per-metric leaders (ties included),
and says explicitly that the numbers are observations, not statistical
significance. It never declares a single winner.

### Results

The committed run is summarised from
[benchmarks/semantic_report.json](../benchmarks/semantic_report.json). Values are
per-provider aggregates over 60 attempted runs each (20 cases × 3 repeats); see
the report for per-case rows, latency, error counts and cost status.

**Dataset.** 20 cases, 18 English plus one German and one French brief. By
label: fields 11, collections 5, images 2, conditions 2, nested lists 1,
multilingual 2, ambiguous 2, missing requirement 1, forbidden scope 3, tables 3,
VAT 3, header 2, footer 1, bank 2. Labels overlap, so they do not sum to 20.

| Provider | Model | Runs | Precision | Recall | Coverage | Type/context | Blocks | Semantic pass | Valid template | p50 / p95 | Spend |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| OpenAI | `gpt-6-sol` | 60 | **0.261** | 1.000 | 1.000 | 1.000 | 0.778 | 58.3% | 100% | 17.0 / 22.1 s | $1.8218 (verified) |
| Anthropic | `claude-sonnet-5-5` | 60 | 0.203 | 1.000 | 1.000 | 1.000 | **1.000** | **73.3%** | 100% | 12.1 / 19.6 s | $2.5598 (verified) |
| Gemini | `gemini-3.6-flash` | 60 attempted (59 planned) | 0.183 | 1.000 | 1.000 | 1.000 | 0.930 | 68.3% | 96.7% | **3.96 / 10.54 s** | **$0.2080 (estimated)** |

Per-valid-template cost: OpenAI $0.03036 (verified), Anthropic $0.04266
(verified), Gemini N/A because one attempt returned no usage (unknown, not
zero). The overall cost-per-valid-template value is therefore unavailable.

**Error taxonomy.** `wrong_binding`: 170 runs; `wrong_context`: 26 runs;
`structured_output`: 1 run. All other codes were zero. The one
`structured_output` failure is Gemini's `wide-line-table` repeat 3 ("the model
did not return a JSON object", 9.1 s, no usage). The primary-code counts are
`wrong_binding` 170 and `structured_output` 1; `wrong_context` appears only as a
secondary code because `wrong_binding` sorts first when both are present.
There were no `missing_field`, `provider_api`, `quota`, `timeout`,
`unsupported_expression`, `compilation`, `renderer` or `harness` codes.

**What the numbers show (observations, not significance).**

- Every provider matched every required field (recall, coverage and
  type/context correctness are all 1.0). The separation is in *extra* bindings
  and shape: precision is 0.261 / 0.203 / 0.183, and semantic pass is 58.3% /
  73.3% / 68.3%.
- OpenAI has the highest precision but the lowest block coverage: it often used a
  paragraph repeat where the brief asked for a table. Anthropic produced the
  requested tables and has the highest semantic pass rate. Gemini is the fastest
  and least expensive, but its cost is a proxy estimate and one run has unknown
  cost.
- Technical validity and semantic correctness diverge on the same runs: OpenAI
  and Anthropic are 100% valid templates but only 58.3% / 73.3% semantically
  passing; Gemini is 96.7% valid. This is exactly what the two metric families
  are meant to keep separate.
- No single winner is declared: precision, block coverage, semantic pass,
  valid-template rate, cost and latency have different leaders. The report shows
  each metric's leader with ties.
- Three repeats are not a population sample. These are run-to-run observations
  on synthetic fixtures; they do not establish statistical significance or
  customer acceptance.

Spend: **$4.3816 verified + $0.2080 estimated = $4.5896**; the $5 warning line
was not reached and the $6 cap was not crossed. One run has unknown cost, so the
report keeps it in `unknown_runs` rather than treating it as free.

## 2.6 Reference-based evaluation (REF-05)

The semantic harness above asks whether a plan satisfies a hand-authored prompt. REF-05 asks a
different question: **does the plan reproduce the patterns and bindings observed in a reference
template?** The runner is
[benchmarks/reference_evaluation.py](../benchmarks/reference_evaluation.py).

It maps reference controls/elements to five expected concepts:

| Reference pattern | Expected concept | Produced evidence |
| --- | --- | --- |
| Field | scalar | field binding |
| List | collection | repeat/table collection |
| If | condition | conditional expression |
| Image | image | image binding |
| Label | text | field binding (text role) |

### Gold set

[benchmarks/reference_cases.json](../benchmarks/reference_cases.json) contains eight hand-authored
synthetic cases: Field scalar, Field date, List collection, If condition, Image logo, Label text,
header/body/footer context and a mixed invoice. They cover 41 expected concepts. The DOCX/DDSP
fixtures under [benchmarks/fixtures/reference](../benchmarks/fixtures/reference) are generated by
[benchmarks/reference_fixtures.py](../benchmarks/reference_fixtures.py). No Docentric corpus content
is used. The evaluator also derives concepts from each synthetic reference and reports any mismatch
with the committed gold (`consistency` in the JSON report), so the pattern mapping is checked rather
than assumed.

### Metrics

| Metric | Definition |
| --- | --- |
| `precision` | matched produced observations / all reference-relevant produced observations |
| `recall` | matched required concepts / required concepts |
| `coverage` | matched concepts / all expected concepts (including optional ones) |
| `f1` | harmonic mean of precision and recall |
| `type_context_correctness` | type and placement checks passed / checks performed |
| `semantic_pass_rate` | runs with no missing/wrong/extra binding and no forbidden hit |
| `valid_template_rate` | validation + compilation successes / runs |

`valid_template_rate` is reported at the top level, inside `valid_templates`, and must not be read
as semantic accuracy. A plan can validate and compile while binding the wrong pattern.

### Synthetic result

```bash
.venv/bin/python benchmarks/reference_evaluation.py --provider mock
```

| Metric | Value |
| --- | --- |
| Cases / runs | 8 / 8 |
| Expected concepts | 41 |
| Precision / recall / coverage | 0.891 / 1.000 / 1.000 |
| F1 | 0.943 |
| Type/context correctness | 1.000 |
| Semantic pass rate | 0.375 |
| Valid template rate | 1.000 |
| Cost | verified, $0.00 |

Five runs produced one extra field each that the reference template did not contain. Those are
false positives by design, so the semantic pass rate is lower than recall; it is not a validation
failure.

### Local-corpus mode

```bash
.venv/bin/python benchmarks/reference_evaluation.py \
  --reference <ignored-corpus>/Template.docx \
  --ddsp <ignored-corpus>/Template.ddsp \
  --prompt-file prompt.txt --provider mock \
  --output-json <ignored-corpus>/reports/template.json
```

`--reference` inspects a DOCX/AXPP at runtime and derives the expectations from it. The report
records `provenance.kind = "local-corpus"`, `committed = false` and no absolute paths; it must stay
in an ignored directory. This milestone ran the mode once against two AX 2012 references and
publishes counts only:

| Reference | Concepts | Matched | Precision | Recall / coverage | Type/context | Valid templates |
| --- | --- | --- | --- | --- | --- | --- |
| AX 2012 reference 1 | 22 (3 unsupported) | 11 | 0.478 | 0.500 | 1.000 | 1.000 |
| AX 2012 reference 2 | 39 (3 unsupported) | 13 | 0.722 | 0.333 | 1.000 | 1.000 |

These are mock-baseline observations on a small set, not a model-quality claim. Real AX DDSP
contracts expose XSD attributes as `@Name`; Template IR 1.0 forbids raw attribute/XPath segments.
For evaluation only, the runner creates an IR-safe schema view and applies the same path mapping to
the reference concepts. Role, type, collection and context are unchanged, and the report records
how many segments were normalized. Template IR, the reference graph and all compilers are
unchanged.

### Cost and live providers

The default `mock` provider is deterministic and makes no paid calls; its report status is
`verified` at zero. A non-mock provider requires `--allow-paid`; cost is `verified` only when the
provider reports usage and the model has a versioned price, `estimated` when a documented proxy is
used, and `unavailable` otherwise. Unknown cost is never rendered as `$0.00`. The report writes
JSON, CSV and self-contained HTML with sample size, provenance, pattern counts, error taxonomy and
cost status.

## 2.7 Gold semantic benchmark (v0.10 PR-05)

> **Historical artifact.** This section describes the v0.10 full 288-run report on dataset `1.0.0`.
> The current dataset is `gold-cases/v2`, version `2.0.0`; the current measurement is the affected
> 72-run subset in [§2.8](#28-v011-semantic-precision-and-adjudicated-labels-2425). Do not splice
> the v0.10 aggregate with v0.11 subset numbers or compare them without the label/prompt changes
> documented in [GOLD_LABELS](GOLD_LABELS.md).

The 20-case semantic harness above is useful for smoke tests but too small for a product claim.
PR-05 adds a versioned 32-case gold dataset with a fixed calibration/holdout split and a live
runner that reports per-family, per-split and per-provider metrics.

| Item | Value |
| --- | --- |
| Dataset | [benchmarks/gold_cases.json](../benchmarks/gold_cases.json) — 32 cases, `gold-cases/v1`, version `1.0.0` |
| Annotation guide | [GOLD_LABELS.md](GOLD_LABELS.md) |
| Rule pass | [benchmarks/gold_dataset.py](../benchmarks/gold_dataset.py) |
| Runner | [benchmarks/gold_evaluation.py](../benchmarks/gold_evaluation.py) |
| Scoring | [benchmarks/semantic_scoring.py](../benchmarks/semantic_scoring.py) (pure functions) |
| Per-run records | `benchmarks/gold_runs.jsonl` (git-ignored; no prompt text or raw output) |
| Reports | [gold_report.json](../benchmarks/gold_report.json), `.csv`, `.html` |
| Settings | Gemini compact v2, repairs 2; priced providers full IR, repairs 1; temperature 0 |
| Budget | `--max-spend 10`, `--warn-spend 5`; running known + estimated spend printed per run |

### Dataset

The 32 cases cover ten families: flat fields (5), images (3), collections (4), nested lists (3),
conditions (3), missing (2), ambiguous (3), multilingual (3), long tables (3) and forbidden scope
(3). By specification category: 10 purchase order, 10 sales order, 6 conditional/complex and 6
adversarial/negative. The split is 20 calibration / 12 holdout, stratified so both splits contain
every family and every category. The canonical cases SHA-256 is recorded in the report.

Every case declares concept-level `required_bindings` (expected paths, allowed alternatives,
required, type/context, satisfiability), `forbidden_paths`, `expected_blocks`, `family`, `category`,
`difficulty`, `split` and `language`. A missing requirement is marked `satisfiable: false` and is
excluded from recall/coverage; inventing a binding for it is a `wrong_binding`. Ambiguous prompts
list defensible alternatives; if a run produces more than one acceptable variant, the duplicate is
not charged as a false positive. Forbidden paths are never exempt.

**Annotation limitation.** The labels were authored by the implementer and validated by the
deterministic rule pass. There was no independent human double review. The rule pass checks paths,
types, contexts, block kinds, family invariants and split sizes; it cannot validate business
judgement. AT-07 is therefore **partial**, and reports state this limitation.

### Metrics

Let `TP` be matched requirements, `FP` produced bindings that no requirement accepts (including
forbidden paths), `FN` required requirements that remain unmatched, `R` required satisfiable
requirements and `S` satisfiable requirements.

| Metric | Definition |
| --- | --- |
| `precision` | `TP / (TP + FP)` |
| `recall` | matched required / `R` |
| `f1` | harmonic mean of precision and recall |
| `requirement_coverage` | matched satisfiable / `S` |
| `type_context_correctness` | correct type/context checks / checks performed |
| `block_coverage` | satisfied `expected_blocks` / declared blocks |
| `semantic_pass_rate` | runs where every required requirement and block is satisfied, no forbidden path is hit, and no type/context error is recorded |
| `valid_template_rate` | deterministic validation + generic DOCX compilation, **reported separately** |
| `cost_per_correct_result_usd` | total cost / runs that pass both semantics and compilation |
| latency | p50 and p95 over planned runs, in milliseconds |

The runner reports each metric overall, per provider, per split (calibration and holdout separately),
per family, per category and per case. It never collapses semantic quality and compilation into one
number. The HTML report includes the dataset hash, split, model versions, prompt version, settings,
date, sample sizes and the explicit "observations, not significance" note.

### Error taxonomy

The shared taxonomy is `provider_api`, `quota`, `timeout`, `structured_output`, `missing_field`,
`wrong_binding`, `wrong_context`, `unsupported_expression`, `compilation`, `renderer` and `harness`.
A run may carry several semantic codes; the report shows both "runs with code" and one primary code
per run that has at least one. Primary counts are not failed-run counts.

### Cost

Cost is `verified` (provider-reported usage and a published price), `estimated` (unpriced model with
a documented proxy) or `unavailable`. Gemini 3.6-flash is unpriced: the runner uses the documented
Gemini 3.8-flash proxy and keeps the `estimated` status. It is never displayed as `$0.00`. The
budget guard warns at $5 and aborts before a call whose worst case could cross the $10 cap.

### Reproduce

```bash
.venv/bin/python benchmarks/gold_evaluation.py \
  --providers openai:gpt-6-sol,anthropic:claude-sonnet-5-5,gemini:gemini-3.6-flash \
  --repeats 3 --split all --max-spend 10 --warn-spend 5 --allow-unpriced
```

A budget-constrained run can add `--paid-repeats 2`: Gemini keeps three repeats, priced providers
use two, and the report records the difference instead of silently truncating the matrix. A provider
without credentials is reported as `not_run`, never substituted with the mock.

### Committed live run (2026-11-05)

Source: [benchmarks/gold_report.json](../benchmarks/gold_report.json), generated by
`benchmarks/gold_evaluation.py` with the command above. Dataset version `1.0.0`, canonical SHA-256
`c2b1d89c70f96f14884de54792784d0dbd3ffaa71d0700d5f73c5c24e93ece30`.

All **288 planned runs completed** (32 cases × 3 providers × 3 repeats); no run was omitted and no
`not_run` provider was silently mocked. Gemini attempted 96 runs and produced 93 planned results:
three compact-IR responses were rejected by the deterministic expander (`structured_output`) and
carry no token usage, so their cost is `unavailable`, not zero.

| Provider | Model | Runs | Valid | Correct | Precision | Recall | F1 | Coverage | Type/context | Blocks | Semantic pass | Valid template | p50 / p95 | Spend | Cost / correct |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| OpenAI | `gpt-6-sol` | 96 | 96 | 53 | **0.226** | 1.000 | **0.368** | 1.000 | 0.995 | 0.851 | 55.2% | 100.0% | 15.5 / 20.0 s | **$2.9754 (verified)** | **$0.0561 (verified)** |
| Anthropic | `claude-sonnet-5-5` | 96 | 96 | 67 | 0.220 | 0.996 | 0.361 | 0.996 | **0.998** | **0.943** | **69.8%** | 100.0% | 10.7 / 20.6 s | $3.9096 (verified) | $0.0584 (verified) |
| Gemini | `gemini-3.6-flash` | 96 attempted / 93 planned | 93 | 62 | 0.184 | 1.000 | 0.311 | 1.000 | 0.998 | 0.911 | 64.6% | 96.9% | **4.1 / 10.2 s** | **$0.2910 (estimated)** | N/A (`unavailable`: 3 unknown runs) |

The overall cost per correct result is **N/A** because three Gemini runs have no usage evidence.
The provider-level verified figures for OpenAI and Anthropic are $0.0561 and $0.0584 per run that
passes both semantic and compilation gates. The overall spend was **$6.8849 verified + $0.2910
estimated = $7.1759**; the $5 warning line fired at $5.0226 and the $10 cap was not crossed. The run
was not aborted.

### Calibration vs holdout

| Split | Provider | Runs | Precision | Recall | F1 | Semantic pass | Valid template | Spend |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Calibration | OpenAI | 60 | 0.239 | 1.000 | 0.386 | 51.7% | 100.0% | $1.8967 |
| Calibration | Anthropic | 60 | 0.242 | 0.995 | 0.389 | **71.7%** | 100.0% | $2.4301 |
| Calibration | Gemini | 60 | 0.196 | 1.000 | 0.327 | 63.3% | 96.7% | $0.1865 (estimated) |
| Holdout | OpenAI | 36 | 0.203 | 1.000 | 0.337 | **61.1%** | 100.0% | $1.0787 |
| Holdout | Anthropic | 36 | 0.186 | 1.000 | 0.314 | 66.7% | 100.0% | $1.4795 |
| Holdout | Gemini | 36 | 0.164 | 1.000 | 0.282 | 66.7% | 97.2% | $0.1045 (estimated) |

The holdout does not confirm a calibration-tuned prompt. On this sample OpenAI's semantic pass is
higher on holdout (61.1% vs 51.7%), Anthropic's is lower (66.7% vs 71.7%) and Gemini's is roughly
flat (66.7% vs 63.3%). Precision is lower on holdout for all three providers. With 12 holdout cases
(36 runs per provider) these are observations, not evidence of a stable ranking.

### Error taxonomy

| Code | Runs with code | Primary code runs |
| --- | ---: | ---: |
| `wrong_binding` | 276 | 275 |
| `wrong_context` | 70 | 0 |
| `structured_output` | 3 | 3 |
| `missing_field` | 1 | 1 |
| `provider_api`, `quota`, `timeout`, `unsupported_expression`, `compilation`, `renderer`, `harness` | 0 | 0 |

A run can carry several semantic codes. `wrong_binding` is dominated by extra unrequested bindings
and forbidden-scope hits; it is not only a wrong-path count. The three `structured_output` failures
are Gemini compact-IR rejections (nested task effort repeat 1, 40-row table repeat 2, nested service
amounts repeat 2). The single `missing_field` is a required vendor address missing from one
Anthropic footer run; the only `wrong_context` outcomes are secondary to `wrong_binding` and block
failures, which is why the primary count is zero.

### What the numbers show (observations, not significance)

- **Recall and coverage are saturated; precision is the differentiator.** Every provider matched
  essentially every required concept (recall 0.996–1.000) and put the bindings in the right
  type/context almost always (0.995–0.998). The difference is extra bindings: precision is
  0.226 / 0.220 / 0.184 and F1 is 0.368 / 0.361 / 0.311. Models frequently bind large parts of the
  schema that the prompt did not request.
- **Structural blocks separate the providers.** Block coverage is 0.851 (OpenAI), 0.943 (Anthropic)
  and 0.911 (Gemini). Nested service lists are the hardest family: semantic pass is 22.2% / 44.4% /
  0% and the usual failure is a paragraph repeat where a nested table was requested. Conditions,
  missing and ambiguous cases pass at 100% for all three providers.
- **Over-binding masks some family signals.** All three providers score 0% semantic pass on the
  images family because they bind every scope-guarded path in the schema (for example a vendor or
  customer name next to the requested company logo), and semantic pass is an all-or-nothing gate.
  OpenAI's multilingual pass is 0% for the same reason. The precision metric still shows the
  difference; the 0% is a scope-adherence result, not an image-recognition result. A future label
  revision should decide whether unrelated forbidden paths belong in the image family gate.
- **Gemini is fastest and cheapest, with a compact-IR reliability cost.** p50 is 4.1 s versus 10.7 s
  and 15.5 s; estimated spend is $0.2910 versus $3.9096 and $2.9754. Three compact-IR responses were
  rejected (valid template 96.9%), and because those runs have no usage their cost is unknown. The
  provider is not free and is never reported as $0.00.
- **No single winner.** OpenAI leads precision and F1, Anthropic leads semantic pass, block coverage
  and type/context, Gemini leads latency and cost. The report lists each metric's leader with ties
  and does not aggregate them into one score.
- **Calibration and holdout disagree in direction.** That is exactly why they are shown separately;
  a single mixed percentage would hide it.
- **Annotation limitation.** Labels are single-annotator and rule-pass validated. AT-07 is partial;
  AT-08 is met (three repeats per case/model); AT-09 is met (precision, recall, F1, coverage,
  type/context, block coverage and class-level error taxonomy). None of this changes
  `runtime_compatibility: not_tested`.

Spend: **$6.8849 verified + $0.2910 estimated = $7.1759**, under the $10 cap, above the $5 warning
line. Three runs have unknown cost and are kept in `unknown_runs` rather than treated as free. The
full report contains per-family, per-category and per-case rows; the CSV and self-contained HTML are
generated from the same JSON.

### What the numbers mean

- Calibration and holdout are separate. A holdout result is not a confirmation of a prompt tuned on
  calibration; it is the closest available out-of-sample check.
- Precision and recall can move in opposite directions because the label set is strict: extra
  unrequested bindings are false positives, while a missing required concept is a false negative.
- A 100% `valid_template_rate` with a lower `semantic_pass_rate` is the expected signature of a
  schema-valid but semantically wrong plan. That divergence is the reason both metric families
  exist.
- The sample is small and the repeats are not independent draws from a population. The report does
  not declare a single winner and does not claim statistical significance.
- Docentric AX runtime compatibility remains `not_tested`; no semantic score changes that gate.

## 2.8 v0.11 semantic precision and adjudicated labels (#24/#25)

### What changed

The v0.10 gold benchmark had recall 0.996–1.000 and precision 0.184–0.226. The v0.11 P0 work
addressed both sides of that result:

- **Labels (#24).** `benchmarks/adjudicate_labels.py` is an independent deterministic second pass.
  It re-derives paths from the prompt and schema with its own lexicon and does not import the
  planner's retrieval. The dataset is now schema `gold-cases/v2`, version `2.0.0`, with per-label
  provenance and `label_status`. The adjudicator reproduced 32/32 cases and 98/98 requirement labels;
  two genuine prompt/label mismatches were fixed (the prompt now requests the line description and
  the outer table it already required). AT-07 remains **partial**: this is a proxy, not a human
  reviewer.
- **Precision (#25).** The planner decomposes the brief into typed requirements, retrieves only
  schema evidence that satisfies hard type/namespace/collection constraints, ranks it
  deterministically and sends a bounded `<candidate_bindings>` list (24 total, 4 per requirement)
  instead of the whole schema. After generation it re-validates every binding against candidate
  evidence. An ambiguous requirement and a requirement with no supported binding become
  `needs_review` rows; they are never filled with a guessed path. The system prompt also forbids
  unrequested blocks and fixes the window where a header-only plan left an empty body.
- **Image family.** The three image cases ask for the company logo; the annotated path exists, and
  v0.10 produced it in 27/27 image runs. The 0% semantic pass was caused by forbidden-scope
  contamination, not by an inexpressible image. All three stay `label_status: "verified"` and are
  reported in a separate scorecard. Only company logo is covered; product image, image collection,
  optional image and negative image cases remain gaps.

### Counters

`benchmarks/gold_evaluation.py` now publishes:

| Counter | Definition |
| --- | --- |
| `planned_runs` | selected cases × configured providers × repeats |
| `executed_runs` | per-run records actually attempted |
| `skipped_runs` | planned minus executed (budget abort, provider not configured, stop) |
| `succeeded_runs` / `failed_runs` | executed split by whether the run produced a result; `executed = succeeded + failed` |
| `valid_template_runs` | subset of succeeded runs whose IR validates and compiles; not the same as succeeded |
| `semantic_pass_runs` | successful semantic passes over non-gap runs |
| `semantic_excluded_runs` | runs whose case is `label_status: "gap"`; excluded from semantic denominators |
| `pass@k` | per `(provider, case)` group, fraction with at least one semantic pass among the first k repeats; groups with fewer than k runs are excluded from that k's denominator |
| `abstention_rate` | executed runs with at least one `needs_review` requirement and no selected path, divided by executed runs |
| `review_rate` / `review_requirements` | runs with any review row / total review rows; an accepted alternative is a review row but not an abstention |
| `family_semantic_pass` | semantic pass and pass@k per family and provider |
| `image_family` | per-case image scorecard with label status, image path, runs where the image binding was present and per-provider semantic pass |
| `governance.at07_status` | `partial`; `second_human_annotator: false`; deterministic adjudicator named |
| `comparison` | Before/after block written by `benchmarks/compare_subset.py`: v0.10 baseline per-case metrics vs the v0.11 subset, with the repeat-count difference stated. Baseline abstention is `not_measured`, never zero. |

The two invariants are asserted in every report:
`planned_runs = executed_runs + skipped_runs` and
`executed_runs = succeeded_runs + failed_runs`. Retry attempts are recorded per run, not added to
`planned_runs`.

### Reproduce the affected subset

```bash
.venv/bin/python benchmarks/gold_evaluation.py \
  --providers openai:gpt-6-sol,anthropic:claude-sonnet-5-5,gemini:gemini-3.6-flash \
  --case-ids po-image-logo-header,so-image-logo-footer,so-image-logo-header-invoice,\
po-ambiguous-supplier-contact,so-ambiguous-vat-number,adv-missing-requisition-number,\
adv-missing-customer-po-reference,cc-nested-service-tasks,cc-nested-task-effort,\
adv-forbidden-customer-bank,adv-forbidden-company-as-customer,adv-collection-forbidden-columns \
  --repeats 2 --repair-attempts 1 --allow-unpriced --max-spend 4 --warn-spend 3 \
  --runs-file benchmarks/gold_runs_v011_subset.jsonl \
  --output-json benchmarks/gold_report_v011_subset.json
.venv/bin/python benchmarks/compare_subset.py
```

The first command writes the run report. The second adds the reproducible before/after block by
reading the committed v0.10 `per_case` metrics for the same 12 cases; it does not need the
git-ignored v0.10 raw runs. The command uses Gemini compact v2 with its pinned two repair calls; the priced providers keep the
product default of one repair call. This is a scoped 72-run before/after check, not a new 288-run
ranking. The v0.10 full report remains the full-matrix artifact and is not spliced with this subset.

### Subset results

The affected-subset run is committed as
[benchmarks/gold_report_v011_subset.json](../benchmarks/gold_report_v011_subset.json). It is
72 planned runs, **72 executed, 0 skipped**, **70 valid templates**, **69 semantic passes** and
**67 correct runs**, with spend **$0.9387** (verified
$0.9055 + estimated $0.0332) under the **$4 cap**.
The **$3 warning line did not fire**. There were no failed runs.
The two validation misses are Anthropic's `cc-nested-task-effort` rows (duplicate repeat alias,
`V3-002`); the three semantic misses are Gemini nested-list block-shape failures. Neither is a
schema-evidence or label failure.

**Before/after.** The baseline is the committed v0.10 full report read case-by-case for the same
12 cases (dataset `1.0.0`, 3 repeats). The v0.11 subset has 2 repeats, so the table states both run
counts and does not splice the two aggregate reports. Baseline abstention was **not measured**
(v0.10 had no abstention signal), not zero.

| Provider | Runs (before → after) | Precision before → after | Recall before → after | Semantic pass before → after | Image pass before → after | Abstention after | pass@2 after | Spend after |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| OpenAI | 36 → 24 | 0.161 → 0.962 | 1.000 → 1.000 | 41.7% → 100.0% | 0.0% → 100.0% | 25.0% | 100.0% | $0.2901 (verified) |
| Anthropic | 36 → 24 | 0.135 → 0.962 | 1.000 → 1.000 | 44.4% → 100.0% | 0.0% → 100.0% | 25.0% | 100.0% | $0.6155 (verified) |
| Gemini | 36 → 24 | 0.129 → 0.962 | 1.000 → 1.000 | 47.2% → 87.5% | 0.0% → 100.0% | 25.0% | 91.7% | $0.0332 (estimated) |
| **All providers** | 108 → 72 | **0.141 → 0.962** | 1.000 → 1.000 | 44.4% → 95.8% | **0.0% → 100.0%** | **25.0%** | **97.2%** | **$0.9387** |

**Observations.**

- **Precision recovered from 0.141 to 0.962** on the affected subset, while **recall stayed 1.000**.
  The gain is not from a looser scorer: it comes from sending only evidence-backed candidates and
  from rejecting unrequested/forbidden bindings before they are accepted.
- **The image family went from 0% to 100%** semantic pass for all three providers. The required
  image binding was present in 18/18 image runs, there were no forbidden hits, and the image
  scorecard reports each case separately. This confirms the v0.10 0% was a scope-precision failure,
  not an image-recognition failure.
- **`pass@2` is 0.972** overall (OpenAI 1.000, Anthropic 1.000, Gemini 0.917). Gemini's three
  nested-list misses are the compact-v2 limitation: the format cannot express an outer `tbl` whose
  rows contain a nested repeat/table, so Gemini emits an outer `rep` with an inner `tbl`. The label
  is correct and stays unchanged; this is a wire-format gap, reported rather than hidden.
- **Abstention is 25.0%** (18/72), all from the two missing-field cases and the unsatisfiable
  customer-bank case. Those are exactly the runs whose requirements have no schema evidence; the
  candidate rows say `NO SUPPORTED BINDING` and the planner does not invent a path. A bound
  ambiguous alternative is a review row, not an abstention (`review_rate` is 41.7%, higher than
  `abstention_rate`).
- **Constraints remain separate.** The 70/72 valid-template rate is not folded into precision; the
  two `V3-002` validation misses keep Anthropic's semantic pass at 100% but its valid-template rate
  at 91.7%. This is the intended separation.
- **Label state.** The dataset is `2.0.0` with 32 verified labels, 0 gap cases, and AT-07 still
  **partial**. The independent deterministic adjudicator reproduced 32/32 cases and 98/98
  requirement labels; it is a proxy, not a human reviewer.
- **Scope.** This is not a new 288-run ranking. It is a 12-case before/after check on the families
  affected by #24/#25. The v0.10 full report remains the full-matrix artifact and must not be
  spliced with this subset.


## 2.9 v0.11 P1 reference workflow is not a benchmark result (#26–#30)

The v0.11 P1 workstreams extend the reference inspector; they do not add a new semantic score and
must not be read as an improvement over the adjudicated gold benchmark.

- **#26 D365 graph evidence** changes representation, not evaluation labels. The graph summary adds
  `evidence_coverage_ratio` and `unresolved_by_status`, but no precision/recall number is derived
  from it. The committed tests are synthetic; the 11-DOCX local corpus was not re-run in this
  branch.
- **#27 safe IR import** is a transformation with explicit skips, not a planner score. A successful
  strict import means every imported construct was resolved and schema-backed; it does **not** mean
  the generic document is semantically equivalent to the reference. There is no semantic-pass metric
  for imported IR in this release.
- **#28 visual diff** is page-level rendering evidence from LibreOffice, not Word fidelity and not a
  gold-benchmark metric. A `different` status is not an error count; `renderer_unavailable` is
  missing evidence and is excluded from any aggregate claim. Structural and semantic statuses stay
  `not_compared` in that report.
- **#29 persistence/export** stores and re-serves the same report bytes; it does not change metrics.
  The HTML export is escaped and does not embed source active content.
- **#30 documentation** records the same partial scope in the README, ROADMAP, CHANGELOG and
  [REFERENCE_TEMPLATES](REFERENCE_TEMPLATES.md#what-is-not-implemented-or-only-partial).

Consequently, the v0.10/2.0.0 gold results and the v0.11 affected-subset results remain the only
measured semantic claims. Docentric AX runtime compatibility remains `not_tested`, and none of the
P1 features is evidence for changing it.
