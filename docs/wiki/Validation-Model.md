# Validation Model

> Five levels, one rule: `not_tested` is never `passed`.

## The levels

| Level | Name | Question | Autonomous |
| --- | --- | --- | --- |
| **V1** | Structural | Is the IR well-formed and within limits? Is the OOXML package valid? | Yes |
| **V2** | Semantic | Does every binding point at a real, scalar, type-compatible field? | Yes |
| **V3** | Logical | Are repeats and conditions coherent and type-correct? | Yes |
| **V4** | Visual | Does the layout fit the page? | Needs sample data + renderer |
| **V5** | Compatibility | Does Docentric AX recognise and execute the output? | Needs a licensed environment |

V1–V3 gate compilation. A plan that fails any of them is never compiled.

## Statuses

| Status | Meaning |
| --- | --- |
| `passed` | All checks in the level succeeded |
| `failed` | At least one error finding |
| `warning` | No errors, at least one warning |
| `skipped` | Not applicable in this run (for example V4 without sample data) |
| `not_tested` | Cannot be evaluated in this environment (V5) |

The report keeps these separate; there is no aggregated “green” that hides a `not_tested`.

## What each level checks

### V1 — Structural
Block count and depth limits, duplicate section names, empty section bodies, text length, required OOXML
package entries, macro payloads, embedded OLE/ActiveX objects, external relationships.

### V2 — Semantic
Every `field` and `image` binding resolves through the alias scope; collection-scoped fields require an
enclosing repeat; format compatibility (`number`/`currency` need numeric fields, date formats need dates,
images need image fields).

### V3 — Logical
Repeat paths must be collections, aliases must be unique, condition fields must exist, boolean comparisons
must target boolean fields, ordering comparisons need comparable types, `contains` needs a string.

### V4 — Visual
Table column widths against page width, when sample data is present. Deliberately shallow: the preview is
not a Word renderer.

### V5 — Compatibility
Always `not_tested` in this build. See [Docentric AX Compatibility](Docentric-AX-Compatibility).

## Report shape

```json
{
  "schema_id": "sales_quotation",
  "target": "generic-docx",
  "ir_digest": "9f8d8ad173de…",
  "checks": [
    { "id": "V2-001", "level": "semantic", "name": "Binding paths exist", "status": "passed", "findings": [] }
  ]
}
```

And the summary contract used by the API:

```json
{
  "structural": "passed",
  "semantic": "passed",
  "logical": "passed",
  "visual": "passed",
  "docentric_compatibility": "not_tested"
}
```

## Rendering

Reports are produced as JSON and as a self-contained HTML document with a compatibility banner. Both are
published as artifacts next to the DOCX.

## Why this matters

Most document generators stop at “the file opened”. This model separates three very different claims:

1. the document is **structurally valid**,
2. the document is **semantically bound to real data**,
3. the document **executes in the target product**.

Only the first two are proven here, and the report says so.
