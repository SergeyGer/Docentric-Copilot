# ADR-0006: One provider gateway with a shared structured-output contract

| Field | Value |
| --- | --- |
| Status | Accepted |
| Date | 2026-11-01 |
| Related | [SRS FR-03](../SRS.md), [THREAT_MODEL T-09…T-16](../THREAT_MODEL.md#52-prompt-and-model-boundary), [EVALUATION](../EVALUATION.md) |

## Context

The planner must be able to use OpenAI, Anthropic, Gemini and a deterministic offline provider.
Each provider differs in:

- how structured output is requested (`response_format=json_schema`, forced tool use, `responseSchema`);
- token/usage field names and finish reasons;
- error status codes, retry semantics and `Retry-After` handling;
- supported JSON Schema subsets (Gemini rejects many keywords);
- authentication headers.

Letting these differences leak into the planner would spread provider-specific branches across prompt
construction, error handling and tests, and would make the deterministic baseline a special case.

## Decision

Create one gateway (`docentric_copilot.llm.LLMGateway`) and one adapter contract:

```python
async def generate_structured(*, messages, schema: dict, settings) -> GenerationResult
```

- The gateway owns provider construction, model resolution, timeouts, retries, budget pre-flight, error
  normalisation, telemetry and logging.
- Every adapter returns a `GenerationResult` whose `content` is a JSON object. The gateway validates that
  object against the caller's pydantic model and rejects non-conforming output with
  `provider_invalid_output`.
- Provider-specific schema conversion is contained in the adapter (for example `to_gemini_schema`).
- The mock provider implements the same interface and requires no network; the planner installs a
  deterministic responder for the baseline.
- Retries are limited to transport/5xx/429 conditions with bounded backoff; the planner may additionally
  retry a schema-invalid response once with a repair message, bounded by `max_repair_attempts`.
- Prompt content is fenced and data-minimised before it reaches any adapter; the adapter never adds
  business context of its own.

## Consequences

**Positive**

- New providers are additive: one adapter plus configuration, no planner changes.
- Errors are uniform (`provider_error`, `provider_timeout`, `provider_bad_response`,
  `provider_invalid_output`, `provider_not_configured`, `budget_exceeded`), which maps cleanly to HTTP
  statuses and CLI exit code 5.
- The same evaluation and benchmark code can compare providers by changing a flag.
- The mock provider keeps the pipeline testable offline and gives the evaluation a reproducible control.

**Negative / costs**

- The lowest-common-denominator contract hides provider-specific capabilities (streaming, tool loops,
  prompt caching, multimodal input); using them would require deliberate extensions.
- Schema conversion can silently degrade structure (Gemini subset); the fallback paths are tested with
  mocked responses, not against live APIs.
- The pricing table is static and approximate; cost telemetry can drift from real invoices, and unknown
  models are unpriced.
- Adapter tests use mocked transports, so provider API changes can break production before tests notice.

## Alternatives rejected

- **Use each provider SDK directly in the planner:** more dependencies, more divergence, harder
  deterministic testing.
- **A generic agent framework:** large dependency surface, implicit retries/tool loops, harder to bound
  cost and to audit prompt content.
- **A single provider only:** unacceptable lock-in for an on-premises/enterprise context, and no control
  baseline.

## Follow-up

- Add contract tests with recorded request/response fixtures to detect provider API drift.
- Verify the pricing table against current provider pricing, or mark models as `unpriced` explicitly.
- Keep the "no network in tests" rule; live verification is a separate, credentialed exercise.
