# Adaptive routing

The router chooses a provider tier from observable facts: schema shape, requirement count,
collections, nesting depth and whether a binding needs review.

| Complexity | Signal | Tier |
| --- | --- | --- |
| simple | ≤ 4 requirements, no collection | fast |
| standard | one collection | balanced |
| complex | several collections, many requirements, conditionals | advanced |
| ambiguous | a binding needs review | advanced + human review |

No cloud provider is required: without configured keys the router selects the deterministic `mock`
provider, records `fallback_used` and explains how much budget the task would have used. Validation
remains the final gate, and routing never skips it.

A live benchmark per provider is not published yet. Every number in this project is reproducible
offline; provider comparisons will be added only with a pinned model version and a recorded budget.

Full detail: [docs/ROUTING.md](../ROUTING.md) · decision: [ADR-0007](../adr/0007-adaptive-model-routing.md).
