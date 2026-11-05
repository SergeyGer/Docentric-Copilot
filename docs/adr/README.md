# Architecture Decision Records

Every significant decision is recorded as an ADR: what forced it, what we chose, and what it costs.
ADRs are immutable once accepted; a changed decision is superseded, never rewritten.

| ADR | Decision | Status |
| --- | --- | --- |
| [ADR-0001](0001-template-ir.md) | A versioned Template IR between the planner and the compilers | Accepted |
| [ADR-0002](0002-llm-compiler-separation.md) | The LLM plans; deterministic code compiles | Accepted |
| [ADR-0003](0003-deterministic-docx.md) | Deterministic DOCX output and content addressing | Accepted |
| [ADR-0004](0004-preview-strategy.md) | Independent HTML preview, never a Docentric runtime | Accepted |
| [ADR-0005](0005-docentric-compatibility-gate.md) | Fail-closed Docentric AX compatibility gate | Accepted |
| [ADR-0006](0006-provider-gateway.md) | Provider gateway with a deterministic baseline | Accepted |
| [ADR-0007](0007-adaptive-model-routing.md) | Adaptive routing with a deterministic fallback | Accepted |
| [ADR-0008](0008-ir-level-quality-engine.md) | Quality checks on the IR, not on pixels | Accepted |
| [ADR-0009](0009-ax-adapter-gate.md) | The AX adapter is a gated interface, not an implementation | Accepted |
| [ADR-0010](0010-reference-inspector.md) | A read-only reference inspector before any Docentric AX writer | Accepted |
| [ADR-0011](0011-reference-graph.md) | A separate ReferenceGraph and read-only Reference IR | Accepted |
| [ADR-0012](0012-reference-diff-and-evaluation.md) | Reference diff and reference-based evaluation | Accepted |
| [ADR-0013](0013-d365-embedded-schema-and-binding-resolution.md) | D365 embedded schema and binding resolution | Accepted |
| [ADR-0014](0014-gold-dataset-and-reference-benchmark.md) | Gold dataset and reference benchmark | Accepted |

New ADRs start from [TEMPLATE.md](TEMPLATE.md) and are reviewed in the pull request that needs
the decision. `scripts/check_docs_links.py` verifies the structure and this index in CI.
