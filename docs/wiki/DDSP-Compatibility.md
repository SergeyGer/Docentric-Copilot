# DDSP Compatibility

> What we know about the input format, what the parser guarantees, and what remains unverified.

## What a DDSP is

A **DDSP** (Docentric Data Source Package) is a container that describes a report's data source: an XML
schema, optional sample data and service metadata, organised into sections such as `MainData`, `Parameters`
and `GeneralData`.

The *public* documentation describes this shape, but the exact internal layout, versioning and metadata
semantics are not published. The parser therefore treats a DDSP as **evidence**, not as a fixed format.

## Parser strategy

```text
ZIP container
 ├─ manifest.json (optional)     → format, version, name, locales
 ├─ *.xsd                        → schema (preferred evidence)
 └─ sample.xml / *.xml           → sample data + schema inference when no XSD exists
```

| Evidence available | Result |
| --- | --- |
| XSD + sample | Typed tree from the schema, values coerced from the sample |
| XSD only | Typed tree, no sample data, placeholders on render |
| Sample only | Inferred types and collections, flagged with `SCHEMA006` |
| Manifest | Supplies `schema_id`, version and locales |
| Nothing usable | Structured error, never a fabricated schema |

## What is preserved

- Original field names, dotted paths and nesting.
- Types: `string`, `number`, `boolean`, `date`, `image`, `collection`, `object`.
- Collection cardinality and parent context.
- XML attributes (as node metadata).
- Raw evidence: `xsd:element:…` or `sample:…` source markers per node.

## Safety limits

| Control | Default |
| --- | --- |
| Upload size | 10 MB (`DC_MAX_DDSP_BYTES`) |
| Uncompressed size | 64 MB (`DC_MAX_UNCOMPRESSED_BYTES`) |
| Compression ratio | 120:1 (`DC_MAX_COMPRESSION_RATIO`) |
| ZIP entries | 512 (`DC_MAX_ZIP_ENTRIES`) |
| XML nodes | 250,000 (`DC_MAX_XML_NODES`) |
| XML depth | 64 (`DC_MAX_XML_DEPTH`) |
| Schema nodes | 5,000 (`DC_MAX_SCHEMA_NODES`) |

DTD and entity declarations are rejected outright (`XML001`); the XML parser has external entities,
network access and recovery mode disabled.

## Diagnostics

| Code | Meaning |
| --- | --- |
| `DDSP001` | File exceeds the size limit |
| `DDSP002` | Not a ZIP or XML container |
| `DDSP003` | Too many ZIP entries |
| `DDSP004` | Uncompressed size limit exceeded |
| `DDSP005` | Suspicious compression ratio |
| `DDSP006` | Encrypted entry |
| `DDSP007` | Unsafe entry name |
| `DDSP008` | No XML content |
| `DDSP009` | Nested archive |
| `DDSP010` | Corrupt entry |
| `DDSP011` | File too small |
| `XML001` | DOCTYPE/ENTITY rejected |
| `XML002` | XML syntax error |
| `XML003` / `XML004` | Node / depth limit |
| `SCHEMA001` | No schema declarations |
| `SCHEMA002` | Unsupported type fallback |
| `SCHEMA003` | Duplicate path |
| `SCHEMA004` | Recursive type not expanded |
| `SCHEMA005` | Schema node limit |
| `SCHEMA006` | Schema inferred from sample |
| `SAMPLE001`–`SAMPLE004` | Sample parse, mismatch, truncation, absence |
| `INFO001`–`INFO003` | Sections detected, format detected, image heuristic |

## Synthetic fixtures

No third-party or customer package is shipped. Three examples are generated deterministically by
`scripts/build_examples.py`:

| Package | Highlights |
| --- | --- |
| `examples/quotation/sales-quotation.ddsp` | logo, customer block, line collection, totals, bank details, VAT flag |
| `examples/invoice/sales-invoice.ddsp` | net/tax/gross, due date, reverse charge |
| `examples/purchase-order/purchase-order.ddsp` | vendor block, delivery terms |

Regenerate and verify them with:

```bash
python scripts/build_examples.py          # write
python scripts/build_examples.py --check  # CI: fail if out of date
```

## What remains unverified

- Parsing a **real** DDSP package produced by Docentric.
- Version-specific metadata and locale structures.
- Relationships between a DSP/DDSP and a specific AX release.

These are tracked in the [Roadmap](Roadmap) and are prerequisites for any compatibility statement.
