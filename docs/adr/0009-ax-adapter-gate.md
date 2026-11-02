# ADR-0009 — AX adapter exists as a gated interface, not an implementation

| Field | Value |
| --- | --- |
| Status | Accepted |
| Date | 2026-11-02 |
| Deciders | Project maintainers |
| Related | [DOCENTRIC_AX_COMPATIBILITY](../DOCENTRIC_AX_COMPATIBILITY.md), [ADR-0005](0005-docentric-compatibility-gate.md) |

## Context

A real Docentric AX compiler needs a supported tagging format, licensed runtime and reference
packages. None of these are available or verified. Promising AX output without them would be
dishonest and commercially risky.

## Decision

Ship the adapter **interface** and a capability matrix (`Field`, `List`, `Image`, `Conditional`,
validator, integration harness) marked `experimental` and `not_tested`. The adapter raises
`UnsupportedTargetError`; the API keeps rejecting the AX target and reports the blocking questions.

## Consequences

- Integrators can see the intended contract without mistaking it for working output.
- The compatibility gate and the `not_tested` status remain intact.
- v1.0 stays a target, not a promise: without a lawful, verifiable integration path the project keeps
  its generic-document positioning.

## Alternatives considered

- **Emit a best-guess AX markup** — unverifiable and misleading; rejected.
- **Do nothing** — hides the planned architecture from reviewers and partners.

## Follow-up

Obtain lawful sample packages, a supported tagging format and a licensed test environment; then
implement the adapters behind the existing gate and publish an independent integration report.
