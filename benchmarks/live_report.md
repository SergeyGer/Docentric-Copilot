# Live multi-provider evaluation

Generated 2026-11-03T08:52:39.889116Z by `benchmarks/live_evaluation.py`.

One run per case and provider. Cost is an estimate from the versioned price table `2026-11-03` (as of 2026-11-03); `N/A` means the model has no published price and is **not** a free call.

- Cases: 6 from `benchmarks/live_cases.json`
- Providers: openai:gpt-6-sol, anthropic:claude-sonnet-5-5, gemini:gemini-3.1-flash-lite
- Estimated spend: $0.478798 of $2.500000 cap (unknown-cost runs: 0)
- Aborted early: no
- Repair attempts per plan: 1 (max output 16000 tokens)

## Provider summary

| Provider | Model | Quality | Precision | Recall | Coverage | Validation | Compile | p50 | p95 | Tokens | Cost |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| openai | gpt-6-sol | 0.617 | 0.115 | 1.000 | 0.857 | 100% | 100% | 19002 ms | 21102 ms | 40919 | $0.199774 |
| anthropic | claude-sonnet-5-5 | 0.616 | 0.110 | 1.000 | 0.857 | 100% | 100% | 14236 ms | 30340 ms | 78940 | $0.279024 |
| gemini | gemini-3.1-flash-lite | 0.000 | N/A | N/A | N/A | 0% | 0% | N/A | N/A | 0 | N/A |

Recommendation: openai

Quality first (weighted precision, recall and coverage, gated by validation), then known cost, then p50 latency. Unpriced providers sort after priced ones on the budget criterion.

## Per-case results

| Case | Provider | Precision | Recall | Coverage | Validation | Compiled | Latency | Cost | Error |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| simple-company-identity | openai:gpt-6-sol | 0.105 | 1.000 | 1.000 | pass | yes | 19402 ms | $0.035580 |  |
| simple-company-identity | anthropic:claude-sonnet-5-5 | 0.143 | 1.000 | 1.000 | pass | yes | 7435 ms | $0.033790 |  |
| simple-company-identity | gemini:gemini-3.1-flash-lite | N/A | N/A | N/A | fail | no | 41376 ms | N/A | The model stopped before finishing the document |
| repeat-quotation-lines | openai:gpt-6-sol | 0.278 | 1.000 | 1.000 | pass | yes | 14298 ms | $0.024746 |  |
| repeat-quotation-lines | anthropic:claude-sonnet-5-5 | 0.556 | 1.000 | 1.000 | pass | yes | 6159 ms | $0.031364 |  |
| repeat-quotation-lines | gemini:gemini-3.1-flash-lite | N/A | N/A | N/A | fail | no | 28421 ms | N/A | The model stopped before finishing the document |
| conditional-eu-vat-notice | openai:gpt-6-sol | 0.042 | 1.000 | 1.000 | pass | yes | 20704 ms | $0.038702 |  |
| conditional-eu-vat-notice | anthropic:claude-sonnet-5-5 | 0.037 | 1.000 | 1.000 | pass | yes | 15030 ms | $0.051612 |  |
| conditional-eu-vat-notice | gemini:gemini-3.1-flash-lite | N/A | N/A | N/A | fail | no | 20806 ms | N/A | Provider output does not satisfy the required schema |
| ambiguous-address | openai:gpt-6-sol | 0.091 | 1.000 | 1.000 | pass | yes | 21235 ms | $0.037638 |  |
| ambiguous-address | anthropic:claude-sonnet-5-5 | 0.074 | 1.000 | 1.000 | pass | yes | 33521 ms | $0.056716 |  |
| ambiguous-address | gemini:gemini-3.1-flash-lite | N/A | N/A | N/A | fail | no | 30325 ms | N/A | The model stopped before finishing the document |
| missing-field | openai:gpt-6-sol | 0.000 | N/A | 0.000 | pass | yes | 16865 ms | $0.029622 |  |
| missing-field | anthropic:claude-sonnet-5-5 | 0.000 | N/A | 0.000 | pass | yes | 20796 ms | $0.058406 |  |
| missing-field | gemini:gemini-3.1-flash-lite | N/A | N/A | N/A | fail | no | 42933 ms | N/A | Provider output does not satisfy the required schema |
| multiline-invoice-items | openai:gpt-6-sol | 0.182 | 1.000 | 1.000 | pass | yes | 18602 ms | $0.033486 |  |
| multiline-invoice-items | anthropic:claude-sonnet-5-5 | 0.174 | 1.000 | 1.000 | pass | yes | 13441 ms | $0.047136 |  |
| multiline-invoice-items | gemini:gemini-3.1-flash-lite | N/A | N/A | N/A | fail | no | 60167 ms | N/A | The provider did not respond in time |

## Caveats

- One run per case and provider: these are observations, not a statistically significant benchmark.
- Latency includes prompt assembly, the provider call and deterministic repair, but not HTTP transport to this harness.
- The recommendation is lexicographic: quality first, then known cost, then p50 latency.
- Cases with an empty expected set (the missing-field case) are excluded from precision/recall aggregates because the denominator is zero.
- Per-run traces are written under `docs/media/runs/` (git-ignored) and contain no prompt text.

