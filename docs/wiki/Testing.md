# Testing

> Full automated suite green in CI, coverage gate 85% on the deterministic core, a committed Playwright E2E suite, and a golden-file corpus that
> compares structure rather than bytes.

## Running the suite

```bash
make test          # pytest
make test-cov      # coverage gate: --cov-fail-under=85
make lint          # ruff check + ruff format --check
make typecheck     # mypy over packages/ and services/
```

Or directly:

```bash
pytest -q
pytest tests/unit -q
pytest tests/integration -q
pytest -k golden -q
```

## Test matrix

| Area | Coverage |
| --- | --- |
| **Parser** | valid, malformed, empty, oversized, encrypted, nested, zip-bomb, XXE, depth/node limits |
| **Schema** | XSD typing, inference from sample data, attributes, recursion, collections, diagnostics |
| **Resolver** | absolute/alias paths, unknown paths, context violations, ambiguity detection |
| **IR** | model validation, expression rules, table shape, migration errors, canonical digest |
| **Planner** | baseline composition, mapping report, repair pass, revisions, budget propagation |
| **Validator** | every level, `not_tested` semantics, package checks (macros, missing entries) |
| **Compiler** | byte-identical output, content assertions, placeholders, images, conditionals, gated target |
| **Preview** | escaping, repeats, conditionals, placeholders, sandboxed HTML |
| **LLM gateway** | adapters via mocked transports, retries, error normalization, budget pre-flight |
| **API** | upload → plan → validate → compile → download, error envelopes, artifact lifecycle |
| **CLI** | every command, JSON output, exit codes |

## Golden files

Eight fixtures (`simple-fields`, `sales-quotation`, `purchase-order`, `nested-list`, `conditional-vat`,
`image-binding`, `missing-data`, `multilingual`) each store:

| File | Content |
| --- | --- |
| `schema.json` | normalized schema |
| `ir.json` | canonical Template IR produced by the baseline planner |
| `mapping.json` | requirement-to-field report |
| `validation.json` | level statuses, findings, package statuses |
| `docx.json` | normalized document structure (paragraphs, tables, header/footer, media, properties) |

DOCX comparison is **structural**: ZIP order, identifiers and metadata legitimately vary, so the test
compares a normalized projection instead of bytes. Compiler determinism is asserted separately by
byte equality in `test_validator_and_compiler.py`.

Regenerate deliberately:

```bash
python -m tests.golden_files.update_golden          # write
python -m tests.golden_files.update_golden --check  # CI guard
```

## Reproducibility guards in CI

| Guard | Command |
| --- | --- |
| Examples are reproducible | `python scripts/build_examples.py --check` |
| Golden files are current | `python -m tests.golden_files.update_golden --check` |
| OpenAPI is current | export + `git diff --exit-code` |
| Coverage gate | `pytest --cov-fail-under=85` |

## What is not covered

| Gap | Status |
| --- | --- |
| Real DDSP packages | No permitted sample available |
| Live LLM provider calls | Adapters tested against mocked HTTP transports |
| Word rendering / pagination | Out of scope for the MVP |
| Docentric AX execution | Blocked by the compatibility gate |
| Browser E2E in CI | Manual Playwright smoke run only |
| UI layouts below 1024 px | Not verified |

## Manual browser smoke test

Performed against a production build with a real API:

1. upload the quotation DDSP → tree, diagnostics and counts render;
2. keyboard navigation and path insertion in the schema tree;
3. plan → mapping rows, validation badges, sandboxed preview;
4. compile → automatic DOCX download (39,749 bytes);
5. revision → version 2, diff summary, load version 1;
6. error path: unsupported file → message, code and details.

Zero console errors; no horizontal overflow at 1024 px.
