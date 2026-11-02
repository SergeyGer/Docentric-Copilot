# ADR-0007 — Adaptive model routing with a deterministic baseline

| Field | Value |
| --- | --- |
| Status | Accepted |
| Date | 2026-11-02 |
| Deciders | Project maintainers |
| Related | [ROUTING](../ROUTING.md), [ADR-0006](0006-provider-gateway.md) |

## Context

Provider choice was manual and static. The product brief asks for routing by task complexity and a
measured quality/cost trade-off, while keeping the deterministic validator as the final gate. Live
provider benchmarks need keys, budget and a pinned model version, none of which are available in CI.

## Decision

Classify each request into `simple`, `standard`, `complex` or `ambiguous` using observable facts
(schema shape, requirement count, collections, depth, review flags), map the class to a provider
tier with an explicit budget, and fall back to the deterministic `mock` provider when no preferred
provider is configured. The decision, its reasons and the budget are persisted with the plan.

## Consequences

- Routing is reproducible and testable offline; the fallback path is the one CI exercises.
- The repository cannot claim a provider quality comparison until a live benchmark with pinned
  model versions exists. Documentation states this explicitly.
- `ambiguous` routes to human review instead of guessing, which links routing to the mapping review
  flow rather than creating a second decision path.

## Alternatives considered

- **Static provider setting** — simpler, but no measurable cost/quality story.
- **LLM-based classifier** — adds a model call to decide which model to call; rejected as circular
  and harder to test.

## Follow-up

Live benchmark per provider (issue #16), cost dashboard over stored runs, and a documented
escalation policy once the benchmark shows a quality gap.
