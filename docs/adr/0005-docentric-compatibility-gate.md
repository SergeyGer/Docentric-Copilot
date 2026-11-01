# ADR-0005: Gate Docentric AX compatibility behind evidence

| Field | Value |
| --- | --- |
| Status | Accepted |
| Date | 2026-11-01 |
| Related | [DOCENTRIC_AX_COMPATIBILITY](../DOCENTRIC_AX_COMPATIBILITY.md), [FEASIBILITY](../FEASIBILITY.md), [SRS NFR-05](../SRS.md#nfr-05--fail-closed-compatibility) |

## Context

The project generates generic OOXML documents. Its name and problem domain invite the question: "does
this produce Docentric AX templates?" The honest answer is that the project does not know, because it
has:

- no authoritative specification of the AX template/tagging format;
- no licensed AX environment;
- no native template or permitted real DDSP package for comparison;
- no acceptance procedure agreed with the vendor or a customer.

Two failure modes were considered:

1. **Optimistic adapter.** Emit a DOCX that "looks like" a template, ship it under a compatibility
   name, and let customers discover the truth. This risks silent, customer-facing document failures
   and is ethically unacceptable.
2. **Fail closed.** Refuse the target with a typed error, publish the evidence required to change the
   status, and keep the gate in code, reports, metadata, the API and the documentation.

A third possibility, quietly treating "opens in Word" as compatibility, was rejected: it is not a
compatibility test and would be a claim without evidence.

## Decision

Create an explicit **compatibility gate**:

- `DocentricAXCompiler` exists but `compile()` always raises `UnsupportedTargetError` with the gate
  reason; it is never enabled by configuration.
- `DC_ENABLE_AX_ADAPTER` changes only the capability status text, never the outcome.
- The compiler registry reports `available=false, verified=false` for `docentric-ax`.
- Validation V5 always emits `not_tested`; `overall` is `passed_unverified_compatibility`, never
  `passed`.
- DOCX core properties state `docentric-compatibility=not_tested`; the preview and optional stamp state
  that compatibility is not verified.
- The product decision is path B/C (generic engine released; AX adapter deferred; manual adaptation
  unsupported), recorded in [DOCENTRIC_AX_COMPATIBILITY §5](../DOCENTRIC_AX_COMPATIBILITY.md#5-feasibility-gate-paths-a-b-and-c).
- Reopening the gate requires the evidence in §7 and the acceptance criteria in §8, with a new ADR.

## Consequences

**Positive**

- No false compatibility claim can originate from the code or the documentation.
- The failure is typed and testable (HTTP 409, exit code 4, `not_tested` reports).
- Users get a useful generic product without being misled; integration partners know exactly what is
  missing.
- The evidence checklist makes a future decision auditable.

**Negative / costs**

- The product is less attractive to buyers who need AX output today.
- A permanent `not_tested` status can look like an unfinished feature; it is a deliberate non-claim.
- The gate must be maintained across every surface (API description, capability payload, DOCX metadata,
  reports, preview, README). Drift is a real risk and is covered by tests only partially.
- Setting a feature flag that does nothing may confuse operators; the status text explains why.

## Alternatives rejected

- **Optimistic output with a disclaimer:** disclaimers are not read; a compatible-looking file causes
  harm.
- **"Experimental" AX output behind a flag:** an experimental label still implies the output is
  meaningful; without evidence it is guesswork.
- **Removing the AX target entirely:** losing the explicit, testable refusal and the documented path to
  a future adapter.

## Follow-up

- Any change to the gate behaviour requires updating this ADR, the compatibility document, the SRS and
  the tests that assert 409/exit 4/`not_tested`.
- Do not use the word "verified" about Docentric compatibility anywhere. "Unverified", "not tested" and
  "blocked" are the correct terms.
