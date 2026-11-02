# Use Cases

> Where the engine saves real time, and where it deliberately does not apply.

## Primary scenario — sales quotation

A functional consultant receives a written requirement and a `SalesQuotation.ddsp`.

| Step | Without Copilot | With Copilot |
| --- | --- | --- |
| Find fields | open the data source, search by name | schema explorer with types and paths |
| Design the layout | manual work in a designer | brief in plain language |
| Bind the item table | configure a repeating region by hand | one repeat over a proven collection |
| Add a tax notice | write a condition expression | typed expression, validated for type correctness |
| Review | open the document and eyeball it | mapping report + five validation levels |
| Change request | edit the document, risk drift | new IR version with a structural diff |

Result: a quotation with company logo, customer block, document number and dates, a line-item table, totals,
payment terms, conditional VAT notice and bank details in the footer.

## Additional scenarios covered by the same engine

| Scenario | What it demonstrates |
| --- | --- |
| **Invoice** | net/tax/gross totals, due dates, reverse-charge condition |
| **Purchase order** | vendor block, delivery terms, item table |
| **Nested collections** | orders → lines rendered as nested repeats |
| **Image binding** | company logo embedded from a base64 field |
| **Missing data** | template compiled without sample data, placeholders instead of invented values |
| **Multilingual** | document language metadata and non-ASCII content |

All of these are exercised by the golden-file suite and the three example packages in `examples/`.

## Personas

### Functional consultant
Needs a document that matches the brief, and a review step they can defend in a meeting.
*Use:* web workspace, mapping review, validation report.

### Template designer
Needs a correct skeleton and a fast way to iterate.
*Use:* revision flow, IR diff, download the IR and inspect it.

### D365 developer
Needs automation inside a pipeline.
*Use:* CLI in CI, JSON output, stable exit codes, deterministic artifacts.

### Solution architect
Needs standardisation and auditability.
*Use:* one Template IR contract, canonical JSON, digest, artifact retention policy.

### Independent consultant
Needs a prototype without a customer environment.
*Use:* `mock` provider, synthetic fixtures, Docker Compose, no external services.

## When not to use it

| Situation | Why | Alternative |
| --- | --- | --- |
| You need pixel-perfect Word pagination | The preview is a content preview, not a Word renderer | validate the DOCX in Word |
| You need Docentric AX tagging today | The adapter is gated; compatibility is unverified | [Docentric AX Compatibility](Docentric-AX-Compatibility) |
| Your data source is not DDSP/XML | The parser is evidence-based for DDSP-style packages | extend the parser, see [DDSP Compatibility](DDSP-Compatibility) |
| The document requires computation (sums, tax rules) | The engine binds data; it does not invent business arithmetic | provide computed fields in the data source |
| The brief is a full design specification | The IR models common business layouts, not arbitrary typesetting | extend the IR with a new block kind |
