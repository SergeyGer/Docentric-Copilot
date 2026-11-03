# Live multi-provider evaluation

Generated 2026-11-03T16:47:01.907032Z by `benchmarks/live_evaluation.py`.

Costs are estimates from the versioned price table `2026-11-03` (as of 2026-11-03). `observed` means the provider reported token usage and the model has a published price; `estimated` means a documented proxy rate was used; `unavailable` means neither exists, which is **not** the same as free.

## Run metadata

- Dataset: `benchmarks/live_cases.json` (20 cases, hash `d0bb43f6e4c6a54e`)
- Repeats per case and provider: 2
- Repair attempts per plan: 2 (max output 32000 tokens, timeout 180s)
- Compact mode: auto (version v2)
- Pricing as of 2026-11-03 (table `2026-11-03`)
- Providers: openai:gpt-6-sol, anthropic:claude-sonnet-5-5, gemini:gemini-3.6-flash

## Budget guard

- Cap: $5.000000
- Known spend (published prices): $2.947912
- Estimated spend (proxy rates): $0.132170
- Total (known + estimated): $3.080082
- Unknown-cost runs: 2
- Allow unpriced: yes
- Aborted early: no

## Provider summary

| Provider | Model | Runs | Planned | Valid | Precision | Recall | Coverage | Validation | Compile | p50 | p95 | Cost | Cost/valid | Cost status |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| openai | gpt-6-sol | 40 | 40 | 40 | 0.259 | 1.000 | 0.711 | 100% | 100% | 16570 ms | 24301 ms | $1.235794 (observed) | $0.030895 (observed) | observed |
| anthropic | claude-sonnet-5-5 | 40 | 40 | 40 | 0.268 | 1.000 | 0.684 | 100% | 100% | 12186 ms | 20215 ms | $1.712118 (observed) | $0.042803 (observed) | observed |
| gemini | gemini-3.6-flash | 40 | 38 | 38 | 0.187 | 1.000 | 0.712 | 100% | 100% | 4080 ms | 8628 ms | $0.132170 (estimated) | $0.003478 (estimated) | estimated |

Recommendation: **openai**

Quality first (weighted precision, recall and coverage, gated by validation), then cost per valid template, then p50 latency. Estimated proxy costs count as budget numbers but keep their status; unavailable costs sort last.

## Error taxonomy

Codes: api_error, quota, timeout, truncated, schema_invalid, binding_invalid, validation_failed, compilation_failed, harness_error.

| Provider | api_error | quota | timeout | truncated | schema_invalid | binding_invalid | validation_failed | compilation_failed | harness_error |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| openai | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| anthropic | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| gemini | 0 | 0 | 0 | 0 | 2 | 0 | 0 | 0 | 0 |
| **total** | 0 | 0 | 0 | 0 | 2 | 0 | 0 | 0 | 0 |

## Per-case results

| Case | Repeat | Provider | Precision | Recall | Coverage | Validation | Compiled | Latency | Cost | Error |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| flat-company-identity | 1 | openai:gpt-6-sol | 0.167 | 1.000 | 1.000 | pass | yes | 13693 ms | $0.026010 (observed) |  |
| flat-company-identity | 1 | anthropic:claude-sonnet-5-5 | 0.400 | 1.000 | 1.000 | pass | yes | 4463 ms | $0.027910 (observed) |  |
| flat-company-identity | 1 | gemini:gemini-3.6-flash | 0.074 | 1.000 | 1.000 | pass | yes | 4197 ms | $0.004004 (estimated) |  |
| flat-document-identifiers | 1 | openai:gpt-6-sol | 0.750 | 1.000 | 1.000 | pass | yes | 6496 ms | $0.016060 (observed) |  |
| flat-document-identifiers | 1 | anthropic:claude-sonnet-5-5 | 1.000 | 1.000 | 1.000 | pass | yes | 4839 ms | $0.027618 (observed) |  |
| flat-document-identifiers | 1 | gemini:gemini-3.6-flash | 0.107 | 1.000 | 1.000 | pass | yes | 4212 ms | $0.004056 (estimated) |  |
| flat-customer-details | 1 | openai:gpt-6-sol | 0.600 | 1.000 | 1.000 | pass | yes | 19886 ms | $0.018300 (observed) |  |
| flat-customer-details | 1 | anthropic:claude-sonnet-5-5 | 0.750 | 1.000 | 1.000 | pass | yes | 4679 ms | $0.028564 (observed) |  |
| flat-customer-details | 1 | gemini:gemini-3.6-flash | 0.130 | 1.000 | 0.667 | pass | yes | 3744 ms | $0.003359 (estimated) |  |
| flat-quotation-owner-terms | 1 | openai:gpt-6-sol | 0.235 | 1.000 | 0.750 | pass | yes | 17128 ms | $0.032138 (observed) |  |
| flat-quotation-owner-terms | 1 | anthropic:claude-sonnet-5-5 | 0.667 | 1.000 | 0.750 | pass | yes | 5552 ms | $0.030170 (observed) |  |
| flat-quotation-owner-terms | 1 | gemini:gemini-3.6-flash | 0.148 | 1.000 | 0.750 | pass | yes | 4144 ms | $0.004078 (estimated) |  |
| repeat-quotation-lines | 1 | openai:gpt-6-sol | 0.278 | 1.000 | 1.000 | pass | yes | 14163 ms | $0.031386 (observed) |  |
| repeat-quotation-lines | 1 | anthropic:claude-sonnet-5-5 | 0.417 | 1.000 | 1.000 | pass | yes | 7822 ms | $0.034954 (observed) |  |
| repeat-quotation-lines | 1 | gemini:gemini-3.6-flash | 0.192 | 1.000 | 1.000 | pass | yes | 4004 ms | $0.003728 (estimated) |  |
| repeat-invoice-services | 1 | openai:gpt-6-sol | 0.238 | 1.000 | 0.800 | pass | yes | 15870 ms | $0.033548 (observed) |  |
| repeat-invoice-services | 1 | anthropic:claude-sonnet-5-5 | 0.227 | 1.000 | 0.800 | pass | yes | 12040 ms | $0.044350 (observed) |  |
| repeat-invoice-services | 1 | gemini:gemini-3.6-flash | 0.217 | 1.000 | 0.800 | pass | yes | 6571 ms | $0.003189 (estimated) |  |
| repeat-purchase-order-lines | 1 | openai:gpt-6-sol | 0.312 | 1.000 | 1.000 | pass | yes | 14779 ms | $0.031102 (observed) |  |
| repeat-purchase-order-lines | 1 | anthropic:claude-sonnet-5-5 | 0.312 | 1.000 | 1.000 | pass | yes | 10163 ms | $0.039712 (observed) |  |
| repeat-purchase-order-lines | 1 | gemini:gemini-3.6-flash | 0.294 | 1.000 | 1.000 | pass | yes | 2906 ms | $0.002523 (estimated) |  |
| multiline-invoice-items | 1 | openai:gpt-6-sol | 0.174 | 1.000 | 1.000 | pass | yes | 21609 ms | $0.036466 (observed) |  |
| multiline-invoice-items | 1 | anthropic:claude-sonnet-5-5 | 0.174 | 1.000 | 1.000 | pass | yes | 13899 ms | $0.047996 (observed) |  |
| multiline-invoice-items | 1 | gemini:gemini-3.6-flash | 0.174 | 1.000 | 1.000 | pass | yes | 3568 ms | $0.003363 (estimated) |  |
| mixed-purchase-order | 1 | openai:gpt-6-sol | 0.533 | 1.000 | 1.000 | pass | yes | 13599 ms | $0.028800 (observed) |  |
| mixed-purchase-order | 1 | anthropic:claude-sonnet-5-5 | 0.533 | 1.000 | 0.889 | pass | yes | 12449 ms | $0.042816 (observed) |  |
| mixed-purchase-order | 1 | gemini:gemini-3.6-flash | 0.471 | 1.000 | 1.000 | pass | yes | 6058 ms | $0.002614 (estimated) |  |
| conditional-eu-vat-notice | 1 | openai:gpt-6-sol | 0.043 | 1.000 | 1.000 | pass | yes | 20057 ms | $0.038782 (observed) |  |
| conditional-eu-vat-notice | 1 | anthropic:claude-sonnet-5-5 | 0.037 | 1.000 | 1.000 | pass | yes | 14872 ms | $0.050762 (observed) |  |
| conditional-eu-vat-notice | 1 | gemini:gemini-3.6-flash | 0.037 | 1.000 | 1.000 | pass | yes | 3698 ms | $0.003419 (estimated) |  |
| conditional-reverse-charge | 1 | openai:gpt-6-sol | 0.083 | 1.000 | 0.000 | pass | yes | 18246 ms | $0.036248 (observed) |  |
| conditional-reverse-charge | 1 | anthropic:claude-sonnet-5-5 | 0.083 | 1.000 | 0.000 | pass | yes | 13671 ms | $0.047712 (observed) |  |
| conditional-reverse-charge | 1 | gemini:gemini-3.6-flash | 0.083 | 1.000 | 0.000 | pass | yes | 7101 ms | $0.003423 (estimated) |  |
| conditional-rush-notice | 1 | openai:gpt-6-sol | 0.056 | 1.000 | 0.000 | pass | yes | 18071 ms | $0.033310 (observed) |  |
| conditional-rush-notice | 1 | anthropic:claude-sonnet-5-5 | 0.056 | 1.000 | 0.000 | pass | yes | 10930 ms | $0.041648 (observed) |  |
| conditional-rush-notice | 1 | gemini:gemini-3.6-flash | 0.056 | 1.000 | 0.000 | pass | yes | 6652 ms | $0.002995 (estimated) |  |
| nested-service-tasks | 1 | openai:gpt-6-sol | 0.389 | 1.000 | 0.333 | pass | yes | 16014 ms | $0.029792 (observed) |  |
| nested-service-tasks | 1 | anthropic:claude-sonnet-5-5 | 0.389 | 1.000 | 0.333 | pass | yes | 18004 ms | $0.051700 (observed) |  |
| nested-service-tasks | 1 | gemini:gemini-3.6-flash | 0.333 | 1.000 | 0.333 | pass | yes | 2771 ms | $0.002754 (estimated) |  |
| nested-task-effort | 1 | openai:gpt-6-sol | 0.286 | 1.000 | 0.200 | pass | yes | 16305 ms | $0.031840 (observed) |  |
| nested-task-effort | 1 | anthropic:claude-sonnet-5-5 | 0.333 | 1.000 | 0.000 | pass | yes | 13248 ms | $0.043136 (observed) |  |
| nested-task-effort | 1 | gemini:gemini-3.6-flash | N/A | N/A | N/A | fail | no | 9173 ms | N/A | Invalid compact IR at $.s[0].b[7]: expected a block array whose first item is one of "h", "p", "img", "tbl", "if", "rep" |
| long-table-order-lines | 1 | openai:gpt-6-sol | 0.542 | 1.000 | 0.545 | pass | yes | 23862 ms | $0.039656 (observed) |  |
| long-table-order-lines | 1 | anthropic:claude-sonnet-5-5 | 0.542 | 1.000 | 0.545 | pass | yes | 12213 ms | $0.044928 (observed) |  |
| long-table-order-lines | 1 | gemini:gemini-3.6-flash | 0.542 | 1.000 | 0.545 | pass | yes | 2908 ms | $0.002966 (estimated) |  |
| long-table-commercial-columns | 1 | openai:gpt-6-sol | 0.476 | 1.000 | 0.667 | pass | yes | 44060 ms | $0.038550 (observed) |  |
| long-table-commercial-columns | 1 | anthropic:claude-sonnet-5-5 | 0.476 | 1.000 | 0.667 | pass | yes | 16613 ms | $0.050450 (observed) |  |
| long-table-commercial-columns | 1 | gemini:gemini-3.6-flash | 0.476 | 1.000 | 0.667 | pass | yes | 3136 ms | $0.002852 (estimated) |  |
| multilingual-company-de | 1 | openai:gpt-6-sol | 0.105 | 1.000 | 1.000 | pass | yes | 19248 ms | $0.036110 (observed) |  |
| multilingual-company-de | 1 | anthropic:claude-sonnet-5-5 | 0.077 | 1.000 | 1.000 | pass | yes | 19724 ms | $0.057400 (observed) |  |
| multilingual-company-de | 1 | gemini:gemini-3.6-flash | 0.074 | 1.000 | 1.000 | pass | yes | 3807 ms | $0.003935 (estimated) |  |
| multilingual-invoice-fr | 1 | openai:gpt-6-sol | 0.750 | 1.000 | 0.500 | pass | yes | 8466 ms | $0.017912 (observed) |  |
| multilingual-invoice-fr | 1 | anthropic:claude-sonnet-5-5 | 0.750 | 1.000 | 0.500 | pass | yes | 6735 ms | $0.030466 (observed) |  |
| multilingual-invoice-fr | 1 | gemini:gemini-3.6-flash | 0.136 | 1.000 | 0.500 | pass | yes | 3394 ms | $0.003175 (estimated) |  |
| missing-field | 1 | openai:gpt-6-sol | N/A | N/A | 0.000 | pass | yes | 12895 ms | $0.025452 (observed) |  |
| missing-field | 1 | anthropic:claude-sonnet-5-5 | N/A | N/A | 0.000 | pass | yes | 18877 ms | $0.055946 (observed) |  |
| missing-field | 1 | gemini:gemini-3.6-flash | N/A | N/A | 0.000 | pass | yes | 4178 ms | $0.003972 (estimated) |  |
| ambiguous-address | 1 | openai:gpt-6-sol | 0.091 | 1.000 | 1.000 | pass | yes | 18953 ms | $0.035658 (observed) |  |
| ambiguous-address | 1 | anthropic:claude-sonnet-5-5 | 0.074 | 1.000 | 1.000 | pass | yes | 31373 ms | $0.052336 (observed) |  |
| ambiguous-address | 1 | gemini:gemini-3.6-flash | 0.074 | 1.000 | 1.000 | pass | yes | 4015 ms | $0.003973 (estimated) |  |
| flat-company-identity | 2 | openai:gpt-6-sol | 0.143 | 1.000 | 1.000 | pass | yes | 15127 ms | $0.029760 (observed) |  |
| flat-company-identity | 2 | anthropic:claude-sonnet-5-5 | 0.087 | 1.000 | 1.000 | pass | yes | 12159 ms | $0.045350 (observed) |  |
| flat-company-identity | 2 | gemini:gemini-3.6-flash | 0.074 | 1.000 | 1.000 | pass | yes | 3946 ms | $0.003872 (estimated) |  |
| flat-document-identifiers | 2 | openai:gpt-6-sol | 0.750 | 1.000 | 1.000 | pass | yes | 5532 ms | $0.014220 (observed) |  |
| flat-document-identifiers | 2 | anthropic:claude-sonnet-5-5 | 1.000 | 1.000 | 1.000 | pass | yes | 4752 ms | $0.027748 (observed) |  |
| flat-document-identifiers | 2 | gemini:gemini-3.6-flash | 0.111 | 1.000 | 1.000 | pass | yes | 8549 ms | $0.004451 (estimated) |  |
| flat-customer-details | 2 | openai:gpt-6-sol | 0.158 | 1.000 | 1.000 | pass | yes | 17321 ms | $0.030774 (observed) |  |
| flat-customer-details | 2 | anthropic:claude-sonnet-5-5 | 0.750 | 1.000 | 1.000 | pass | yes | 4960 ms | $0.027984 (observed) |  |
| flat-customer-details | 2 | gemini:gemini-3.6-flash | 0.130 | 1.000 | 0.667 | pass | yes | 3773 ms | $0.003336 (estimated) |  |
| flat-quotation-owner-terms | 2 | openai:gpt-6-sol | 0.444 | 1.000 | 0.750 | pass | yes | 12355 ms | $0.022768 (observed) |  |
| flat-quotation-owner-terms | 2 | anthropic:claude-sonnet-5-5 | 0.667 | 1.000 | 0.750 | pass | yes | 6499 ms | $0.032530 (observed) |  |
| flat-quotation-owner-terms | 2 | gemini:gemini-3.6-flash | 0.154 | 1.000 | 0.750 | pass | yes | 7505 ms | $0.003864 (estimated) |  |
| repeat-quotation-lines | 2 | openai:gpt-6-sol | 0.263 | 1.000 | 1.000 | pass | yes | 15813 ms | $0.031656 (observed) |  |
| repeat-quotation-lines | 2 | anthropic:claude-sonnet-5-5 | 0.385 | 1.000 | 1.000 | pass | yes | 7370 ms | $0.034184 (observed) |  |
| repeat-quotation-lines | 2 | gemini:gemini-3.6-flash | 0.185 | 1.000 | 1.000 | pass | yes | 3897 ms | $0.003901 (estimated) |  |
| repeat-invoice-services | 2 | openai:gpt-6-sol | 0.227 | 1.000 | 0.800 | pass | yes | 16775 ms | $0.036398 (observed) |  |
| repeat-invoice-services | 2 | anthropic:claude-sonnet-5-5 | 0.227 | 1.000 | 0.800 | pass | yes | 11743 ms | $0.043980 (observed) |  |
| repeat-invoice-services | 2 | gemini:gemini-3.6-flash | 0.217 | 1.000 | 0.800 | pass | yes | 3518 ms | $0.003364 (estimated) |  |
| repeat-purchase-order-lines | 2 | openai:gpt-6-sol | 0.312 | 1.000 | 1.000 | pass | yes | 17138 ms | $0.034082 (observed) |  |
| repeat-purchase-order-lines | 2 | anthropic:claude-sonnet-5-5 | 0.312 | 1.000 | 1.000 | pass | yes | 9568 ms | $0.039142 (observed) |  |
| repeat-purchase-order-lines | 2 | gemini:gemini-3.6-flash | 0.294 | 1.000 | 1.000 | pass | yes | 2637 ms | $0.002471 (estimated) |  |
| multiline-invoice-items | 2 | openai:gpt-6-sol | 0.174 | 1.000 | 1.000 | pass | yes | 17737 ms | $0.037136 (observed) |  |
| multiline-invoice-items | 2 | anthropic:claude-sonnet-5-5 | 0.174 | 1.000 | 1.000 | pass | yes | 12956 ms | $0.046086 (observed) |  |
| multiline-invoice-items | 2 | gemini:gemini-3.6-flash | 0.174 | 1.000 | 1.000 | pass | yes | 3563 ms | $0.003348 (estimated) |  |
| mixed-purchase-order | 2 | openai:gpt-6-sol | 0.533 | 1.000 | 1.000 | pass | yes | 13888 ms | $0.029150 (observed) |  |
| mixed-purchase-order | 2 | anthropic:claude-sonnet-5-5 | 0.615 | 1.000 | 0.889 | pass | yes | 10436 ms | $0.040466 (observed) |  |
| mixed-purchase-order | 2 | gemini:gemini-3.6-flash | 0.500 | 1.000 | 1.000 | pass | yes | 5720 ms | $0.002517 (estimated) |  |
| conditional-eu-vat-notice | 2 | openai:gpt-6-sol | 0.043 | 1.000 | 1.000 | pass | yes | 18055 ms | $0.037582 (observed) |  |
| conditional-eu-vat-notice | 2 | anthropic:claude-sonnet-5-5 | 0.037 | 1.000 | 1.000 | pass | yes | 14021 ms | $0.048442 (observed) |  |
| conditional-eu-vat-notice | 2 | gemini:gemini-3.6-flash | 0.037 | 1.000 | 1.000 | pass | yes | 4849 ms | $0.004319 (estimated) |  |
| conditional-reverse-charge | 2 | openai:gpt-6-sol | 0.083 | 1.000 | 0.000 | pass | yes | 17103 ms | $0.035978 (observed) |  |
| conditional-reverse-charge | 2 | anthropic:claude-sonnet-5-5 | 0.083 | 1.000 | 0.000 | pass | yes | 12565 ms | $0.044562 (observed) |  |
| conditional-reverse-charge | 2 | gemini:gemini-3.6-flash | 0.087 | 1.000 | 0.000 | pass | yes | 7553 ms | $0.003182 (estimated) |  |
| conditional-rush-notice | 2 | openai:gpt-6-sol | 0.056 | 1.000 | 0.000 | pass | yes | 13569 ms | $0.029900 (observed) |  |
| conditional-rush-notice | 2 | anthropic:claude-sonnet-5-5 | 0.056 | 1.000 | 0.000 | pass | yes | 10700 ms | $0.041408 (observed) |  |
| conditional-rush-notice | 2 | gemini:gemini-3.6-flash | 0.042 | 1.000 | 0.000 | pass | yes | 6701 ms | $0.003572 (estimated) |  |
| nested-service-tasks | 2 | openai:gpt-6-sol | 0.389 | 1.000 | 0.333 | pass | yes | 16733 ms | $0.033562 (observed) |  |
| nested-service-tasks | 2 | anthropic:claude-sonnet-5-5 | 0.389 | 1.000 | 0.333 | pass | yes | 17296 ms | $0.050340 (observed) |  |
| nested-service-tasks | 2 | gemini:gemini-3.6-flash | N/A | N/A | N/A | fail | no | 10012 ms | N/A | Invalid compact IR at $.s[0].b[5]: expected a block array whose first item is one of "h", "p", "img", "tbl", "if", "rep" |
| nested-task-effort | 2 | openai:gpt-6-sol | 0.261 | 1.000 | 0.200 | pass | yes | 15875 ms | $0.032850 (observed) |  |
| nested-task-effort | 2 | anthropic:claude-sonnet-5-5 | 0.333 | 1.000 | 0.000 | pass | yes | 13248 ms | $0.043146 (observed) |  |
| nested-task-effort | 2 | gemini:gemini-3.6-flash | 0.261 | 1.000 | 0.200 | pass | yes | 9214 ms | $0.003037 (estimated) |  |
| long-table-order-lines | 2 | openai:gpt-6-sol | 0.542 | 1.000 | 0.545 | pass | yes | 18386 ms | $0.035896 (observed) |  |
| long-table-order-lines | 2 | anthropic:claude-sonnet-5-5 | 0.542 | 1.000 | 0.500 | pass | yes | 11715 ms | $0.043788 (observed) |  |
| long-table-order-lines | 2 | gemini:gemini-3.6-flash | 0.565 | 1.000 | 0.545 | pass | yes | 2776 ms | $0.002879 (estimated) |  |
| long-table-commercial-columns | 2 | openai:gpt-6-sol | 0.476 | 1.000 | 0.667 | pass | yes | 32650 ms | $0.037120 (observed) |  |
| long-table-commercial-columns | 2 | anthropic:claude-sonnet-5-5 | 0.476 | 1.000 | 0.667 | pass | yes | 19454 ms | $0.055250 (observed) |  |
| long-table-commercial-columns | 2 | gemini:gemini-3.6-flash | 0.526 | 1.000 | 0.667 | pass | yes | 8522 ms | $0.002676 (estimated) |  |
| multilingual-company-de | 2 | openai:gpt-6-sol | 0.105 | 1.000 | 1.000 | pass | yes | 16408 ms | $0.033610 (observed) |  |
| multilingual-company-de | 2 | anthropic:claude-sonnet-5-5 | 0.077 | 1.000 | 1.000 | pass | yes | 19662 ms | $0.057390 (observed) |  |
| multilingual-company-de | 2 | gemini:gemini-3.6-flash | 0.071 | 1.000 | 0.333 | pass | yes | 9075 ms | $0.004841 (estimated) |  |
| multilingual-invoice-fr | 2 | openai:gpt-6-sol | 0.750 | 1.000 | 0.500 | pass | yes | 5089 ms | $0.013762 (observed) |  |
| multilingual-invoice-fr | 2 | anthropic:claude-sonnet-5-5 | 0.750 | 1.000 | 0.500 | pass | yes | 6978 ms | $0.031166 (observed) |  |
| multilingual-invoice-fr | 2 | gemini:gemini-3.6-flash | 0.130 | 1.000 | 0.500 | pass | yes | 3401 ms | $0.003381 (estimated) |  |
| missing-field | 2 | openai:gpt-6-sol | N/A | N/A | 0.000 | pass | yes | 13658 ms | $0.025102 (observed) |  |
| missing-field | 2 | anthropic:claude-sonnet-5-5 | N/A | N/A | 0.000 | pass | yes | 18693 ms | $0.056256 (observed) |  |
| missing-field | 2 | gemini:gemini-3.6-flash | N/A | N/A | 0.000 | pass | yes | 4998 ms | $0.004670 (estimated) |  |
| ambiguous-address | 2 | openai:gpt-6-sol | 0.087 | 1.000 | 1.000 | pass | yes | 17813 ms | $0.037368 (observed) |  |
| ambiguous-address | 2 | anthropic:claude-sonnet-5-5 | 0.077 | 1.000 | 1.000 | pass | yes | 29536 ms | $0.052326 (observed) |  |
| ambiguous-address | 2 | gemini:gemini-3.6-flash | 0.071 | 1.000 | 1.000 | pass | yes | 4880 ms | $0.004111 (estimated) |  |

## Caveats

- 2 repeats per case and provider: these are observations, not a statistically significant benchmark.
- Latency includes prompt assembly, the provider call and deterministic repair, but not HTTP transport to this harness.
- The recommendation is lexicographic: quality first, then cost per valid template, then p50 latency. Estimated proxy costs count as a budget number but keep their status in the report.
- The missing-field case has no expected binding set, so it is excluded from precision/recall; its requirement coverage is still reported.
- Per-run traces are written under `docs/media/runs/` (git-ignored) and contain no prompt text.

