# ADR-0002: Separate LLM planning from deterministic compilation

| Field | Value |
| --- | --- |
| Status | Accepted |
| Date | 2026-11-01 |
| Related | [SRS FR-03/FR-05](../SRS.md), [ARCHITECTURE §5.2](../ARCHITECTURE.md#52-planning-schema--requirement--ir), [ADR-0006](0006-provider-gateway.md) |

## Context

A language model is useful for interpreting a requirement ("include an EU VAT notice when the customer
is in the EU") but unsuitable as the component that writes files: its output varies between calls, it
can hallucinate fields, and it cannot be regression-tested against byte-level expectations.

A single "AI writes the document" pipeline was considered. It would be simpler to build but would make
every guarantee conditional on model behaviour: no deterministic artifacts, no stable golden files, no
way to separate a model failure from a compiler failure, and no defensible answer to "why did this
document bind a field that does not exist?".

## Decision

Split the pipeline at the Template IR:

- **Planning (non-deterministic, model-facing):** `docentric_copilot.planner` builds prompts, calls a
  provider through the gateway, validates the proposal against the IR model, and runs a deterministic
  sanitisation and mapping-report pass.
- **Execution (deterministic, model-free):** validation and compilation never import a model client,
  never perform network I/O, never read the clock and never use randomness.

The sanitisation pass is deliberately conservative: any binding, repeat, conditional or image that
cannot be resolved against the schema is **removed** and reported. It never guesses a replacement.

## Consequences

**Positive**

- Model output is treated as an untrusted proposal, not as an artefact.
- Compilation and validation can be tested exhaustively and deterministically; the mock provider
  exercises the full path without credentials.
- Failures are attributable: provider errors (`5xx`/`provider_*`) are distinct from validation
  (`422 validation_failed`) and compilation (`422 compilation_failed`) failures.
- The system can run fully offline (mock) for demos, tests and CI.

**Negative / costs**

- The IR must be expressive enough to carry the model's intent; otherwise planning quality is limited by
  the contract, not the model.
- Two passes over the document (plan → validate) add complexity and latency (the mock plan is tens of
  milliseconds; hosted latency is provider-dominated).
- Sanitisation can silently remove content from a user's perspective; the mapping report and
  `removed_bindings` list are the only mitigation, and users must review them.
- Prompt-injection resistance depends on the IR/validator, not on the model obeying instructions.

## Alternatives rejected

- **Let the model emit DOCX or OOXML directly:** unvalidatable, unsafe, non-deterministic.
- **Let the model patch an existing document:** requires a trustworthy document model we do not have,
  and makes diffs unreliable.
- **Use the model at compile time for "smart" formatting:** violates determinism (NFR-01) and makes
  offline use impossible.

## Follow-up

- New planner capabilities must keep the "proposal → sanitise → validate" order.
- If a feature cannot be expressed in the IR, change the IR first (with an ADR) rather than adding a
  model-specific escape hatch.
