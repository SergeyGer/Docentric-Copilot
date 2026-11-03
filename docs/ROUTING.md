# Adaptive model routing

Status: implemented, including an **auto** execution trace and a reduced live multi-provider benchmark
on 2026-11-03. The deterministic validator remains the final gate in every path.

## What the router decides

`POST /api/v1/templates/route` classifies a brief from **observable facts** — the schema, the parsed
requirements and the draft mapping review — never from prompt wording alone.

| Complexity | Signals | Tier | Budget |
| --- | --- | --- | --- |
| `simple` | ≤ 4 requirements, no collection | fast | $0.02 |
| `standard` | one collection, typical commercial document | balanced | $0.10 |
| `complex` | several collections, > 8 requirements, depth ≥ 4, conditional logic | advanced | $0.30 |
| `ambiguous` | a binding needs review, or a party-scoped field without a named party | advanced | $0.30, `requires_review: true` |

The tier lists provider **preferences**. If none of them are configured, the router selects the
deterministic `mock` provider and records `fallback_used` with the reason. Routing never bypasses
validation.

## Auto-routing execution (`routing: "auto"`)

`POST /api/v1/templates/plan` keeps the historical explicit provider by default. Adding
`"routing": "auto"` changes the request to:

1. classify the brief with the existing `classify()`;
2. route against the **configured** providers (keys present, including `mock`);
3. execute the plan with the selected provider and its default model;
4. return a trace comparing the recommendation with what actually ran.

The response gains a `routing` object and leaves the rest of `PlanResponse` unchanged:

| Field | Meaning |
| --- | --- |
| `decision` | Full `RouteDecision`: complexity, recommended provider/model, reasons, tier budget, `requires_review`, `fallback_used` |
| `actual_provider` | Provider that produced the plan (from the generation result, not the request) |
| `actual_model` | Model that produced the plan (the provider's resolved model) |
| `fallback` | The preferred tier was unavailable, including the explicit deterministic baseline |
| `match` | `true` **only** when `decision.provider == actual_provider` |
| `run_id` | Identifier of the trace file and of this execution |
| `started_at` / `finished_at` | UTC timestamps around the provider call |
| `usage` | Token usage and estimated cost; `estimated_cost_usd` is `null` for an unpriced model |

The tier budget is a routing hint. The request's `max_generation_cost_usd` remains the enforced
generation cap; the trace records both (`budget_usd` and `request_budget_usd`).

### Traces

Each auto plan writes a sanitized JSON trace to `docs/media/runs/<run_id>.json` (configurable with
`DC_ROUTING_TRACE_DIR`, empty disables writing). The directory is **git-ignored**; traces are local
run evidence and are never published. A trace contains:

- provider, model, complexity, tier budget and request budget;
- recommendation and execution, `match`, `fallback`;
- timestamps, duration, token usage and the estimated cost with its pricing-table version;
- validation statuses, overall status and `ir_digest`;
- the prompt's character count and SHA-256 digest — **never the prompt text**, the model output or an
  API key. Error messages are redacted.

### Failure semantics

If the routed provider fails, the request returns a `502` with code `routing_provider_failed` and
details containing the recommendation, the executed provider, the `fallback` block, the trace path and
the provider error. The gateway **never silently substitutes `mock`**. The failed trace is still
written with `"status": "failed"`.

`routing: "explicit"` (the default) keeps the previous behaviour: request provider/model, no
`routing` object and no trace file.

## Gemini live support

The Gemini adapter originally sent the converted IR schema with `maxItems` limits. Gemini 3.x rejects
sufficiently large array limits with a bare `400 INVALID_ARGUMENT`; the threshold depends on the whole
schema and is undocumented. The adapter now:

1. drops `maxItems` from the converted schema (array bounds remain enforced by the IR model and the
   validator);
2. merges the block union into one permissive object schema while keeping inline runs (`TextRun` /
   `FieldBinding`) discriminable, and keeps `kind` required;
3. sets `thinkingConfig.thinkingLevel = "minimal"` for `gemini-3*` so thinking tokens do not consume
   the completion budget;
4. retries **once** without `responseSchema`, `temperature` and `thinkingConfig` when Gemini still
   answers a `400` (the same pragmatic fallback used by the OpenAI and Anthropic adapters), keeping
   JSON mode on;
5. reports `MAX_TOKENS` as an explicit `output_truncated` error instead of returning partial JSON.

Verified with a live plan on 2026-11-03 using `gemini-3.1-flash-lite`: valid IR, structural, semantic,
logical and visual validation passed, 1 214 prompt + 375 completion tokens, 4.1 s, estimated
$0.000866. `gemini-3-flash-preview` is the preferred cheap model and its 400 was the trigger for the
schema fix, but the free-tier cap (20 requests/day per model) was exhausted before a post-fix run, so
it is **not** claimed as verified. `.env.example` therefore defaults to `gemini-3.1-flash-lite`; raise
it to `gemini-3-flash-preview` deliberately after checking the quota and re-running a live plan.

## Recommendation function

`docentric_copilot.evaluation.reporting.recommend_provider` implements an explicit lexicographic
policy:

1. **Quality first** — `quality_score` weights field precision 0.4, recall 0.4 and requirement coverage
   0.2, then multiplies by the validation pass rate; a provider with no validating plan scores 0 and
   is never recommended.
2. **Then budget** — lower estimated cost for the measured runs wins; a provider with no published
   price sorts **after** every priced provider because it cannot be compared on budget.
3. **Then latency** — lower p50 latency breaks the remaining tie.

The same function is used by the live benchmark and documented in [EVALUATION](EVALUATION.md). It is a
deterministic policy over measured metrics, not a learned model.

## Verified live calls

Measured on 2026-11-02 with the bundled quotation package and the same brief:

| Provider | Model | Result | Latency |
| --- | --- | --- | --- |
| Anthropic | `claude-haiku-5-5` | valid IR, 5 confirmed mappings | ~10 s |
| Anthropic | `claude-sonnet-5-5` | valid IR, 5 confirmed mappings | ~17 s |
| OpenAI | `gpt-6-sol` | valid IR, 4 confirmed + 1 missing | ~21 s |
| OpenAI | `gpt-6.1-sol` | valid IR, 4 confirmed + 1 missing | ~33 s |
| OpenAI | `gpt-4.1` | valid IR, 5 confirmed mappings | ~42 s |
| Google Gemini | `gemini-3.1-flash-lite` | valid IR, all validation gates passed | ~4 s |
| OpenAI | `gpt-4.1-mini` | rejected: invalid date pattern and a malformed table row | — |

The default model in `.env.example` is `gpt-6-sol`. The GPT-4.1 family is being retired and the
cheaper mini variant produced invalid IR. These are single observations, not the benchmark; the
reproducible harness and its measured numbers live in [EVALUATION](EVALUATION.md).

## Cost reporting

Every plan records provider, model, token usage and cost in the generation metadata. Prices come from
the versioned table in [PRICING](PRICING.md); an unpriced model is `N/A`, never `$0.00`. The mock
provider reports a real zero.
