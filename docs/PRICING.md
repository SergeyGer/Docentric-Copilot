# Pricing policy

| Field | Value |
| --- | --- |
| Table version | `2026-11-03` |
| As of | 2026-11-03 |
| Implementation | [packages/llm-gateway/src/docentric_copilot/llm/pricing.py](../packages/llm-gateway/src/docentric_copilot/llm/pricing.py) |
| Consumers | `POST /api/v1/templates/compare`, `benchmarks/live_evaluation.py`, the web workspace |
| Related | [ROUTING](ROUTING.md), [EVALUATION](EVALUATION.md), [BENCHMARKS](BENCHMARKS.md) |

Costs in this project are **estimates from a versioned static table**, not invoices. Provider prices
change, add context-length or batch tiers, and differ by region. The table records the standard
(non-batch, short-context) list price at the date above so a reported number can be traced back to a
source.

## 1. The rule

> **No published price means `None` / `N/A`, never `$0.00`.**

A missing entry is an absence of information, not a free call. The deterministic `mock` provider is
the only genuinely free provider: its price is `Price(0.0, 0.0)` and it reports `0.0`.

The rule is applied consistently:

| Surface | Unknown price | Mock |
| --- | --- | --- |
| `price_for(model)` | `(None, False)` | `(Price(0, 0), True)` |
| `estimate_cost(...)` | `None` | `0.0` |
| `Usage.estimated_cost_usd` | `null` in JSON | `0.0` |
| `POST /templates/compare` `cost_usd` | `null` | `0.0` |
| `benchmarks/live_evaluation.py` | `N/A`, excluded from the total | `$0.000000` |
| Benchmark `cost_usd` aggregate | `null` / `N/A` if any run is unpriced | `0.0` |
| Web (`formatCostUsd`) | `N/A` | `$0.00` |

A total that mixes known and unknown prices is **N/A** as a whole; the known subtotal is still reported
separately (`known_spend_usd` in the live benchmark) so a partial number is never mistaken for the
full spend.

## 2. Price table (`2026-11-03`)

Values are USD per million tokens. Prefix matching is used, longest prefix wins, so a dated snapshot
such as `gpt-4.1-2025-04-14` resolves through `gpt-4.1`.

| Model prefix | Input / MTok | Output / MTok | Source |
| --- | ---: | ---: | --- |
| `gpt-6-sol` | $2.00 | $10.00 | [OpenAI model page](https://developers.openai.com/api/docs/models/gpt-6-sol) |
| `gpt-4.1` | $2.00 | $8.00 | [OpenAI pricing](https://developers.openai.com/api/docs/pricing) |
| `gpt-4.1-mini` | $0.40 | $1.60 | [OpenAI pricing](https://developers.openai.com/api/docs/pricing) |
| `gpt-4o` | $2.50 | $10.00 | [OpenAI pricing](https://developers.openai.com/api/docs/pricing) |
| `gpt-4o-mini` | $0.15 | $0.60 | [OpenAI pricing](https://developers.openai.com/api/docs/pricing) |
| `o4-mini` | $1.10 | $4.40 | [OpenAI pricing](https://developers.openai.com/api/docs/pricing) |
| `claude-sonnet-5-5` | $2.00 | $10.00 | [Anthropic model page](https://platform.claude.com/docs/en/models/sonnet-5-5/overview) |
| `claude-sonnet-4` | $3.00 | $15.00 | [Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing) |
| `claude-3-5-sonnet` | $3.00 | $15.00 | [Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing) |
| `claude-3-5-haiku` | $0.80 | $4.00 | [Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing) |
| `claude-opus-4` | $15.00 | $75.00 | [Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing) |
| `gemini-3-flash-preview` | $0.50 | $3.00 | [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing) |
| `gemini-3.1-flash-lite` | $0.25 | $1.50 | [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing) |
| `gemini-3.1-pro-preview` | $2.00 | $12.00 | [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing) (≤ 200k context) |
| `gemini-3.8-flash` | $0.75 | $3.75 | [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing) (introductory through 2026-12-31) |
| `gemini-2.5-flash` | $0.30 | $2.50 | [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing) |
| `gemini-2.5-pro` | $1.25 | $10.00 | [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing) |
| `gemini-2.0-flash` | $0.10 | $0.40 | [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing) (deprecated) |
| `mock-planner` | $0.00 | $0.00 | Deterministic baseline: no paid call |

Models that are not in this table (including `gpt-6.1-sol` and `claude-haiku-5-5` in this version) are
reported as `N/A`. Adding a row requires a dated provider source and a bump of `PRICING_VERSION`.

## 3. What the estimate includes

- **Text input and output tokens only.** Cached-input discounts, cache writes, reasoning/thinking
  tokens billed at a different rate, batch/Flex discounts, Priority/Fast tiers, long-context
  multipliers and tool fees are **not** modelled. The adapter reports the token counts the provider
  returned, so a model that bills thinking tokens in `completion_tokens` is included at the output
  rate.
- **Standard tier.** The table intentionally stores the standard list price, not the cheapest
  possible tier.
- **No currency conversion.** All values are USD.
- The gateway's pre-flight budget check only uses a known price; an unpriced model bypasses it, which
  is why the live benchmark additionally refuses unpriced calls unless `--allow-unpriced` is passed.

## 4. Change procedure

1. Confirm the price against the provider's official pricing page and note the date.
2. Update `PRICES` and `PRICING_VERSION` / `PRICING_AS_OF` in `pricing.py`.
3. Update the table in this document and the date at the top.
4. Run `pytest tests/unit/test_pricing_and_tracing.py` and the benchmark; the report records
   `pricing_version` and `pricing_as_of` in its metadata.
5. Re-run the live benchmark before quoting a cost comparison; old reports remain labeled with the
   table version that produced them.

## 5. References

- Implementation and tests:
  [pricing.py](../packages/llm-gateway/src/docentric_copilot/llm/pricing.py),
  [test_pricing_and_tracing.py](../tests/unit/test_pricing_and_tracing.py)
- Live benchmark metadata: `pricing_version`, `pricing_as_of`, `pricing_source`
- [EVALUATION](EVALUATION.md) for the metric definitions and the latest measured numbers
