# ADR-0008 — Quality checks on the Template IR, not on rendered pixels

| Field | Value |
| --- | --- |
| Status | Accepted |
| Date | 2026-11-02 |
| Deciders | Project maintainers |
| Related | [QUALITY](../QUALITY.md), [ADR-0004](0004-preview-strategy.md) |

## Context

Visual defects (overflowing tables, oversized images, unbreakable values) erode trust in the output.
Pixel analysis needs a rendering stack and produces hard-to-explain findings; the IR already knows
widths, page geometry and bindings.

## Decision

Run deterministic checks on the validated IR, return per-element findings with a stable id and an IR
path, and express every automatic fix as a typed IR change that produces a new version and a fresh
validation pass.

## Consequences

- Findings are explainable and reproducible; no renderer is required for CI.
- The checks cannot see Word pagination or font substitution. PDF rendering remains optional and is
  labelled as LibreOffice output.
- Optimisation can never silently trade a warning for a failure: the original document is kept.

## Alternatives considered

- **PDF pixel analysis first** — strongest fidelity, but needs a licensed/desktop renderer and makes
  CI non-deterministic.
- **Heuristic warnings without fixes** — safer, but leaves the user with manual work.

## Follow-up

LibreOffice renderer behind a capability flag (issue #14), visual regression fixtures, and a
quality dashboard that groups findings by page once a renderer exists.
