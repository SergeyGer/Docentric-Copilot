# Evaluation

| Field | Value |
| --- | --- |
| Purpose | Measure planner quality and cost on a fixed, reproducible case set |
| Harness | [packages/evaluation/src/docentric_copilot/evaluation/metrics.py](../packages/evaluation/src/docentric_copilot/evaluation/metrics.py), [benchmarks/run_evaluation.py](../benchmarks/run_evaluation.py) |
| Cases | [benchmarks/evaluation_cases.json](../benchmarks/evaluation_cases.json) (3 synthetic fixtures) |
| Default provider | `mock` (deterministic baseline, no credentials) |
| Related | [BENCHMARKS](BENCHMARKS.md), [SRS](SRS.md), [DDSP_COMPATIBILITY](DDSP_COMPATIBILITY.md) |

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

### 2.3 Known measurement limitations

These are properties of the current harness, not of the product. They must be fixed before recall
numbers are used for decisions.

1. **Alias bindings are not resolved when collecting `actual_paths`.** The collector calls
   `resolve_value(schema, binding.path, Scope())` with a root scope, so bindings such as
   `line.ItemId` inside a table repeat fail to resolve and are omitted. Table-item fields therefore
   appear in the ground truth but not in the actual set.
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
| Field selection precision | 1.000 | 44 / 44 |
| Field selection recall | 0.772 | 44 / 57 |
| Requirement coverage | 1.000 | 27 / 27 |
| Compilation success rate | 1.000 | 3 / 3 |
| Clarification rate | 0.000 | 0 / 27 |
| Correction rate | 0.000 | 0 / 3 |
| Verified compatibility rate | 0.000 | 0 / 3 |
| Cost per valid template (USD) | 0.000 | 0.0 / 3 |

Interpretation with the limitations in §2.3:

- **Precision 1.0** means every path the baseline bound was in the ground truth. It does *not* mean the
  documents are complete: recall is 0.772.
- **Recall 0.772** is dominated by collection/table paths and condition-only fields that the current
  collector does not count (see §2.3). It should be re-measured after the harness resolves aliases; the
  number is reported as-is rather than adjusted by hand.
- **Requirement coverage 1.0** means every extracted clause got a `resolved` mapping. The mapping
  report is lenient in two documented ways: a clause matched by the document title is `resolved`, and a
  clause whose best field is bound is `resolved` even if other clauses reuse the same field.
- **Clarification 0.0** means the baseline never returned `ambiguous` on these fixtures. On a small,
  well-named synthetic schema that is expected; it is not evidence that the baseline recognises
  ambiguity in general.
- **Compilation 1.0** means the three fixtures compile. Golden and integration tests assert the same.
- **Compatibility 0.0** is the gate, not a failure of the compiler. No compatibility is claimed.

### 5.2 LLM comparison (to be filled)

No hosted-provider evaluation has been run in this repository. The table is a skeleton; every cell is
`TBD` until a run is recorded with its command, model and commit.

| Provider / model | Cases | Precision | Recall | Coverage | Compilation | Clarification | Correction | Cost / valid template | p95 latency | Commit |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| mock (baseline) | 3 | 1.000 | 0.772 | 1.000 | 1.000 | 0.000 | 0.000 | $0.000 | TBD | TBD |
| openai / `<model>` | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| anthropic / `<model>` | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| gemini / `<model>` | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |

How each `TBD` will be measured:

- **Metrics**: `benchmarks/evaluation.json` from the matching command; repeat ≥ 3 times and report
  median and range.
- **Cost / valid template**: `cost_usd` from `GenerationResult.usage.estimated_cost_usd`, divided by
  compiled cases. Verify the model is in `llm/pricing.py`; otherwise record `unpriced`.
- **p95 latency**: the `plan` stage from `benchmarks/run_benchmarks.py --provider ...` (see
  [BENCHMARKS](BENCHMARKS.md)); the evaluation harness does not measure timings.
- **Commit**: the git commit of the run, so results are attributable.

## 6. Reproducibility checklist

For every result published in this file or in a PR:

1. Command executed verbatim.
2. Provider and exact model identifier; whether an API key was configured.
3. Commit hash and Python version.
4. Cases file version (the JSON is part of the repository).
5. Raw output file path (`benchmarks/evaluation.json` or an alternative).
6. Number of repetitions and how variance was handled.
7. Known limitations that apply (§2.3) and whether any were fixed for this run.

Results without these are anecdotes and must not be presented as metrics.

## 7. Threats to validity

| Threat | Effect | Mitigation |
| --- | --- | --- |
| Tiny, synthetic case set | Overstates generalisation | Add permitted real fixtures; report per-case results |
| Ground truth authored by the same team | Confirmation bias | Independent review of `expected_paths`; publish the cases |
| Alias/collection accounting (§2.3) | Recall understated | Fix the collector and re-baseline; version the change |
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
