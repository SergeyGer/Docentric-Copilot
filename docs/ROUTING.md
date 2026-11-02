# Adaptive model routing

Status: implemented for the deterministic baseline; no live provider benchmark has been run yet.

## What the router decides

`POST /api/v1/templates/route` classifies a brief from **observable facts** — the schema, the parsed
requirements and the draft mapping review — never from prompt wording alone.

| Complexity | Signals | Tier | Budget |
| --- | --- | --- | --- |
| `simple` | ≤ 4 requirements, no collection | fast | $0.02 |
| `standard` | one collection, typical commercial document | balanced | $0.10 |
| `complex` | several collections, > 8 requirements, depth ≥ 4, conditional logic | advanced | $0.30 |
| `ambiguous` | a binding needs review, or a party-scoped field without a named party | advanced | $0.30, `requires_review: true` |

The tier lists provider **preferences**. If none of them is configured, the router selects the
deterministic `mock` provider and records `fallback_used` with the reason. Routing never bypasses
validation: the validator is the last mandatory gate.

## Why this order

The product brief recommends AI quality and cost work before visual optimisation and AX
compatibility, because it produces reproducible engineering evidence without a licensed runtime.

## Metrics

`benchmarks/run_evaluation.py` reports field-selection precision/recall, requirement coverage,
compilation success, clarification and correction rates. These are measured on the deterministic
baseline with fixed schemas and prompts, so the numbers are reproducible offline.

A live benchmark per model is **not** included yet. It requires provider keys, a fixed model version
and a budget; the harness is tracked in issue #16 and must record the model version next to every
number. Until then, no table in this repository claims a provider comparison.

## Cost and quality reporting

Each plan records provider, model, token usage and cost in the generation metadata (the mock
provider reports zero cost). A dashboard over that data is future work; numbers shown in the UI come
from stored runs, never from illustrative constants.

## Verified live calls

Measured on 2026-11-02 with the bundled quotation package and the same brief:

| Provider | Model | Result | Latency |
| --- | --- | --- | --- |
| Anthropic | `claude-haiku-5-5` | valid IR, 5 confirmed mappings | ~10 s |
| Anthropic | `claude-sonnet-5-5` | valid IR, 5 confirmed mappings | ~17 s |
| OpenAI | `gpt-6-sol` | valid IR, 4 confirmed + 1 missing | ~21 s |
| OpenAI | `gpt-6.1-sol` | valid IR, 4 confirmed + 1 missing | ~33 s |
| OpenAI | `gpt-4.1` | valid IR, 5 confirmed mappings | ~42 s |
| OpenAI | `gpt-4.1-mini` | rejected: invalid date pattern and a malformed table row | — |

The default model in `.env.example` is `gpt-6-sol`. The GPT-4.1 family is being retired and the
cheaper mini variant produced invalid IR; the adapter now also retries with `max_completion_tokens`
and without `temperature`, which the GPT-6 models require. These
numbers are single observations, not a benchmark; the reproducible harness is tracked separately.
