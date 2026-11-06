# Template IR v1.1

| Field | Value |
| --- | --- |
| Contract | Template Intermediate Representation, version `1.1` |
| Model | [packages/template-ir/src/docentric_copilot/template_ir/models.py](../packages/template-ir/src/docentric_copilot/template_ir/models.py) |
| Canonical form | [canonical.py](../packages/template-ir/src/docentric_copilot/template_ir/canonical.py) |
| Traversal | [traversal.py](../packages/template-ir/src/docentric_copilot/template_ir/traversal.py) |
| JSON Schema | `docentric-copilot ir-schema` |

All IR models derive from `StrictModel`, which sets `extra="forbid"` (unknown keys fail validation).
The Template IR is the only contract between the AI planning layer and the deterministic execution
layer. It is deliberately narrow:

- no executable code, no raw XPath, no raw OOXML;
- every dynamic reference is a schema path that the validator can resolve;
- every optional feature has a defensive size bound so a hostile or hallucinated document cannot
  exhaust the compiler;
- unknown keys are rejected (`extra="forbid"`), so a model cannot smuggle fields into a document.

## 1. Minimal valid document

A document with only the required fields plus one section. `ir_version`, `kind`, `language`, `target`
and `page` have defaults and may be omitted; `metadata`, `title` and `sections` are required.

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
    "design_style": "modern"
  },
  "sections": [
    {
      "kind": "section",
      "name": "Main",
      "body": [
        {
          "kind": "heading",
          "level": 1,
          "runs": [{ "kind": "text", "text": "Sales Quotation" }]
        },
        {
          "kind": "paragraph",
          "runs": [
            { "kind": "text", "text": "No.: " },
            { "kind": "field", "path": "MainData.Quotation.QuotationId" }
          ]
        }
      ]
    }
  ]
}
```

This document is model-valid. Semantic validity additionally requires that `sales_quotation` exposes
`MainData.Quotation.QuotationId`; otherwise V2 reports `V2-001` and compilation is blocked.

## 2. Root entities

### 2.1 `Document`

| Field | Type | Required | Constraints | Default |
| --- | --- | --- | --- | --- |
| `kind` | literal `"document"` | no | fixed discriminator | `"document"` |
| `ir_version` | literal `"1.1"` | no | current version; `1.0` payloads are migrated | `"1.1"` |
| `title` | string | **yes** | 1–200 chars, must not be blank after trimming | — |
| `language` | string | no | `^[a-z]{2}(-[A-Z]{2})?$`, e.g. `en`, `en-US` | `"en"` |
| `target` | enum | no | `generic-docx` \| `docentric-ax` | `generic-docx` |
| `page` | `PageSettings` | no | see below | A4 portrait, 20 mm margins |
| `metadata` | `DocumentMetadata` | **yes** | see below | — |
| `sections` | array of `Section` | **yes** | 1–10 items | — |

`target` is a *request*, not a capability. `docentric-ax` in the IR enables the target code path, but
the compiler refuses it (see [DOCENTRIC_AX_COMPATIBILITY.md](DOCENTRIC_AX_COMPATIBILITY.md)).

### 2.2 `DocumentMetadata`

| Field | Type | Required | Constraints |
| --- | --- | --- | --- |
| `template_name` | string | **yes** | 1–120 chars, `^[A-Za-z0-9 _\-().]{1,120}$` |
| `source_schema_id` | string | **yes** | 1–120 chars; usually `NormalizedSchema.schema_id` |
| `design_style` | enum | no | `classic` \| `modern` \| `minimal` |
| `intent` | string \| null | no | ≤ 1,000 chars; the requirement text (planner stores it) |
| `generator` | string \| null | no | ≤ 120 chars; for the baseline `heuristic-baseline-v1`, otherwise `provider/model` |
| `notes` | string \| null | no | ≤ 2,000 chars; free-form, never rendered automatically |

`template_name` is used for artifact filenames and core properties; it is not a display title.

### 2.3 `PageSettings`

| Field | Type | Required | Constraints | Default |
| --- | --- | --- | --- | --- |
| `size` | literal | no | `A4` \| `LETTER` | `A4` |
| `orientation` | literal | no | `portrait` \| `landscape` | `portrait` |
| `margin_top_mm` | float | no | 5–60 | `20.0` |
| `margin_right_mm` | float | no | 5–60 | `20.0` |
| `margin_bottom_mm` | float | no | 5–60 | `20.0` |
| `margin_left_mm` | float | no | 5–60 | `20.0` |

Printable width used by V4: A4 = 210 mm, LETTER = 215.9 mm, minus left and right margins.

### 2.4 `Section`

| Field | Type | Required | Constraints | Default |
| --- | --- | --- | --- | --- |
| `kind` | literal `"section"` | no | discriminator | `"section"` |
| `name` | string | **yes** | 1–80 chars, `^[A-Za-z0-9 _\-]{1,80}$`, unique across the document (V1-003) | — |
| `body` | array of `Block` | no | ≤ 500 items; must be non-empty to pass V1-004 | `[]` |
| `header` | array of `Block` \| null | no | ≤ 50 items; only paragraph/heading/image are rendered | `null` |
| `first_page_header` | array of `Block` \| null | no | ≤ 50 items; enables Word `titlePg`; `[]` suppresses the default header on page 1 | `null` |
| `footer` | array of `Block` \| null | no | ≤ 50 items; same restriction | `null` |

Each IR section becomes a Word section on a new page. A `header`/`footer` of `null` inherits the
previous section; an explicit empty list is an empty header/footer. `first_page_header` is evaluated
per section and enables that section's `titlePg`. Preview applies the same inheritance.

## 3. Inline content

`InlineContent` is a discriminated union of `TextRun` and `FieldBinding` on `kind`.

### 3.1 `TextRun`

| Field | Type | Required | Constraints |
| --- | --- | --- | --- |
| `kind` | literal `"text"` | no | discriminator |
| `text` | string | **yes** | ≤ 20,000 chars (`max_text_length` is validated at V1) |
| `style` | `TextStyle` \| null | no | see below |

### 3.2 `FieldBinding`

| Field | Type | Required | Constraints |
| --- | --- | --- | --- |
| `kind` | literal `"field"` | no | discriminator |
| `path` | string | **yes** | dotted path, ≤ 512 chars, `^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$` |
| `label` | string \| null | no | ≤ 200 chars; metadata only, not rendered |
| `format` | `ValueFormat` \| null | no | see §7 |
| `date_pattern` | string \| null | no | 1–40 chars, `^[A-Za-z0-9 \-/:.,]{1,40}$`; only with a date format |
| `currency_code` | string \| null | no | `^[A-Z]{3}$`; required when `format` is `currency` |
| `decimals` | integer \| null | no | 0–6; defaults depend on the format |
| `style` | `TextStyle` \| null | no | run formatting |

Cross-field rules enforced by the model:

- `format: "currency"` requires `currency_code`;
- `date_pattern` is only accepted with `date_short`, `date_long`, `date_iso` or no format;
- a binding must resolve to a **scalar** field (not a collection and not an object) or V2 fails.

### 3.3 `ImageBinding`

| Field | Type | Required | Constraints |
| --- | --- | --- | --- |
| `kind` | literal `"image"` | no | discriminator |
| `source` | enum | no | `schema` (default) or `static` |
| `path` | string | for `source=schema` | dotted path, ≤ 512 chars; empty for a static asset |
| `static_asset` | string \| null | for `source=static` | reviewed asset key `^[a-z0-9][a-z0-9_-]{0,63}$`, never a path |
| `alt_text` | string \| null | no | ≤ 200 chars |
| `width_mm` | float \| null | no | 5–200 |
| `height_mm` | float \| null | no | 5–200 |
| `alignment` | enum \| null | no | `left` \| `center` \| `right` \| `justify` |
| `fallback` | enum | no | `placeholder` (default) \| `blank` \| `alt_text` |
| `preserve_aspect` | bool | no | default `true`; when false, both width and height stretch the image |

The IR never embeds binary payloads. Schema values (base64 or `data:` URI) and compile-time static
assets are decoded with magic-byte validation and a 5 MiB cap. Missing or invalid images follow the
fallback policy without corrupting the DOCX; static assets are supplied through
`CompileOptions.static_assets` and are looked up by key, never by filesystem path.

### 3.4 `TextStyle`

| Field | Type | Required | Constraints |
| --- | --- | --- | --- |
| `bold` | bool \| null | no | — |
| `italic` | bool \| null | no | — |
| `underline` | bool \| null | no | — |
| `font_size_pt` | float \| null | no | 6–72 |
| `color` | string \| null | no | `^#[0-9A-Fa-f]{6}$` |
| `alignment` | enum \| null | no | `left` \| `center` \| `right` \| `justify` |

`null` means "leave the consumer's default unchanged"; it is not the same as `false`.

## 4. Block content

`Block` is a discriminated union on `kind`: `paragraph`, `heading`, `image`, `repeat`, `conditional`,
`table`.

### 4.1 `Paragraph`

| Field | Type | Required | Constraints | Default |
| --- | --- | --- | --- | --- |
| `kind` | literal `"paragraph"` | no | discriminator | `"paragraph"` |
| `runs` | array of `InlineContent` | no | ≤ 200 items | `[]` |
| `style` | `TextStyle` \| null | no | alignment is the only paragraph-level property applied | `null` |
| `space_after_pt` | float \| null | no | 0–48 | `null` |

### 4.2 `Heading`

| Field | Type | Required | Constraints | Default |
| --- | --- | --- | --- | --- |
| `kind` | literal `"heading"` | no | discriminator | `"heading"` |
| `level` | integer | no | 1–3; maps to the Word `Heading N` style | `1` |
| `runs` | array of `InlineContent` | **yes** | 1–50 items | — |
| `style` | `TextStyle` \| null | no | - | `null` |

### 4.3 `Repeat`

| Field | Type | Required | Constraints | Default |
| --- | --- | --- | --- | --- |
| `kind` | literal `"repeat"` | no | discriminator | `"repeat"` |
| `path` | string | **yes** | path to a **collection** node | — |
| `alias` | string | **yes** | `^[a-z][a-z0-9_]{0,31}$`, unique in scope (V3-002) | — |
| `blocks` | array of `Block` | **yes** | 1–200 items | — |
| `max_items` | integer \| null | no | 1–1,000; when omitted the compiler uses `CompileOptions.max_repeat_items` (default 200) | `null` |
| `empty_message` | string \| null | no | ≤ 200 chars; rendered when the collection is empty in sample mode | `null` |

### 4.4 `Conditional`

| Field | Type | Required | Constraints | Default |
| --- | --- | --- | --- | --- |
| `kind` | literal `"conditional"` | no | discriminator | `"conditional"` |
| `condition` | `Expression` | **yes** | see §6 | — |
| `then_blocks` | array of `Block` | **yes** | 1–200 items | — |
| `else_blocks` | array of `Block` \| null | no | ≤ 200 items | `null` |

Without sample data the compiler renders `then_blocks` and emits a warning; the preview does the same
silently. This is a deliberate "show the intended content" behaviour, not an evaluation.

### 4.5 `Table`

| Field | Type | Required | Constraints | Default |
| --- | --- | --- | --- | --- |
| `kind` | literal `"table"` | no | discriminator | `"table"` |
| `columns` | array of `TableColumn` | **yes** | 1–20 items | — |
| `rows` | array of `TableRow` | no | ≤ 500 items; every row must have exactly `len(columns)` cells | `[]` |
| `repeat` | `TableRepeat` \| null | no | requires `row_template` | `null` |
| `row_template` | array of `Cell` \| null | no | ≤ 20 items, exactly `len(columns)`; only valid with `repeat` | `null` |
| `show_header` | bool | no | — | `true` |
| `style` | `TableStyle` \| null | no | — | `null` |

Cross-field rules: row width equality, repeat ↔ row_template coupling, and header row width. These are
enforced by `Table._check_table` and are **not** expressible in the JSON Schema (see §9).

#### `TableColumn`

| Field | Type | Required | Constraints |
| --- | --- | --- | --- |
| `header` | string | **yes** | ≤ 200 chars |
| `width_mm` | float \| null | no | 5–200; if all columns have a width, V4 checks the total against the page |
| `alignment` | enum \| null | no | `left` \| `center` \| `right` \| `justify` |

#### `TableRow` and `Cell`

| Entity | Field | Type | Required | Constraints |
| --- | --- | --- | --- | --- |
| `TableRow` | `cells` | array of `Cell` | **yes** | 1–20 items |
| `Cell` | `blocks` | array of `Block` | no | ≤ 20 items |

#### `TableRepeat`

| Field | Type | Required | Constraints |
| --- | --- | --- | --- |
| `path` | string | **yes** | collection path |
| `alias` | string | **yes** | alias pattern; used by bindings in `row_template` |
| `max_items` | integer \| null | no | 1–1,000 |

#### `TableStyle`

| Field | Type | Required | Constraints | Default |
| --- | --- | --- | --- | --- |
| `borders` | bool | no | selects the `Table Grid` style | `true` |
| `header_background` | string \| null | no | `^#[0-9A-Fa-f]{6}$` | `null` |
| `zebra` | bool | no | alternating shading of repeated rows (`F7F9FC`) | `false` |
| `font_size_pt` | float \| null | no | 6–24; applied to header runs | `null` |

## 5. Path and alias semantics

### 5.1 Paths

A path is an absolute dotted path into the normalized schema, beginning with the section name:
`Section.Element.Child`. Each segment matches `[A-Za-z_][A-Za-z0-9_]*`.

The schema convention (see [DDSP_COMPATIBILITY](DDSP_COMPATIBILITY.md)) is that a node with
`collection = true` describes **one item** of that collection through its children. Therefore:

- `MainData.QuotationLines.Line` is a collection;
- `MainData.QuotationLines.Line.Description` is a scalar *of an item*, not of the document;
- `MainData.Quotation.Customer.Name` is a document-level scalar.

A scalar whose ancestor is a collection may only be bound inside a repeat context whose alias maps to
that collection. Binding it outside is `context_violation` (V2-003 / `V3-004` for conditions), even when
the path exists.

### 5.2 Aliases

`Repeat.alias` (and `Table.repeat.alias`) introduce a lexical name for the collection being iterated.
Inside the block, a binding may use `alias.Field` instead of the absolute path:

```json
{
  "kind": "table",
  "columns": [
    { "header": "Description" },
    { "header": "Amount", "alignment": "right" }
  ],
  "repeat": { "path": "MainData.QuotationLines.Line", "alias": "line", "max_items": 100 },
  "row_template": [
    {
      "blocks": [
        {
          "kind": "paragraph",
          "runs": [{ "kind": "field", "path": "line.Description" }]
        }
      ]
    },
    {
      "blocks": [
        {
          "kind": "paragraph",
          "runs": [
            {
              "kind": "field",
              "path": "line.LineAmount",
              "format": "number",
              "decimals": 2
            }
          ]
        }
      ]
    }
  ]
}
```

Resolution rules:

1. `alias.Field` expands to `<absolute collection path>.Field`.
2. Scopes are lexical and nest; the nearest enclosing repeat wins. An inner repeat may reuse an outer
   alias name only if it shadows it; two repeats in the *same* scope may not share a name (V3-002).
   Conditional branches and independent table cells are separate scopes: an alias may be reused in
   two mutually exclusive branches or two sibling cells. The planner resolves a real same-scope
   conflict deterministically and reports an `alias_conflict_resolved` repair note.
3. Aliases are resolved by the planner, validator, compiler and preview with the same function
   (`schema_resolver.paths.absolute_path` / `Scope`), so the four components cannot disagree.
4. An alias that does not cover the path's ancestor collection does not make the binding legal: the
   resolver checks the schema ancestry, not just the presence of a scope.
5. An alias is not a schema path and may not be used at the document root.

## 6. Expressions

`Expression` is a tiny boolean algebra — not XPath, not a scripting language.

| Field | Type | Required | Constraints |
| --- | --- | --- | --- |
| `operator` | enum | **yes** | one of the twelve operators below |
| `field` | string \| null | per operator | dotted path, ≤ 512 chars; forbidden for `and`/`or`/`not` |
| `value` | bool \| int \| float \| string \| null | per operator | forbidden for logical and null-check operators |
| `operands` | array of `Expression` \| null | per operator | ≤ 16; logical operators only; total depth ≤ 8 |

```json
{
  "operator": "and",
  "operands": [
    { "operator": "equals", "field": "MainData.Quotation.Customer.IsEU", "value": true },
    { "operator": "not_null", "field": "MainData.Quotation.Customer.VatNumber" }
  ]
}
```

### 6.1 Operators

| Operator | Category | Operands | `field` | `value` |
| --- | --- | --- | --- | --- |
| `and` | logical | 2–16 | forbidden | forbidden |
| `or` | logical | 2–16 | forbidden | forbidden |
| `not` | logical | exactly 1 | forbidden | forbidden |
| `equals` | comparison | none | required | required |
| `not_equals` | comparison | none | required | required |
| `greater_than` | comparison | none | required | required |
| `greater_or_equal` | comparison | none | required | required |
| `less_than` | comparison | none | required | required |
| `less_or_equal` | comparison | none | required | required |
| `contains` | comparison | none | required | string |
| `not_null` | null check | none | required | forbidden |
| `is_null` | null check | none | required | forbidden |

Bounds: `field` ≤ 512 chars, `value` is `bool | int | float | str`, `operands` ≤ 16, total nesting
depth ≤ 8. Unknown operators do not exist in the contract.

### 6.2 Evaluation semantics (`docx_compiler/expression.py`)

- `and`: all operands true; `or`: any; `not`: negation of its single operand.
- `not_null` is true when the value is neither `None` nor `""`.
- `is_null` is true when the value is `None` or `""`.
- Comparisons with `None` on either side are **false** (there is no three-valued logic).
- If both sides parse as numbers, numeric comparison is used; if either side is a boolean, both are
  coerced to booleans (`"true"`, `"1"`, `"yes"` are true); otherwise string comparison is used.
- `contains` is a substring test: `right in left`.
- There is no arithmetic, no function call, no regex and no date arithmetic. A business rule that needs
  arithmetic must be encoded in the source data.

## 7. Value formats

Formatting is locale-independent in this build (English-style numbers and dates). The exact behaviour
of `format_value` is:

| `format` | Output | Default `decimals` | Notes |
| --- | --- | --- | --- |
| `plain` (or absent) | `true`/`false` for booleans; integral floats as integers; otherwise `str(value)` | — | `1980.0` renders `1980` |
| `uppercase` | upper-case string | — | |
| `lowercase` | lower-case string | — | |
| `number` | thousands-separated decimal, e.g. `1,980.00` | 2 | uses `,` grouping and `.` decimal |
| `currency` | number followed by a space and the code, e.g. `1,980.00 EUR` | 2 | `currency_code` is required by the model |
| `percent` | value × 100 with `%`, e.g. `0.21` → `21.0%` | 1 | |
| `date_iso` | `2026-03-02` (or `date_pattern`) | — | accepts `date`/`datetime`/ISO string |
| `date_short` | `02 Mar 2026` | — | zero-padded day |
| `date_long` | `2 March 2026` | — | day is **not** zero-padded in this build |
| `boolean_yes_no` | `Yes` / `No` | — | uses Python truthiness: pass real booleans, not `"false"` strings |

`date_pattern` tokens are replaced in this order: `YYYY`, `YY`, `MMMM`, `MMM`, `MM`, `M`, `DD`, `D`.
Example: `DD/MM/YYYY` → `02/03/2026`. Letters that appear literally in a pattern may be replaced; keep
patterns to the allowed character set and the documented tokens.

If a value cannot be parsed for the requested numeric/date format, the raw value is rendered as a
string (and V2 may have already rejected the format/type combination). `None` renders as an empty
string at the formatting layer; the compiler and preview insert a visible `[[path]]` placeholder before
reaching the formatter.

## 8. Canonical serialization and digest

`canonical_ir_json(document)` produces:

- UTF-8 JSON;
- keys sorted lexicographically at every level;
- separators `,` and `:` (no whitespace);
- every field present, including `null` values (`exclude_none=False`);
- enums as their string values.

The IR digest is `sha256(canonical_json)` as lowercase hex. Consequences:

- reordering keys or whitespace in the input does not change the digest;
- adding a field with its default value **does** change the digest, because defaults are serialized;
- the digest is a content fingerprint, not a signature and not an authorisation token.

`load_document` accepts JSON text, UTF-8 bytes or a mapping, migrates the payload (see §9) and
validates it. Validation errors are reported with at most 25 entries of the form
`{"location", "message", "type"}`.

## 9. Versioning and migration policy

- Current version: `IR_SCHEMA_VERSION = "1.1"`; supported set: `{"1.0", "1.1"}`.
- A payload without `ir_version` is assumed to be the current version.
- `1.0 -> 1.1` migration adds `sections[*].first_page_header: null` and the image source/fallback
  defaults; it never changes a binding path or a block.
- The major/minor prefix (`"1.0"` from `"1.0.3"`) is checked against the supported set. Anything else
  raises `IRMigrationError` with code `ir_version_unsupported` (an `InvalidInputError`, HTTP 400).
- Migrations are one-step functions keyed by the *from* version in `MIGRATIONS`; a chain is followed
  until the current version is reached, with a cycle guard of 16 steps. The registry currently
  contains `1.0 -> 1.1`.
- Policy for future changes:
  1. **Backwards-compatible addition** (new optional field with a default): increment the minor
     version, keep reading 1.0, and add a migration that fills the default explicitly.
  2. **Breaking change** (renamed/required field, new block kind): increment the major version, ship a
     new model and refuse the old version with `ir_version_unsupported` until a migration is written.
  3. Never silently coerce, drop or reinterpret a field during migration.
- Because unknown keys are rejected, an old reader will refuse a newer document even within the same
  major version. That is intentional: a silent partial parse is worse than a typed rejection.

## 10. JSON Schema generation

```bash
docentric-copilot ir-schema                      # stdout
docentric-copilot ir-schema --output ir-schema.json
```

`document_json_schema()` returns `Document.model_json_schema(mode="validation")` with:

- `$schema`: `https://json-schema.org/draft/2020-12/schema`
- `$id`: `https://docentric-copilot.dev/schemas/template-ir-v1.0.json`
- `title`: `Template IR v1.0`
- `additionalProperties: false` for every model (from `extra="forbid"`)
- `$defs` with discriminators (`kind`) and `oneOf` unions for blocks and inline content
- `required` at the root: `title`, `metadata`, `sections`

The schema is suitable for provider structured-output bindings and editor autocompletion. It does
**not** encode pydantic model validators, so it cannot express:

- `Table` row/column width coupling and `repeat` ↔ `row_template` coupling;
- expression operator shape rules and depth;
- `currency` → `currency_code` coupling and date-pattern applicability;
- cross-field uniqueness (section names) and all V1–V4 checks.

Always run `load_document` (model + validators) and the validation engine; a schema-valid payload can
still be semantically invalid.

## 11. Limits

IR-level bounds (enforced by pydantic; violation is a validation error):

| Bound | Value |
| --- | --- |
| Sections per document | 10 |
| Blocks per body / header / first-page header / footer | 500 / 50 / 50 / 50 |
| Blocks per repeat / conditional branch | 200 |
| Table rows / columns / cells per row | 500 / 20 / 20 |
| Blocks per table cell | 20 |
| Text run length | 20,000 chars |
| Title / template name / section name | 200 / 120 / 80 chars |
| Expression operands / depth | 16 / 8 |
| Repeat items (`max_items`) | 1,000 |
| Compiler repeat cap (`max_repeat_items`) | 1,000 (default 200; used when the block sets no `max_items`) |

Platform limits (enforced at ingestion/validation, configurable by environment variable):

| Setting | Default | Env var |
| --- | --- | --- |
| `max_ddsp_bytes` | 10 MiB | `DC_MAX_DDSP_BYTES` |
| `max_uncompressed_bytes` | 64 MiB | `DC_MAX_UNCOMPRESSED_BYTES` |
| `max_compression_ratio` | 120 | `DC_MAX_COMPRESSION_RATIO` |
| `max_zip_entries` | 512 | `DC_MAX_ZIP_ENTRIES` |
| `max_xml_nodes` | 250,000 | `DC_MAX_XML_NODES` |
| `max_xml_depth` | 64 | `DC_MAX_XML_DEPTH` |
| `max_schema_nodes` | 5,000 | `DC_MAX_SCHEMA_NODES` |
| `max_ir_blocks` | 5,000 | `DC_MAX_IR_BLOCKS` (API, service and CLI) |
| `max_ir_depth` | 24 | `DC_MAX_IR_DEPTH` (API, service and CLI) |
| `max_text_length` | 20,000 | `DC_MAX_TEXT_LENGTH` |
| `artifact_ttl_seconds` | 3600 | `DC_ARTIFACT_TTL_SECONDS` |

`TemplateService` constructs the validation engine from these settings, so the three IR-related limits
take effect for API and CLI calls that use the service. The bounds in the table above are independent:
the model rejects a 300-column table before the validator ever runs.

## 12. Reserved vocabulary

`docentric_copilot.template_ir.models.DataType` defines `string`, `number`, `boolean`, `date`,
`image`, `collection`, `any`. It documents the normalized-schema type vocabulary; it is **not** a field
of any v1.0 IR entity. Schema node types are strings produced by `ddsp_parser`, and bindings rely on
validator type checks rather than on an IR-level type annotation.
