# CLI Reference

> `docentric-copilot` — the same engine as the API, built for scripts, CI and headless machines.

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Success |
| `1` | Validation or processing failure |
| `2` | CLI usage error |
| `3` | Invalid or unsupported input file |
| `4` | Unsupported compilation target |
| `5` | Provider error (missing key, timeout, invalid output) |
| `6` | Not found |

Scripts can rely on these codes; they are part of the contract.

## Commands

### `inspect`

```bash
docentric-copilot inspect examples/quotation/sales-quotation.ddsp [--json] [--paths]
```

Prints schema id, sections, node/scalar/collection counts, depth, sample-data availability and the parser
diagnostics. `--json` emits the normalized schema for automation.

### `plan`

```bash
docentric-copilot plan \
  --ddsp examples/quotation/sales-quotation.ddsp \
  --prompt-file examples/quotation/prompt.txt \
  --output plan.json \
  --mapping mapping.json \
  --provider mock \
  --design-style modern \
  --language en \
  --target generic-docx
```

Writes the Template IR, optionally the mapping report, and prints validation status. Refuses to write an IR
that fails V1–V3.

### `validate`

```bash
docentric-copilot validate --ddsp source.ddsp --plan plan.json \
  --report report.html --json-report report.json
```

Runs V1–V5 against the source schema and sample data. Exits `1` when compilation would be blocked.

### `compile`

```bash
docentric-copilot compile --ddsp source.ddsp --plan plan.json \
  --target generic-docx --output quotation.docx
```

Deterministic, no model calls. Validates first, then compiles and re-validates the produced package.

### `preview`

```bash
docentric-copilot preview --ddsp source.ddsp --plan plan.json --output preview.html
```

Independent HTML rendering with the source's sample data.

### `providers`

```bash
docentric-copilot providers [--json]
```

Shows which providers have credentials configured. Never prints keys.

### `ir-schema`

```bash
docentric-copilot ir-schema --output ir.schema.json
```

Exports the JSON Schema of the current Template IR version.

### `version`

```bash
docentric-copilot version
# docentric-copilot 0.2.0 (IR 1.0)
```

## Secrets

API keys are read from the environment only:

| Provider | Variable |
| --- | --- |
| OpenAI | `OPENAI_API_KEY` |
| Anthropic | `ANTHROPIC_API_KEY` |
| Google Gemini | `GEMINI_API_KEY` or `GOOGLE_API_KEY` |

They are never accepted as arguments, never written to logs, and never returned by the API.

## CI example

```yaml
- name: Generate the quotation template
  run: |
    docentric-copilot plan --ddsp examples/quotation/sales-quotation.ddsp \
      --prompt-file examples/quotation/prompt.txt --output plan.json
    docentric-copilot validate --ddsp examples/quotation/sales-quotation.ddsp --plan plan.json
    docentric-copilot compile --ddsp examples/quotation/sales-quotation.ddsp \
      --plan plan.json --output quotation.docx
```

Because output is deterministic, the artifact can be committed or compared across runs.
