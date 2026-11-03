# Live multi-provider evaluation

Generated 2026-11-03T15:55:17.112432Z by `benchmarks/live_evaluation.py`.

One run per case and provider. Cost is an estimate from the versioned price table `2026-11-03` (as of 2026-11-03); `N/A` means the model has no published price and is **not** a free call.

- Cases: 6 from `benchmarks/live_cases.json`
- Providers: openai:gpt-6-sol, anthropic:claude-sonnet-5-5, gemini:gemini-3.6-flash
- Estimated spend: N/A of $3.000000 cap (unknown-cost runs: 3)
- Aborted early: no
- Repair attempts per plan: 0 (max output 32000 tokens)
- Compact IR mode: auto

## Provider summary

| Provider | Model | Quality | Precision | Recall | Coverage | Validation | Compile | p50 | p95 | Tokens | Cost |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| openai | gpt-6-sol | 0.706 | 0.287 | 1.000 | 0.957 | 100% | 100% | 14517 ms | 15619 ms | 36309 | $0.156330 |
| anthropic | claude-sonnet-5-5 | 0.727 | 0.359 | 1.000 | 0.917 | 100% | 100% | 7005 ms | 12038 ms | 71114 | $0.205828 |
| gemini | gemini-3.6-flash | 0.617 | 0.105 | 1.000 | 0.875 | 100% | 100% | 16766 ms | 17861 ms | 7446 | N/A |

Recommendation: anthropic

Quality first (weighted precision, recall and coverage, gated by validation), then known cost, then p50 latency. Unpriced providers sort after priced ones on the budget criterion.

## Per-case results

| Case | Provider | Precision | Recall | Coverage | Validation | Compiled | Latency | Cost | Error |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| simple-company-identity | openai:gpt-6-sol | 0.500 | 1.000 | 1.000 | pass | yes | 8727 ms | $0.016510 |  |
| simple-company-identity | anthropic:claude-sonnet-5-5 | 0.400 | 1.000 | 1.000 | pass | yes | 5159 ms | $0.029280 |  |
| simple-company-identity | gemini:gemini-3.6-flash | 0.074 | 1.000 | 1.000 | pass | yes | 15228 ms | N/A |  |
| simple-document-identifiers | openai:gpt-6-sol | 0.750 | 1.000 | 1.000 | pass | yes | 7073 ms | $0.015180 |  |
| simple-document-identifiers | anthropic:claude-sonnet-5-5 | 0.750 | 1.000 | 1.000 | pass | yes | 5257 ms | $0.028548 |  |
| simple-document-identifiers | gemini:gemini-3.6-flash | 0.111 | 1.000 | 1.000 | pass | yes | 17983 ms | N/A |  |
| simple-customer-details | openai:gpt-6-sol | 0.158 | 1.000 | 1.000 | pass | yes | 13618 ms | $0.029704 |  |
| simple-customer-details | anthropic:claude-sonnet-5-5 | 0.750 | 1.000 | 1.000 | pass | yes | 4609 ms | $0.027984 |  |
| simple-customer-details | gemini:gemini-3.6-flash | 0.136 | 1.000 | 0.667 | pass | yes | 16766 ms | N/A |  |
| repeat-quotation-lines | openai:gpt-6-sol | 0.294 | 1.000 | 1.000 | pass | yes | 15451 ms | $0.031386 |  |
| repeat-quotation-lines | anthropic:claude-sonnet-5-5 | 0.385 | 1.000 | 1.000 | pass | yes | 8753 ms | $0.034064 |  |
| repeat-quotation-lines | gemini:gemini-3.6-flash | N/A | N/A | N/A | fail | no | 15531 ms | N/A | Invalid compact IR: unknown key(s) at $.sections[0].body[6].align |
| repeat-invoice-services | openai:gpt-6-sol | 0.250 | 1.000 | 0.800 | pass | yes | 15675 ms | $0.032168 |  |
| repeat-invoice-services | anthropic:claude-sonnet-5-5 | 0.227 | 1.000 | 0.800 | pass | yes | 12375 ms | $0.044690 |  |
| repeat-invoice-services | gemini:gemini-3.6-flash | N/A | N/A | N/A | fail | no | 16709 ms | N/A | Invalid compact IR: unknown key(s) at $.sections[0].body[6].align |
| repeat-purchase-order-lines | openai:gpt-6-sol | 0.312 | 1.000 | 1.000 | pass | yes | 15416 ms | $0.031382 |  |
| repeat-purchase-order-lines | anthropic:claude-sonnet-5-5 | 0.312 | 1.000 | 0.833 | pass | yes | 11025 ms | $0.041262 |  |
| repeat-purchase-order-lines | gemini:gemini-3.6-flash | N/A | N/A | N/A | fail | no | 10126 ms | N/A | Invalid compact IR: unknown key(s) at $.sections[0].body[7].align |

## Caveats

- One run per case and provider: these are observations, not a statistically significant benchmark.
- Latency includes prompt assembly, the provider call and deterministic repair, but not HTTP transport to this harness.
- The recommendation is lexicographic: quality first, then known cost, then p50 latency.
- Cases with an empty expected set (the missing-field case) are excluded from precision/recall aggregates because the denominator is zero.
- Per-run traces are written under `docs/media/runs/` (git-ignored) and contain no prompt text.

