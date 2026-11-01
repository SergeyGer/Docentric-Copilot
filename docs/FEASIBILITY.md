# M0 Feasibility Findings

| Field | Value |
| --- | --- |
| Milestone | M0 — feasibility and compatibility decision |
| Outcome | Generic deterministic engine is feasible; an AX-compatible compiler is **not** feasible with the evidence available |
| Decision | Path B/C: release the generic engine, defer the AX adapter, allow unsupported manual adaptation |
| Related | [DOCENTRIC_AX_COMPATIBILITY](DOCENTRIC_AX_COMPATIBILITY.md), [ADR-0005](adr/0005-docentric-compatibility-gate.md), [DDSP_COMPATIBILITY](DDSP_COMPATIBILITY.md) |

This document records *what was learned before building* and distinguishes it from what the project
later demonstrated. It contains no claim that was not either implemented and tested or explicitly
marked as unproven.

## 1. Questions the feasibility study had to answer

1. Can a business document be generated from a DDSP-style data package without Microsoft Word,
   Docentric Designer or a Dynamics 365 environment?
2. Can the output be made deterministic and reviewable enough to test in CI?
3. Can an LLM be constrained so that it cannot silently invent fields?
4. Can the project honestly claim compatibility with Docentric AX?
5. If not, what is the most useful honest product that can be shipped?

## 2. Method and evidence base

| Evidence source | What it supports | Limits |
| --- | --- | --- |
| Public OOXML/WordprocessingML documentation (ECMA-376 family) | Generic DOCX is a documented, open format; a library can generate it | `python-docx` covers a subset; Word rendering is not specified by the file format alone |
| The project's own synthetic DDSP packages (`examples/`) | A workable ingestion model: ZIP + manifest + XSD + sample XML | They are authored by this project; they are **not** evidence about real DDSP |
| The manifest string `docentric-ax-ddsp` | The package family is labelled as related to a Docentric AX pipeline | A label is not a specification |
| Behavioural experiments with `python-docx` and ZIP normalisation | Byte-identical output is achievable with fixed timestamps, sorted entries and fixed core properties | Verified for the DOCX subset used by this project |
| Experiments with a typed IR (pydantic) and a validator | Model output can be rejected or repaired deterministically | Does not prove the repaired document is *business-correct* |
| Provider API documentation for OpenAI/Anthropic/Gemini | Structured output mechanisms exist for all three | Live behaviour, quotas and drift were not tested here |

**Not available:** an authoritative public specification of the DDSP container, the Docentric AX
template/tagging format, its required package parts, or its version differences. The project did not
obtain a licensed environment, a native template, or a permitted real DDSP package. Any statement
about those formats in this repository is therefore a hypothesis or a non-claim, never a finding.

## 3. Findings

### F-1 — Generic document generation is feasible (demonstrated)

A validated IR can be rendered with `python-docx` into a valid OOXML package containing paragraphs,
headings, tables, images, headers/footers and repeats. The package passes structural inspection
(required entries, no macros, no embedded objects) and opens as a DOCX in the tooling used by the
test suite (it is parsed back by `python-docx`). This is a statement about OOXML structure, not about
visual fidelity in Word.

### F-2 — Determinism is feasible (demonstrated)

Byte-identical output is achievable by removing every environmental input from the compiler:

- sorted ZIP entries, fixed timestamps, fixed permissions, deterministic deflate level;
- fixed core properties (created/modified/revision/author), IR-derived metadata only;
- no clock, randomness or network in the compile path;
- canonical JSON for IR digests.

Repeated runs on the quotation fixture produced the same SHA-256 (`c882f0b1…`, 39,749 bytes) across CLI
and API paths. This is the basis of NFR-01 and the golden suite.

### F-3 — Constraining a model to a typed contract is feasible (mechanism demonstrated)

A pydantic model with `extra="forbid"`, a JSON Schema for structured output, a deterministic
sanitiser, and a validator that blocks compilation unless V1–V3 pass together prevent an unresolvable
binding from reaching a document. The mock provider demonstrates the full path offline; the three
hosted adapters implement the same contract but their live behaviour remains unverified.

What this does **not** prove: that a model's *choice* of fields is good, that requirements are fully
covered, or that the resulting document is business-correct. Those are evaluation questions
([EVALUATION](EVALUATION.md)).

### F-4 — Evidence-based DDSP parsing is feasible; DDSP compatibility is not proven

Because no authoritative layout is available, the parser was designed to discover structure from
XSD/sample XML and to report what it cannot interpret. This yields a usable schema for synthetic
packages and a defensible failure mode for unknown ones. It cannot establish that a real DDSP will be
parsed correctly; the honest label is "implemented against synthetic fixtures, unverified against real
packages".

### F-5 — An AX-compatible compiler is not feasible without external evidence (decisive finding)

The following are unknown and cannot be responsibly guessed:

1. the tagging elements or field syntax a native template must contain;
2. the required package parts, relationships and content types;
3. how data binding at print time is expressed and evaluated;
4. version-specific differences and validation behaviour;
5. the acceptance procedure in a licensed environment.

Generating a DOCX that *looks* like a template and calling it compatible would be a false claim with
customer-facing consequences. The feasibility study therefore rejects path A (automated adapter) for
now and records the gate in [DOCENTRIC_AX_COMPATIBILITY](DOCENTRIC_AX_COMPATIBILITY.md).

### F-6 — A useful honest product exists without AX output (decision basis)

A deterministic, schema-validated, versioned generic DOCX pipeline is independently valuable:

- it removes silent binding drift (V2/V3);
- it makes templates reviewable (IR, mapping, diffs);
- it gives a reproducible baseline for AI planning;
- it fails closed instead of pretending compatibility.

## 4. What public documentation supports

- The **OOXML** package and WordprocessingML parts used by the compiler are public standards. The
  project relies on that for generic DOCX, not on any vendor-specific extension.
- **JSON Schema draft 2020-12** is public and used for the IR schema export.
- The **provider APIs** document structured output mechanisms; the adapters follow those documents but
  are only contract-tested with mocked transports.
- No public documentation was available to this project for the DDSP layout or the AX template format.
  The project does not cite, quote or bundle any third-party specification or asset.

## 5. What remains unproven

| Open question | Consequence | How it could be resolved |
| --- | --- | --- |
| Real DDSP layout and manifest semantics | Parser may reject or misread production packages | Permitted representative package + fixtures |
| Whether a DDSP carries tagging metadata | AX adapter design would change fundamentally | Same, plus documentation |
| AX tagging vocabulary and required parts | No adapter possible | Licensed environment + authoritative docs |
| Whether generic DOCX renders acceptably in Word | Visual review may fail | Word-based manual review protocol; not automatable here |
| LLM quality vs. the deterministic baseline | Product value of the AI path unproven | Repeatable evaluation with credentials |
| Cost and latency at scale | Deployment economics unknown | 100-run benchmark + provider measurements |
| Security posture under hostile load | DoS and quota risks | Load tests + quotas + external review |

## 6. Decision

> **Decision (M0):** ship the deterministic **generic DOCX** engine (path B). Defer the Docentric AX
> adapter until the evidence required by [DOCENTRIC_AX_COMPATIBILITY §7](DOCENTRIC_AX_COMPATIBILITY.md#7-evidence-required-to-change-the-status)
> exists. Path C (manual adaptation by a licensed user) is allowed as an **unsupported** workflow and
> must never be described as compatibility.

Consequences recorded in the architecture:

- `DocentricAXCompiler` exists only as a fail-closed placeholder;
- validation V5 always returns `not_tested`;
- the capability payload reports the AX target as `available=false, verified=false`;
- the report verdict is `passed_unverified_compatibility`, never `passed`;
- documentation, API descriptions, DOCX metadata and the preview all state the non-claim.

## 7. Stop conditions

The following conditions would stop or redirect the work. They are recorded so that future decisions
are explicit rather than drifting.

| ID | Condition | Consequence |
| --- | --- | --- |
| SC-1 | A permitted real DDSP package cannot be obtained | Keep the parser evidence-based and labelled unverified; do not claim DDSP support |
| SC-2 | No licensed AX environment or authoritative specification becomes available | AX adapter remains blocked indefinitely; no partial AX output is shipped |
| SC-3 | A proposed feature requires guessing a vendor format | Reject the feature; add a diagnostic or a non-claim instead |
| SC-4 | A change would make output non-deterministic in the compile path | Reject the change; determinism is a product requirement (NFR-01) |
| SC-5 | Input cannot be bounded (size/depth/time) | Do not ship the parser change; a bounded rejection is preferable |
| SC-6 | A metric cannot be measured reproducibly | Report `TBD` with a measurement plan, never an estimate presented as a result |
| SC-7 | A dependency's licence or security posture is incompatible | Replace or remove the dependency; record an ADR |

## 8. M0 acceptance

- [x] Problem and personas defined ([PRD](PRD.md)).
- [x] Feasibility questions answered to the extent the evidence allows (this document).
- [x] Compatibility paths A/B/C analysed and a decision recorded (this document, ADR-0005).
- [x] Explicit non-claims published ([DOCENTRIC_AX_COMPATIBILITY §9](DOCENTRIC_AX_COMPATIBILITY.md#9-explicit-non-claims)).
- [x] Evidence required to reopen the gate defined.
- [ ] Representative real-world DDSP package studied — **blocked** (SC-1).
- [ ] Licensed AX environment available — **blocked** (SC-2).

M0 is accepted on the basis of the information available, with the two blocked items explicitly
carried into [ROADMAP](ROADMAP.md).
