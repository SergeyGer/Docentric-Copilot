# DDSP Compatibility and Parser Behaviour

| Field | Value |
| --- | --- |
| Scope | How the system reads a DDSP data source package, what is known, what is assumed, what is rejected |
| Parser | [packages/ddsp-parser/src/docentric_copilot/ddsp_parser/](../packages/ddsp-parser/src/docentric_copilot/ddsp_parser/) |
| Status | Evidence-based parser; synthetic fixtures in CI plus a private, untracked reference corpus |

## 1. What "DDSP" means here

A DDSP is the **data source package** consumed by the template pipeline. Two layouts are supported:

1. The reference adapter (`packages/reference-inspector/src/docentric_copilot/reference/ddsp_real.py`)
   recognises the real bare AX 2012 document: root `dsp:dataSourcePackage` in
   `http://schemas.docentric.com/dynamics-ax/data-source-packages`, with `design`, `systemInfo`,
   `labels` and `dataSections`. Each `dataSection` carries an `xs:schema` and optional `dsp:data`
   sample. The adapter maps that layout into the same `NormalizedSchema`; attributes become
   `@Name` leaves, `GeneralData`/`MainData` stay separate sections and unsupported constructs are
   listed explicitly. It is selected by root/namespace, not by file extension.
2. The v0.5 synthetic parser below treats a DDSP as a ZIP container holding some combination of:

- a JSON manifest (`manifest.json`, `ddsp.json` or `metadata.json`);
- one or more XML Schema (XSD) documents;
- one or more sample data XML documents.

The synthetic ZIP description is derived from the packages the project generates, not from an
authoritative published specification. The bare XML layout is observed evidence from a private
reference corpus; no vendor specification was used and no Docentric component was executed.

## 2. Known, assumed and unknown

### 2.1 Known from the implementation and fixtures

| Fact | Evidence |
| --- | --- |
| The parser receives bytes and classifies them by magic bytes | `ddsp_parser/safety.py::classify_container` |
| A ZIP container is expected to be deflate-compressed and unencrypted | `safety.py::read_container`; `scripts/build_examples.py` writes deflate entries |
| A manifest may declare `format`, `format_version`/`version`, `name`, `sections`, `locales` | `ddsp_parser/parser.py::_load_manifest` |
| XSD 1.0 constructs are the primary schema evidence | `ddsp_parser/xsd.py` |
| Sample data can substitute for a missing XSD, with an explicit `SCHEMA006` marker | `ddsp_parser/sampledata.py::infer_sections_from_sample` |
| Sections named `MainData`, `Parameters`, `GeneralData` are conventional hints | `xsd.py::KNOWN_SECTIONS` |
| Path convention is `Section.Element.Child`, a collection node describes one item | `ddsp_parser/models.py` |
| The example packages are synthetic and deterministic | `scripts/build_examples.py`, `examples/*/README.md` |

### 2.2 Assumed (not proven against real packages)

1. A DDSP is always a ZIP (or a bare XML document, supported for convenience).
2. Schema definitions are XSD; no other schema language is recognised.
3. Sample data is well-formed XML whose repeated sibling elements represent collections.
4. Manifest keys are only hints; the parser works without a manifest.
5. Logical sections are the top-level data elements; the parser does not invent a section hierarchy
   beyond what the XSD or sample exposes.

### 2.3 Unknown

- The authoritative DDSP directory layout, manifest schema and version semantics.
- Whether production DDSPs use XSD at all, or additional descriptor files.
- How images, localisations, lookups and multi-company data are represented.
- Whether a DDSP contains pre-existing Docentric tagging metadata, and in what form.
- How real packages handle namespaces, `xs:import`/`xs:include`, substitution groups and wildcards
  (the current parser does not resolve external schema documents).

Because of these unknowns, the parser is deliberately conservative: **it records evidence and reports
what it cannot interpret; it never guesses a field.** If a construct is not recognised, the resulting
schema is smaller and a diagnostic explains why. A smaller correct schema is preferred to a larger
plausible one.

## 3. Parser strategy

```text
bytes
  │
  ├─ size check (min 16 bytes, max DC_MAX_DDSP_BYTES)             DDSP011 / DDSP001
  ├─ classify_container: zip | xml | unknown                      DDSP002
  │
  ├─ ZIP: read_container
  │    ├─ entry count, name safety, encryption, nested archive    DDSP003/007/006/009
  │    ├─ declared size, decompression budget, ratio              DDSP004/005
  │    ├─ CRC/decompression errors                                DDSP010
  │    └─ entries (bytes in memory; nothing written to disk)
  │
  ├─ manifest (first recognised name, ≤ 64 KiB, object)           INFO002 or DDSP002 warning
  │
  ├─ select XML entries (sample-hinted first, then lexical, ≤ 40)
  │    └─ parse with DTD/entity/network disabled, node/depth caps  XML001/XML002/XML003/XML004
  │
  ├─ schema document? → build_sections_from_xsd
  │    └─ no usable XSD → infer_sections_from_sample               SCHEMA001 / SCHEMA006
  │
  ├─ sample data → extract_sample_data + coerce_sample_tree        SAMPLE002/003
  │
  └─ NormalizedSchema (deterministic projection) + diagnostics
```

Selection details that matter for reproducibility:

- `_prioritise` puts entries whose names contain `sample`, `data`, `example` or `demo` first, then
  sorts by name; at most 40 XML documents are examined.
- The first XSD document that produces sections wins. Multiple XSDs are reported (`INFO002`) and the
  remainder ignored.
- If an XML document fails to parse but others succeed, it is skipped with an `XML002` warning. If no
  document can be used, the first parse failure is re-raised with its original code.
- Manifest values are filtered through an allow-list; unknown keys are dropped, not stored.
- A manifest is never trusted for field names: fields come from XSD or sample structure only.

## 4. Container and XML protections

| Protection | Behaviour | Code |
| --- | --- | --- |
| Minimum size | Files < 16 bytes are rejected | `DDSP011` |
| Maximum size | `DC_MAX_DDSP_BYTES`, default 10 MiB | `DDSP001` |
| ZIP entry count | `DC_MAX_ZIP_ENTRIES`, default 512 | `DDSP003` |
| Uncompressed size | `DC_MAX_UNCOMPRESSED_BYTES`, default 64 MiB (declared and actual) | `DDSP004` |
| Compression ratio | `DC_MAX_COMPRESSION_RATIO`, default 120 | `DDSP005` |
| Encrypted entries | Rejected | `DDSP006` |
| Unsafe entry names | Absolute paths, `..`, backslashes, NUL/control chars, > 300 chars | `DDSP007` |
| Nested archives | Entries ending in `.zip`, `.ddsp`, `.7z`, `.rar`, `.gz`, `.tar`, `.bz2`, `.xz` | `DDSP009` |
| Bad ZIP | Not a readable archive | `DDSP002` |
| Decompression/CRC failure | Entry cannot be read | `DDSP010` |
| DOCTYPE / ENTITY | Rejected by pattern before parsing | `XML001` |
| XML parser hardening | `resolve_entities=False`, `no_network=True`, `load_dtd=False`, `dtd_validation=False`, `recover=False`, comments/PIs removed | — |
| Tree size | `DC_MAX_XML_NODES` default 250,000 | `XML003` |
| Tree depth | `DC_MAX_XML_DEPTH` default 64 | `XML004` |
| Malformed XML | `XML002`; secondary documents are skipped with a warning | `XML002` |

Nothing is extracted to disk: entries are read into memory under a shared uncompressed-byte budget.
The suffix list lives in `_NESTED_ARCHIVE_SUFFIXES` in
[safety.py](../packages/ddsp-parser/src/docentric_copilot/ddsp_parser/safety.py).

## 5. XSD mapping

### 5.1 Supported constructs

- top-level `xs:element` declarations, including a wrapper element whose children are the known
  section names;
- inline and named `xs:complexType`, `xs:sequence`, `xs:choice`, `xs:all`;
- `xs:complexContent` / `xs:extension` (attributes and nested elements);
- `xs:attribute` and `xs:attributeGroup` references;
- inline and named `xs:simpleType` with `xs:restriction` (base type resolution, depth-limited), and
  `xs:union` (first member type);
- `minOccurs`/`maxOccurs` for cardinality (`maxOccurs > 1` or `unbounded` ⇒ collection);
- `ref` to a top-level element (resolved recursively);
- namespaced schema documents (the parser matches by namespace URI
  `http://www.w3.org/2001/XMLSchema`, not by prefix).

Not supported: `xs:import`/`xs:include` resolution, substitution groups, wildcards, identity
constraints, notations, `xs:anyType` semantics beyond "string", and cross-document type definitions.
Unsupported *types* degrade to `string` with `SCHEMA002`; unsupported *structure* simply yields a
smaller tree.

### 5.2 Type mapping

| XSD builtin (local name) | Normalized type |
| --- | --- |
| `string`, `normalizedString`, `token`, `language`, `ID`, `IDREF`, `NMTOKEN`, `Name`, `QName`, `duration`, `hexBinary` | `string` |
| `anyURI` | `string`; `image` when the element name matches `logo`/`image`/`photo`/`picture`/`signature`/`thumbnail` (INFO003) |
| `decimal`, `float`, `double`, `integer`, `int`, `long`, `short`, `byte`, `nonNegativeInteger`, `positiveInteger`, `unsigned*` | `number` |
| `boolean` | `boolean` |
| `date`, `dateTime`, `time` | `date` |
| `base64Binary` | `image` |
| anything else | `string` + `SCHEMA002` warning |

The image inference is a heuristic, not a contract: it is reported as `INFO003` so a reviewer can see
why a field became an image. The compiler still validates actual image payloads at render time.

### 5.3 Recursion and budgets

- Recursive type expansion is detected by a `(type, node identity, name)` key; the node is emitted with
  `data_type = "any"` and a `SCHEMA004` warning instead of being expanded.
- Recursion depth is capped at 32.
- The total schema node budget is `DC_MAX_SCHEMA_NODES` (default 5,000); exhaustion produces
  `SCHEMA005` and truncates the remainder.

### 5.4 Sample-data-only inference

When no XSD is present, the first data document is used:

- the root name becomes a section (or its known-section children become sections);
- repeated sibling names become collections; single occurrences are scalars;
- scalar type inference checks **number first**, then boolean (`true/false/yes/no`), then ISO date,
  then string;
- attributes are captured as `SchemaAttribute` entries;
- `SCHEMA006` is always emitted so an inferred schema can never be mistaken for a declared contract;
- inference is bounded by `DC_MAX_SCHEMA_NODES`.

## 6. Normalized schema shape

`NormalizedSchema` (see [models.py](../packages/ddsp-parser/src/docentric_copilot/ddsp_parser/models.py)):

| Field | Meaning |
| --- | --- |
| `schema_id` | 1–120 chars, lower-case identifier from the manifest `name` or the filename stem |
| `source` | constant `"docentric-ax-ddsp"` (a label, not a compatibility claim) |
| `format_version` | manifest `format_version` or `version`, ≤ 40 chars |
| `container_format` | `zip`, `xml` |
| `sections` | ≤ 20 `SchemaSection` objects |
| `diagnostics` | ≤ 200 `Diagnostic` records |
| `sample_data_available` | true only when sample values were extracted |
| `locales` | ≤ 50 declared locales (recorded, not used for formatting) |

`SchemaNode` fields: `name`, `path`, `data_type`, `collection`, `required`, `source`, `description`,
`sample_value`, `attributes` (≤ 50), `children` (≤ 500). `SchemaSection`: `name`
(`^[A-Za-z_][A-Za-z0-9_]{0,79}$`), `nodes` (≤ 500), `source`.

The schema index maps every path to its node for O(1) resolution. `digest()` excludes diagnostics, so
cosmetic diagnostic changes do not change the schema digest. `compact_fragment()` produces the
LLM-facing projection: path, type, collection flag and required flag **only** — never sample values.
`sample_value` exists on the normalized model for local preview/review and is not sent to providers by
the planner prompt.

## 7. Diagnostics

All codes are stable and are part of the public contract. Severity is the severity used by the emitter;
some codes can appear with more than one severity (for example `DDSP002` is an error when it prevents
parsing and a warning when it concerns a manifest).

| Code | Typical severity | Emitted by | Meaning |
| --- | --- | --- | --- |
| `DDSP001` | error (exception) | `safety.check_file_size`, upload route | Input exceeds `max_ddsp_bytes` |
| `DDSP002` | error / warning | `safety.read_container`, `parser._load_manifest` | Unknown/unreadable container, or an unusable manifest that was ignored |
| `DDSP003` | error (exception) | `safety.read_container` | Too many ZIP entries |
| `DDSP004` | error (exception) | `safety.read_container` | Declared or actual uncompressed size exceeds the limit |
| `DDSP005` | error (exception) | `safety.read_container` | Suspicious per-entry compression ratio |
| `DDSP006` | error (exception) | `safety.read_container` | Encrypted entry |
| `DDSP007` | error (exception) | `safety.read_container` | Unsafe entry name |
| `DDSP008` | error (exception) | `parser.parse_ddsp` | No XML content / empty container |
| `DDSP009` | error (exception) | `safety.read_container` | Nested archive entry |
| `DDSP010` | error (exception) | `safety.read_container` | Entry could not be decompressed (CRC/bad data) |
| `DDSP011` | error (exception) | `safety.check_file_size` | File smaller than 16 bytes |
| `XML001` | error (exception) | `safety.parse_xml` | DOCTYPE or ENTITY declaration present |
| `XML002` | error (exception) / warning | `safety.parse_xml`, `parser.parse_ddsp` | Malformed XML; secondary documents are skipped with a warning |
| `XML003` | error (exception) | `safety.enforce_tree_limits` | Node count above `max_xml_nodes` |
| `XML004` | error (exception) | `safety.enforce_tree_limits` | Nesting depth above `max_xml_depth` |
| `SCHEMA001` | error | `_select_sections`, `xsd.build_sections_from_xsd` | No usable XSD section could be built |
| `SCHEMA002` | warning | `xsd.map_builtin_type`, `xsd._build_node` | Unsupported XSD type → `string`; nameless element skipped |
| `SCHEMA003` | warning | `reference.ddsp_real._RealSchemaBuilder._unique_name` | Duplicate declaration path was renamed, never dropped; the synthetic XSD builder does not emit it |
| `SCHEMA004` | warning | `xsd._build_node` | Recursive type not expanded |
| `SCHEMA005` | error | `xsd.XsdToSchema.build` | Schema node budget exhausted |
| `SCHEMA006` | info | `sampledata.infer_sections_from_sample` | Schema inferred from sample data, no XSD |
| `SAMPLE001` | — | — | **Reserved, never emitted in this build** (sample parse error uses `XML002`) |
| `SAMPLE002` | warning / info | `sampledata` | Sample value/type does not match the schema; data root mapped to a single section |
| `SAMPLE003` | info | `sampledata._coerce_scalar` | Sample value truncated to 2,000 characters |
| `SAMPLE004` | info | `parser.parse_ddsp` | Package has no sample data document |
| `INFO001` | info | `xsd._nested_sections` | Sections discovered inside a wrapper element |
| `INFO002` | info | parser | Container/manifest format detected; sample data loaded; multiple XSDs |
| `INFO003` | info | `xsd.map_builtin_type` | Field treated as an image because of its name |

`Diagnostic` records are `{code, severity, message, location}` with severity `error`, `warning` or
`info`. A fatal condition usually raises a `CopilotError` whose `code` is the diagnostic code, and the
collected diagnostics travel in `details.diagnostics` (limited to 50 entries).

## 8. Limits

See [TEMPLATE_IR §11](TEMPLATE_IR.md#11-limits) for the full table and environment variables. The
parsing-relevant subset:

| Setting | Default | Effect |
| --- | --- | --- |
| `DC_MAX_DDSP_BYTES` | 10 MiB | Total input size |
| `DC_MAX_UNCOMPRESSED_BYTES` | 64 MiB | Shared decompression budget |
| `DC_MAX_COMPRESSION_RATIO` | 120 | Per-entry ratio |
| `DC_MAX_ZIP_ENTRIES` | 512 | Entry count |
| `DC_MAX_XML_NODES` | 250,000 | Parsed tree nodes |
| `DC_MAX_XML_DEPTH` | 64 | Parsed tree depth |
| `DC_MAX_SCHEMA_NODES` | 5,000 | Normalized schema nodes |

Additional non-configurable caps: manifest ≤ 64 KiB, at most 40 XML documents analysed, recursion
depth 32, 50 attributes per node, 500 children per node, 20 sections, 200 diagnostics retained in the
model, 2,000 characters per sample value.

## 9. Compatibility statement

- The synthetic parser is **not** a certified DDSP reader. It is covered by synthetic fixtures.
- The reference adapter was exercised statically against six real AX 2012 DDSP documents in a
  private, git-ignored corpus. That is format evidence only: it does not prove runtime behaviour,
  and no Docentric component was installed or executed.
- A successful parse proves only that the bytes matched the rules in this document. It does **not**
  prove that the package is a valid DDSP for any third-party product.
- The `source` field is the literal string `"docentric-ax-ddsp"` for labelling. It is not evidence of
  interoperability. See [DOCENTRIC_AX_COMPATIBILITY.md](DOCENTRIC_AX_COMPATIBILITY.md).

## 10. Adding fixtures (how to extend coverage)

Fixtures must be synthetic. Never commit customer data, third-party templates or proprietary DDSP
packages.

1. **Generate a package deterministically.** Add an entry to `EXAMPLE_SPECS` in
   [scripts/build_examples.py](../scripts/build_examples.py) with an XSD, a sample XML and a prompt;
   run:

   ```bash
   python scripts/build_examples.py
   python scripts/build_examples.py --check   # verifies committed bytes match the generator
   ```

   The generator uses fixed ZIP timestamps and sorted entries, so a fixture change is reviewable as a
   byte diff.
2. **Add parser expectations.** Add a test that asserts the discovered sections, paths, collection
   flags, types, sample coercion and diagnostic codes. The existing parser tests live in
   [tests/unit/test_ddsp_parser.py](../tests/unit/test_ddsp_parser.py); the deterministic ZIP helper is
   in `tests/conftest.py`.
3. **Test hostile variants** for any new container feature: oversized entry, unsafe name, nested
   archive, encrypted entry, DOCTYPE, excessive depth/nodes.
4. **Do not encode assumptions as tests.** If the real layout is unknown, assert the current
   evidence-based behaviour and mark the uncertainty in this document; do not assert a guessed layout.
5. **Update this document** with any newly supported construct, diagnostic behaviour or limit; state
   explicitly whether the evidence is synthetic or from a real package (with permission).

## 11. Open questions

| Question | Why it matters | How it will be resolved |
| --- | --- | --- |
| What is the real DDSP container layout? | Parser selection order and manifest handling | A representative package under NDA/permission, or public documentation |
| Does production DDSP use XSD? Which profile? | XSD subset coverage | Same |
| How are images/localisations represented? | Image bindings and formatting | Same |
| Does a DDSP carry Docentric tagging metadata? | Feasibility of an AX adapter | [DOCENTRIC_AX_COMPATIBILITY](DOCENTRIC_AX_COMPATIBILITY.md) evidence list |
| Which XML namespaces appear in practice? | Namespace-agnostic parsing is implemented, but untested on real data | Fixtures |

Until these are answered, the honest status is: **implemented against synthetic fixtures; unverified
against real DDSP packages.**
