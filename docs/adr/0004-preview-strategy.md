# ADR-0004: Independent HTML preview instead of a layout emulator

| Field | Value |
| --- | --- |
| Status | Accepted |
| Date | 2026-11-01 |
| Related | [SRS FR-06](../SRS.md), [ARCHITECTURE §11](../ARCHITECTURE.md#11-known-architectural-constraints-and-debt), [THREAT_MODEL T-24](../THREAT_MODEL.md#53-artifacts-and-output) |

## Context

Users need to see what a template will print before compiling and distributing it. Options considered:

1. **No preview** — rely on the DOCX and Word.
2. **Convert the DOCX to PDF** with LibreOffice or a cloud renderer and display it.
3. **Render the IR directly to HTML**, sharing the data/expression/formatting semantics with the
   compiler but not the layout engine.
4. **Run a headless word processor in the browser** (WASM/OnlyOffice-style).

Options 2 and 4 introduce a heavy dependency, non-deterministic or environment-specific rendering, and
a tempting but false claim: "the preview shows what Word will print". They also complicate deployment
(office runtimes, fonts) and the security model.

## Decision

Implement an **independent HTML preview** (`docentric_copilot.preview`) that:

- renders the same block kinds, repeats, conditionals, tables and images;
- reuses `SampleContext`, `evaluate()` and `format_value()` so values and conditions match the compiler;
- escapes all user text, accepts images only as validated `data:` URIs, and references no external
  resource;
- labels itself in the output: "Independent preview · layout differs from Word/Docentric pagination"
  and "Docentric AX compatibility: not verified";
- is served by the API as `text/html` with `nosniff` and a restrictive Content-Security-Policy.

The preview is a **content review tool**, not a rendering guarantee.

## Consequences

**Positive**

- No office runtime, no headless browser, no font dependency; works in CI and offline.
- Data-binding semantics are shared with the compiler, so a wrong binding is visible in the same way.
- The honest label prevents the most dangerous misinterpretation ("it looked fine in the preview").
- Easy to test: HTML is a string, not a rendered page.

**Negative / costs**

- Layout logic exists twice (DOCX renderer and HTML renderer) and can drift. Mitigation: shared
  context/expression/formatting modules and tests for both.
- Pagination, font metrics, hyphenation, page breaks inside tables and print margins are not modelled.
- Users who need a print-accurate preview must open the compiled DOCX in Word/LibreOffice, which the
  project does not automate.
- The HTML surface needs its own security attention (escaping, CSP, image URIs); see THREAT_MODEL.

## Alternatives rejected

- **PDF conversion as preview:** heavy runtime, environment-dependent output, and still not proof of
  Word layout.
- **Screenshot service:** external dependency, data leaves the deployment, no reproducibility.
- **No preview:** users would review only the binary, losing the fast feedback loop.

## Follow-up

- Keep the preview and compiler semantics aligned; extract shared render helpers rather than copying
  logic.
- Add CSP to the HTML artifact `/view` route (currently only the preview endpoint sets it) — tracked as
  residual risk R-04.
- Do not add a "looks like Word" claim anywhere in the UI or documentation.
