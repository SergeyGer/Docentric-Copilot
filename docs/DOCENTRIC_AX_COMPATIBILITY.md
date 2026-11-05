# Docentric AX Compatibility: Gate, Status and Non-Claims

| Field | Value |
| --- | --- |
| Status | **Blocked / unverified.** No compatibility is claimed. |
| Compiler | `DocentricAXCompiler` in [generic.py](../packages/docx-compiler/src/docentric_copilot/docx_compiler/generic.py) |
| Gate status string | `blocked: feasibility gate M0 has not been passed` |
| Related | [FEASIBILITY.md](FEASIBILITY.md), [ADR-0005](adr/0005-docentric-compatibility-gate.md), [ADR-0013](adr/0013-d365-embedded-schema-and-binding-resolution.md), [DDSP_COMPATIBILITY.md](DDSP_COMPATIBILITY.md) |

## 1. Scope of this document

This document records three things:

1. why the project does **not** claim Docentric AX compatibility;
2. what the code does today when an AX target is requested;
3. what evidence would be required to change the status, and the paths considered.

It is a compatibility *gate*, not a marketing page. Nothing here may be quoted as "works with",
"verified for" or "certified for" Docentric AX.

## 2. Terminology

- **Generic DOCX** — an OOXML word-processing document produced by `python-docx` and normalised by this
  project. It contains ordinary paragraphs, tables, images and core properties. It contains no
  product-specific tagging vocabulary.
- **Docentric AX** — a third-party document reporting/templating product for Microsoft Dynamics 365.
  This project is independent and is not affiliated with or endorsed by its vendor.
- **AX adapter** — a compiler target (`docentric-ax`) that would emit whatever a Docentric AX
  environment expects, rather than plain OOXML.
- **Compatibility** — the claim that a document produced by this project can be consumed by a specific
  Docentric AX version/configuration in the way a native template is consumed. This is the claim that
  is **not** made.

## 3. Current status

| Question | Answer |
| --- | --- |
| Is an AX adapter implemented? | No. `DocentricAXCompiler.compile` always raises. |
| Can the adapter be enabled by configuration? | No. `DC_ENABLE_AX_ADAPTER` only changes the capability status text. |
| What does a request with `target=docentric-ax` return? | HTTP `409` with `code=target_unsupported` (CLI: exit code 4). |
| What does the validation report say? | V5 check status `not_tested`; overall `passed_unverified_compatibility` for a valid generic document. |
| Is any AX compatibility claimed? | No. |
| Has any AX environment been used in development? | No. No licensed environment was available. |
| Are real DDSP packages tested? | No. Only synthetic fixtures in the public test suite; the local corpus may be inspected privately. |
| Does D365 embedded-schema inspection change this gate? | No. `reference d365` reads static `ProjectData` XSD/`PreviewData` evidence and reports `not_tested`; it does not execute or validate in Docentric AX. |

## 4. What the code does today (fail closed)

The gate is implemented in several independent places so that a single mistake cannot silently produce
a "compatible-looking" document.

| Control | Behaviour | Evidence |
| --- | --- | --- |
| Compiler | `DocentricAXCompiler.compile` raises `UnsupportedTargetError` with `details.target`, `details.gate`, `details.documentation` | `docx_compiler/generic.py` |
| Generic compiler | Refuses any target other than `generic-docx` while `verified_compatibility` is false | `docx_compiler/generic.py` |
| Registry | Reports `available: false, verified: false` for `docentric-ax`; the flag only alters the status wording | `docx_compiler/registry.py` |
| Capabilities API | `features.docentric_ax_adapter=false`, `features.verified_compatibility=false` | `api/routes/system.py` |
| Validation | V5 always emits `not_tested` and never participates in `can_compile` | `template_validator/engine.py` |
| CLI | `compile --target docentric-ax` exits with code 4 | `cli/main.py` |
| API | Compile route returns `409 target_unsupported` | `api/routes/templates.py` |
| DOCX metadata | `keywords` includes `docentric-compatibility=not_tested`; `comments` states the document is generic and unverified | `docx_compiler/generic.py` |
| Optional stamp | `include_compatibility_stamp=true` appends "Docentric AX compatibility: not verified." | `docx_compiler/generic.py` |
| Preview | Toolbar badge: "Docentric AX compatibility: not verified" | `preview/renderer.py` |
| API description | OpenAPI description states compatibility is unverified and reported as `not_tested` | `api/app.py` |

The exact error returned today:

```json
{
  "error": {
    "code": "target_unsupported",
    "message": "The Docentric AX compiler is not available: autonomous generation of Docentric tagging elements has not been verified in a licensed environment",
    "details": {
      "target": "docentric-ax",
      "gate": "blocked: feasibility gate M0 has not been passed",
      "documentation": "docs/DOCENTRIC_AX_COMPATIBILITY.md"
    }
  }
}
```

HTTP status `409`; CLI exit code `4`. Both are stable contract values.

## 5. Feasibility gate: paths A, B and C

The M0 feasibility study considered three paths. They are mutually exclusive as *product claims*, but
B and C can coexist operationally.

### Path A — automated AX adapter

Build a compiler that emits AX-compatible documents and prove compatibility in a licensed environment.

Required: authoritative format documentation, representative templates and data packages, a licensed
environment, an agreed acceptance procedure, and permission to test and publish results. Then:
implement the adapter, extend the IR if necessary (or map the IR to the target construct), run the
compatibility suite, and only then set `verified_compatibility = true`.

**Status: not attempted.** The prerequisites are not available to this project.

### Path B — generic engine released, AX adapter deferred (current)

Release the deterministic generic DOCX engine, expose the AX target as explicitly unavailable, and
report compatibility as `not_tested` everywhere. Users who need AX output do the product-specific step
themselves, with no claim from this project.

**Status: this is the recorded decision.** It is the only honest option while the evidence in §7 is
missing.

### Path C — assisted manual adaptation (operational, not a claim)

A user exports the generic DOCX and the canonical IR, then performs product-specific tagging in a
licensed environment. This may be useful operationally, but:

- it is not implemented or automated by this project;
- it is not tested;
- it does not make the output "compatible" in any certified sense;
- the mapping from generic constructs to AX constructs is the user's responsibility.

**Status: possible workflow, explicitly out of scope and unsupported.**

### Decision record

> Decision: **path B, with path C available only as an unsupported manual workflow.** The generic
> engine is released; the AX adapter is deferred. The gate remains blocked until the evidence in §7
> exists and the acceptance criteria in §8 are met.

This decision is also recorded in [ADR-0005](adr/0005-docentric-compatibility-gate.md). Reopening it
requires a new ADR, not an incremental code change.

## 6. Compatibility matrix

The matrix is intentionally pessimistic. "Not attempted" means no work exists; "not tested" means code
may exist but no evidence was produced.

| Capability | Generic DOCX (this project) | Docentric AX target |
| --- | --- | --- |
| OOXML package structure | Implemented and structurally inspected (required entries, no macros/OLE) | Not attempted |
| Rendering in Microsoft Word | **Not tested** by this repository | Not tested |
| Docentric tagging vocabulary | Not emitted | Not implemented |
| Docentric field/binding syntax | Not emitted (bindings are substituted at compile time) | Not implemented |
| Native template editing in a Docentric designer | Not applicable | Not implemented |
| Dynamics 365 data binding at print time | Not implemented (values are rendered from sample data) | Not implemented |
| Print/PDF output through Docentric | Not implemented | Not implemented |
| Compatibility with a specific AX version | **Unverified** | **Unverified** |
| Automated compatibility test suite | Not available | Not available |

## 7. Evidence required to change the status

A future change must provide all of the following. Partial evidence is insufficient.

1. **Authoritative specification** of the target format: container/package layout, tagging elements or
   fields, binding syntax, required parts/relationships, version differences, and error behaviour.
2. **Permission and environment**: a licensed Docentric AX environment of a named version, with
   permission to use it for testing and to publish results.
3. **Representative inputs**: at least one real (or vendor-sanctioned) DDSP package and one native
   template per supported document class, plus the expected output.
4. **Golden evidence**: for each supported feature, a produced document and the observable proof that
   the target product consumes it correctly (screenshots/reports alone are not enough; include the
   exact steps, versions and configuration).
5. **Independent execution**: the evidence must be reproducible by someone other than the author,
   from a clean checkout, with recorded commands.
6. **Failure-mode evidence**: what happens with unsupported constructs, missing fields, empty
   collections and invalid values. A happy-path-only demonstration does not pass the gate.
7. **Legal review**: no third-party assets, trademarks or confidential material committed; no claim
   beyond what was tested.
8. **Documentation update**: this file, [SRS](SRS.md), README, [API_SPEC](API_SPEC.md) and the
   capability payload updated together, with the supported version range stated explicitly.

## 8. Gate acceptance criteria

The gate can be marked passed only when:

- [ ] the evidence in §7 is complete and linked from this document;
- [ ] an automated compatibility suite runs in CI or a documented reproducible procedure, with a
      recorded pass rate (not "it looked right");
- [ ] unsupported constructs fail with typed errors rather than emitting approximate output;
- [ ] `DocentricAXCompiler.verified_compatibility` is set to `true` only for the tested version range;
- [ ] the capability payload distinguishes `available` (implemented) from `verified` (tested in a
      licensed environment) and both are true only for the tested range;
- [ ] V5 validates against recorded evidence rather than hard-coded `not_tested`;
- [ ] an independent reviewer signs off the evidence.

Until every box is checked, the status remains **blocked/unverified**.

## 9. Explicit non-claims

This project does **not** claim any of the following:

1. That generated documents are Docentric AX templates, or are accepted as such.
2. That generated documents can be opened, edited or rendered by Docentric AX without modification.
3. That any Docentric AX version, service pack or configuration is supported.
4. That the DDSP parser understands the real DDSP format beyond the documented evidence.
5. That the generic DOCX renders identically in Word, LibreOffice, Docentric or a PDF exporter.
6. That mappings from generic constructs to Docentric constructs are correct, complete or stable.
7. That "no macros / no embedded objects / no external relationships" implies product compatibility.
8. That passing V1–V4 in any way predicts V5. V5 is always `not_tested` in this build.
9. That the word `verified` in the capability payload refers to Docentric compatibility. For
   `generic-docx` it means "compiler implemented and package structurally inspected"; for
   `docentric-ax` both flags are `false`.
10. That this project is affiliated with, endorsed by or supported by the vendor of Docentric AX.

## 10. Reporting a compatibility issue

If you observe a problem when using output from this project with a Docentric environment, please
report it as a **compatibility observation**, including:

- the exact project version/commit and compiler target used;
- the Docentric AX version and configuration;
- the input package, IR and produced DOCX (synthetic or redacted data only);
- steps, expected behaviour and observed behaviour;
- whether the claim you are testing is one this project makes (see §9).

Such reports are valuable, but a single observation does not by itself pass the gate. Use the bug
report template in `.github/ISSUE_TEMPLATE/` and state clearly that the report is about an unverified
compatibility observation.

## 11. Change log for this gate

| Date/version | Change |
| --- | --- |
| 0.1.0 | Gate established; path B recorded; adapter unavailable; V5 `not_tested` |
| 0.2.0 | Gate unchanged; documentation and dependency hardening only |
