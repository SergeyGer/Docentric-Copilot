# Template IR

> The Template IR is the contract between the AI planner and the deterministic compiler.
> If it is not in the IR, it does not exist in the document.

## Why a typed IR at all

Asking a model to emit DOCX XML is unreviewable, untestable and unsafe. Asking it to emit a small typed tree
gives us three properties: **reviewable decisions**, **deterministic execution**, and **honest failure**.

## Document structure

```text
Document
├── ir_version       "1.1"
├── title, language, target
├── page             size, orientation, margins
├── metadata         template_name, source_schema_id, design_style, generator
└── sections[]
    ├── name
    ├── body[]       blocks
    ├── header[]     blocks (pages 2+)
    ├── first_page_header[]  page-1-only blocks; null = no titlePg, [] = blank page 1
    └── footer[]     blocks
```

## Block kinds

| Kind | Purpose | Key fields |
| --- | --- | --- |
| `paragraph` | Static text and inline dynamic values | `runs[]`, `style`, `space_after_pt` |
| `heading` | Section titles | `level` 1–3, `runs[]` |
| `image` | Schema or static image | `source`, `path`/`static_asset`, `fallback`, `preserve_aspect`, width/height, `alt_text` |
| `repeat` | Iterate a collection | `path`, `alias`, `blocks[]`, `max_items` |
| `conditional` | Show content when a typed expression holds | `condition`, `then_blocks`, `else_blocks` |
| `table` | Static rows and/or a repeated row template | `columns`, `rows`, `repeat`, `row_template` |

Inline content is deliberately tiny: `text` or `field`. There is no code, no raw XML and no XPath anywhere in
the contract.

## Example

```json
{
  "kind": "document",
  "ir_version": "1.1",
  "title": "Sales Quotation",
  "language": "en",
  "target": "generic-docx",
  "metadata": {
    "template_name": "quotation_template",
    "source_schema_id": "sales_quotation",
    "generator": "heuristic-baseline-v1"
  },
  "sections": [
    {
      "name": "Main",
      "body": [
        { "kind": "heading", "level": 1, "runs": [{ "kind": "text", "text": "Sales Quotation" }] },
        {
          "kind": "table",
          "columns": [
            { "header": "Description", "width_mm": 70 },
            { "header": "Qty", "width_mm": 16 },
            { "header": "Unit price", "width_mm": 28 }
          ],
          "repeat": { "path": "MainData.QuotationLines.Line", "alias": "line" },
          "row_template": [
            { "blocks": [{ "kind": "paragraph", "runs": [{ "kind": "field", "path": "line.Description" }] }] },
            { "blocks": [{ "kind": "paragraph", "runs": [{ "kind": "field", "path": "line.Quantity", "format": "number", "decimals": 0 }] }] },
            { "blocks": [{ "kind": "paragraph", "runs": [{ "kind": "field", "path": "line.UnitPrice", "format": "number", "decimals": 2 }] }] }
          ]
        }
      ]
    }
  ]
}
```

## Paths and repeat aliases

Paths are dotted and rooted at a schema section: `MainData.Quotation.Customer.Name`.

Inside a `repeat` (or a table repeat), the alias introduces a scope. `line.UnitPrice` resolves to
`MainData.QuotationLines.Line.UnitPrice` through the nearest enclosing alias. The validator
**rejects** a collection-scoped field used outside a repeat — a rule that catches the most common
template bug before anything is compiled.

## Typed expressions

Only a small boolean algebra exists:

```json
{
  "operator": "and",
  "operands": [
    { "operator": "equals", "field": "MainData.Quotation.Customer.IsEU", "value": true },
    { "operator": "not_null", "field": "MainData.Quotation.Customer.VatNumber" }
  ]
}
```

Operators: `and`, `or`, `not`, `equals`, `not_equals`, `greater_than`, `greater_or_equal`, `less_than`,
`less_or_equal`, `not_null`, `is_null`, `contains`. Nesting is capped at eight levels. Unknown operators
cannot be represented at all.

## Value formatting

| Format | Example |
| --- | --- |
| `number` | `1,234.50` |
| `currency` | `12.00 EUR` (currency code is literal in the IR) |
| `percent` | `50.0%` |
| `date_iso` | `2026-03-02` |
| `date_short` | `02 Mar 2026` |
| `date_long` | `2 March 2026` |
| `boolean_yes_no` | `Yes` / `No` |
| `uppercase`, `lowercase`, `plain` | text transforms |

`date_pattern` accepts tokens (`YYYY`, `MM`, `DD`, `MMMM`, …), not executable format strings.

## Versioning, canonical form, schema

- `ir_version` is part of the document; 1.0 payloads migrate to 1.1, unsupported versions raise
  `ir_version_unsupported`.
- `first_page_header` enables Word `titlePg`; the compiler writes a separate first-page header part and
  `headerReference type="first"`. The preview selects it only for page 1.
- Image `source=static` uses a reviewed `static_asset` key, never a path; `fallback` is
  `placeholder`, `blank` or `alt_text`. `preserve_aspect` defaults to true.
- A migration registry exists; version 1.0 is the only released schema today.
- Canonical JSON = sorted keys, no insignificant whitespace, UTF-8. The SHA-256 of that string is the
  document digest used in artifacts and golden files.
- The JSON Schema is generated from the models: `docentric-copilot ir-schema --output ir.schema.json`.

## Limits

| Limit | Default | Environment variable |
| --- | --- | --- |
| Blocks per document | 5,000 | `DC_MAX_IR_BLOCKS` |
| Nesting depth | 24 | `DC_MAX_IR_DEPTH` |
| Text run length | 20,000 characters | `DC_MAX_TEXT_LENGTH` |
| Expression nesting | 8 (fixed) | — |
| Repeat items rendered | 200 per repeat (fixed default) | — |

Full model reference: [`packages/template-ir/src/docentric_copilot/template_ir/models.py`](https://github.com/SergeyGer/Docentric-Copilot/blob/main/packages/template-ir/src/docentric_copilot/template_ir/models.py).
