# Evaluation

| Field | Value |
| --- | --- |
| Purpose | Measure planner quality and cost on a fixed, reproducible case set |
| Harness | [metrics.py](../packages/evaluation/src/docentric_copilot/evaluation/metrics.py), [reporting.py](../packages/evaluation/src/docentric_copilot/evaluation/reporting.py), [run_evaluation.py](../benchmarks/run_evaluation.py), [live_evaluation.py](../benchmarks/live_evaluation.py) |
| Cases | [benchmarks/evaluation_cases.json](../benchmarks/evaluation_cases.json) (3 synthetic fixtures), [benchmarks/live_cases.json](../benchmarks/live_cases.json) (12 live cases) |
| Default provider | `mock` (deterministic baseline, no credentials) |
| Related | [BENCHMARKS](BENCHMARKS.md), [PRICING](PRICING.md), [ROUTING](ROUTING.md), [SRS](SRS.md), [DDSP_COMPATIBILITY](DDSP_COMPATIBILITY.md) |

This document defines the metrics, describes the harness as implemented, and separates what has been
measured from what is still `TBD`. It contains **no** invented numbers: every non-`TBD` value comes
from a committed run of the harness, quoted with its command and caveats.

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

### 5.2 Hosted-provider comparison (pending)

The mock baseline row is measured. No hosted-provider evaluation has been run in this repository, so
the OpenAI/Anthropic/Gemini rows are `TBD` until a run is recorded with its command, model and commit.
Latency is deliberately not part of this table: measure it separately with
[`benchmarks/run_benchmarks.py`](BENCHMARKS.md).

| Provider / model | Cases | Precision | Recall | Coverage | Compilation | Clarification | Correction | Cost / valid template | Evidence | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| mock (baseline) | 3 | 0.932 | 0.965 | 1.000 | 1.000 | 0.000 | 0.000 | $0.000 | `benchmarks/evaluation.json` | V1-V3 autonomous; no LLM cost |
| openai / `<model>` | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| anthropic / `<model>` | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| gemini / `<model>` | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |

How each `TBD` will be measured:

- **Metrics**: `benchmarks/evaluation.json` from the matching command; repeat ≥ 3 times and report
  median and range.
- **Cost / valid template**: `cost_usd` from `GenerationResult.usage.estimated_cost_usd`, divided by
  compiled cases. Verify the model is in `llm/pricing.py`; otherwise record `unpriced`.
- **Latency**: not measured by this harness; use `benchmarks/run_benchmarks.py --provider ...` and
  record the result in [BENCHMARKS](BENCHMARKS.md).
- **Commit**: the git commit of the run, so results are attributable.

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
