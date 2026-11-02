# FAQ

**Is this an official Docentric product?**
No. It is an independent open-source project, not affiliated with or endorsed by Docentric.

**Does it produce Docentric AX templates?**
No. It produces generic DOCX documents. Docentric AX output is gated and unverified — see
[Docentric AX Compatibility](Docentric-AX-Compatibility).

**Why not just let the LLM write the document?**
Because an unreviewable binary is not engineering. The model writes a typed plan; deterministic code
validates and executes it. That is what makes the result reviewable, testable and reproducible.

**Do I need an API key to try it?**
No. The `mock` provider runs the whole pipeline offline and deterministically.

**Which models are supported?**
OpenAI, Anthropic and Google Gemini through one gateway. Any model identifier your account can call.

**Is my data sent to a provider?**
Only when you explicitly select a cloud provider. A compact schema fragment and your brief are sent; sample
values are not sent by default. The `mock` provider sends nothing.

**How large a DDSP is supported?**
10 MB upload, 64 MB uncompressed, 512 entries, 10 MB per entry by default; all configurable.

**Can two runs differ?**
No, not for the same IR, schema, sample data and compiler version. Output is byte-identical, which is
asserted by tests.

**What happens if the AI invents a field?**
It is removed by a deterministic repair pass, reported as an `invalid` mapping, and cannot reach the
compiler.

**Does it compute totals or tax?**
No. It binds values that exist in the data source. Business arithmetic belongs upstream.

**Can it edit an existing Word document?**
No. It generates new documents from a plan. Editing existing templates is out of scope.

**Is there authentication?**
Not in the MVP. Deploy behind a gateway or run locally.

**Where are artifacts stored?**
Locally: SQLite for metadata and a file store for artifacts, with a one-hour TTL by default.

**What does `not_tested` mean?**
The check exists but could not be executed in this environment. It is never treated as a pass.

**How do I contribute?**
See [Contributing](Contributing) and the issue templates.

**What if I find a security issue?**
Report it privately per [SECURITY.md](https://github.com/SergeyGer/Docentric-Copilot/blob/main/SECURITY.md).
