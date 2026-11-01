# Benchmarks

| Field | Value |
| --- | --- |
| Runner | [benchmarks/run_benchmarks.py](../benchmarks/run_benchmarks.py) |
| Output | `benchmarks/results.json` (default) |
| Default runs | 100 per example per stage |
| Provider | `mock` by default; `--provider`/`--model` for a hosted provider |
| Fixtures | The three synthetic packages under `examples/` |
| Related | [EVALUATION](EVALUATION.md), [TEST_PLAN](TEST_PLAN.md), [SRS NFR-07](SRS.md#nfr-07--latency-and-throughput) |

Latency numbers are **environment-specific**. This document therefore states the methodology and a
skeleton first, and quotes the committed smoke run only as an explicitly labelled, non-normative
example.

## 1. What the benchmark measures

For each example package (quotation, invoice, purchase-order), the runner executes the deterministic
pipeline stages and records wall-clock latency per iteration:

| Stage | Measured work |
| --- | --- |
| `parse` | `parse_ddsp()` on the package bytes (ZIP read, XML/XSD mapping, sample extraction) |
| `plan` | `TemplatePlanner.plan()` with the selected provider. With `mock` this is prompt assembly + the deterministic heuristic + sanitisation + mapping report; it is **not** an LLM latency measurement |
| `validate` | `ValidationEngine.validate()` with sample data (V1–V4; V5 is a constant check) |
| `compile` | `GenericDocxCompiler.compile()` including ZIP normalisation and package inspection |

Not measured: HTTP overhead, JSON serialisation of API responses, artifact storage, preview rendering,
SQLite writes, concurrent load, cold-start import time. Those are outside the runner's scope.

## 2. How to run

```bash
make bench
# equivalent to:
python benchmarks/run_benchmarks.py --runs 100
```

Options (from the runner's argparse):

| Option | Default | Meaning |
| --- | --- | --- |
| `--runs N` | `100` | Iterations per example per stage |
| `--provider` | `mock` | Provider passed to the planner |
| `--model` | `None` | Model identifier for a hosted provider |
| `--output PATH` | `benchmarks/results.json` | Where to write JSON |
| `--json` | off | Print the full JSON payload to stdout instead of the table |

Hosted-provider example (requires credentials; results are not comparable with the mock):

```bash
python benchmarks/run_benchmarks.py --runs 20 --provider openai --model gpt-4o-mini
```

The runner writes JSON even when printing a table. The JSON payload contains:

```text
generated_by, python, platform, runs_per_example, provider, model,
aggregate: { parse, plan, validate, compile } -> Stats,
per_example: { quotation, invoice, purchase-order } -> { stage -> Stats }
```

`Stats` = `{name, runs, min_ms, mean_ms, p50_ms, p95_ms, max_ms, budget_ms}`. Budgets are displayed for
`parse` (2000 ms) and `compile` (5000 ms); the `within_budget` property exists on `Stats` but the
runner prints the budget column rather than failing on it. Other stages have no budget.

## 3. Methodology

1. **Fixtures are fixed.** The three synthetic packages and their prompts are read from `examples/`.
   They are regenerated deterministically by `scripts/build_examples.py`.
2. **Warm-up is implicit.** The runner parses and plans once per example before the timed loop. There
   is no explicit warm-up iterations beyond that, and no process isolation between stages.
3. **Timing** uses `time.perf_counter()` around each call. Each iteration re-parses the package and
   re-runs the planner; validation and compilation reuse the document produced before the loop.
4. **Percentiles** are computed by linear interpolation over the sorted samples:
   `position = (n - 1) × fraction`, interpolating between the two nearest samples. `p50` and `p95` are
   therefore exact for the sample, not histogram estimates.
5. **Per-example statistics** (`per_example.*`) are computed over all runs for that stage and example.
6. **Aggregate statistics** are computed over the three **per-example p95 values** (one per example),
   not over all `3 × runs` samples. This is what the current code does; it makes the aggregate a
   summary of worst-case behaviour per fixture, with only three data points. Do not interpret the
   aggregate `runs` field (`3`) as the iteration count; read `runs_per_example` for that.
7. **Throughput is not computed** by the runner. Derive it manually only if needed:
   `1000 / mean_ms` calls per second per stage, single-threaded, excluding overheads listed in §1.

### 3.1 Reproducibility checklist

Record with any published number:

- command line and `runs_per_example`;
- `python` and `platform` from the JSON;
- provider and model;
- machine class (CPU, memory), because the runner does not capture it;
- commit hash;
- whether the machine was otherwise idle.

## 4. Results

### 4.1 Reference run (100 runs)

Not yet produced in this repository. Fill the table from `benchmarks/results.json` after running
`make bench`, and state the machine and commit.

| Stage | p50 (ms) | p95 (ms) | max (ms) | Budget (ms) | Within budget |
| --- | --- | --- | --- | --- | --- |
| parse | TBD | TBD | TBD | 2000 | TBD |
| plan (mock) | TBD | TBD | TBD | — | — |
| validate | TBD | TBD | TBD | — | — |
| compile | TBD | TBD | TBD | 5000 | TBD |

Per-example breakdown (fill from `per_example`):

| Example | parse p95 | plan p95 | validate p95 | compile p95 |
| --- | --- | --- | --- | --- |
| quotation | TBD | TBD | TBD | TBD |
| invoice | TBD | TBD | TBD | TBD |
| purchase-order | TBD | TBD | TBD | TBD |

Hosted-provider plan latency (separate table because it includes network and provider variance):

| Provider / model | Runs | p50 (ms) | p95 (ms) | Error rate | Commit |
| --- | --- | --- | --- | --- | --- |
| TBD | TBD | TBD | TBD | TBD | TBD |

### 4.2 Committed smoke run (non-normative)

`benchmarks/results.json` currently contains a short smoke run produced on the development machine:
`runs_per_example = 5`, `provider = mock`, Python 3.12.3, Linux 6.8 (x86_64). It is useful to confirm
the runner works and to give an order of magnitude, but it is **not** the 100-run benchmark and its
aggregate is computed over three p95 values (§3 item 6).

| Stage | p50 (ms) | p95 (ms) | max (ms) | Budget (ms) |
| --- | --- | --- | --- | --- |
| parse | 2.46 | 5.12 | 5.42 | 2000 |
| plan (mock) | 45.00 | 54.22 | 55.25 | — |
| validate | 2.46 | 2.73 | 2.76 | — |
| compile | 76.91 | 94.68 | 96.66 | 5000 |

Reading it: on that machine the deterministic stages are fast (single-digit milliseconds for parse and
validation; tens of milliseconds for compilation), and the mock planner spends most of its ~45 ms on
prompt assembly, heuristic layout and the mapping report. These values say nothing about hosted LLM
latency or about a different machine.

## 5. Interpretation rules

- **Never compare across machines** without stating the environment; absolute milliseconds are not a
  product claim.
- **`plan (mock)` is a baseline, not an AI metric.** For AI latency, use the hosted-provider table with
  the model identifier and error rate.
- **Budgets are guard rails**, not service-level objectives. A budget breach is worth investigating;
  passing it is not evidence of good performance.
- **A single run is an anecdote.** Publish p50/p95 with the number of runs and the commit.
- **Do not infer correctness from speed.** A fast compiler that emits invalid packages fails the
  validator and the golden tests, not the benchmark.

## 6. Known limitations

1. Aggregate p50/p95 are computed over per-example p95 values, not over all samples (§3.6).
2. No warm-up phase and no process isolation; JIT/import caching and GC can affect the first runs.
3. Only three small synthetic fixtures; large schemas, deep repeats and image-heavy documents are not
   represented.
4. No concurrency or throughput test; the API's threadpool and SQLite locking are not exercised.
5. Memory usage is not measured.
6. The runner's sys.path manipulation assumes the editable install is present; a clean-checkout run
   must install dependencies first.
7. Hosted-provider measurements include network variance and provider throttling; they are not
   comparable between runs without the model version and time window.
8. `budget_ms` values (2000/5000) are hard-coded in the runner, not product requirements.

## 7. Reporting template

When adding results to a PR or release note, use:

```text
command:      python benchmarks/run_benchmarks.py --runs 100 [--provider ... --model ...]
commit:       <sha>
environment:  <CPU / RAM / OS / Python>
provider:     <mock | provider/model>
results:      parse p95=<ms>, plan p95=<ms>, validate p95=<ms>, compile p95=<ms>
budgets:      parse 2000 ms (pass/fail), compile 5000 ms (pass/fail)
caveats:      <any of §6 that apply>
artifact:     benchmarks/results.json (or path)
```
