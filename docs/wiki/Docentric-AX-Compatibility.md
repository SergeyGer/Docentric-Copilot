# Docentric AX Compatibility

> **Status: unverified.** This page explains exactly what that means, why it is the honest status, and what
> evidence would be required to change it.

## The claim we deliberately do not make

Docentric Copilot produces **generic DOCX** documents. It does **not** claim that those documents are
recognised, executed or rendered correctly by Docentric AX for Dynamics 365 Finance & Operations.

This is not modesty. It is the conclusion of the feasibility analysis: the format of Docentric tagging
elements is not publicly specified, and no licensed Docentric environment was available to verify generated
output.

## How the gate manifests in the product

| Surface | Behaviour |
| --- | --- |
| API `target: "docentric-ax"` | HTTP `409`, code `target_unsupported`, details include the gate |
| CLI `--target docentric-ax` | exit code `4` |
| Validation report | `docentric_compatibility: "not_tested"` — never `"passed"` |
| Web workspace | amber banner + dashed neutral V5 badge |
| README / release notes | explicit non-claim in the first screen |

The AX compiler class exists but always raises: it cannot silently produce an unverified artifact.

## Feasibility paths

| Path | Condition | Decision |
| --- | --- | --- |
| **A** — verified compatibility | Format understood, legally implementable, execution proven in a licensed environment | Not reached |
| **B** — runtime unverified | Format partially understood, no independent execution evidence | **Current position**: experimental adapter stays disabled |
| **C** — infeasible or legally blocked | No lawful, verifiable route | Fallback: generic engine only |

The project is on path B: the generic engine is fully released, the AX adapter is deferred.

## Evidence required to change the status

1. A **permitted** real DDSP package and the corresponding Docentric template for the same scenario.
2. Written clarification (or licence review) that programmatic generation of tagging elements is allowed.
3. A reference template produced by Docentric Designer, with its internal XML inspected.
4. Independent execution of a generated document in a licensed Docentric AX environment, covering at least
   **Field, List, Image and If**.
5. Reproducible integration tests stored in a permitted form (no proprietary binaries in the repository).

When all five exist, the adapter may be enabled, the V5 check promoted to `passed`, and a compatibility
matrix published per AX version.

## How to contribute evidence

If you have a licensed environment and can run a permitted verification, open an issue titled
`Compatibility evidence: <AX version>` describing:

- what was tested (scenario, elements),
- how it was produced (commit, IR digest),
- the observed result (screenshots/logs that may legally be published).

## Related reading

- [DDSP Compatibility](DDSP-Compatibility) — the input side of the same problem.
- [Validation Model](Validation-Model) — why `not_tested` is a first-class result.
- [ADR-0005 Compatibility gate](https://github.com/SergeyGer/Docentric-Copilot/blob/main/docs/adr/0005-docentric-compatibility-gate.md).

## Adapter interface (experimental, gated)

The repository now ships the AX adapter **contract** and a capability matrix — `FieldAdapter`,
`ListAdapter`, `ImageAdapter`, `ConditionalAdapter`, `CompatibilityValidator` and
`IntegrationTestHarness`. Every capability is marked `experimental`; the adapter raises
`UnsupportedTargetError` and the API keeps rejecting the AX target.

The blocking questions are explicit: which tagging format is lawfully supported, where licensed
runtime and reference packages can be obtained, and which dynamic elements an independent
integration run must execute. Until those are answered, **generic DOCX is the only output** and the
status stays `not_tested`.

Decision record: [ADR-0009](../adr/0009-ax-adapter-gate.md).
