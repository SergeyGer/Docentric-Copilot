# Glossary

| Term | Meaning |
| --- | --- |
| **DDSP** | Docentric Data Source Package — a container describing a report's data source (schema, sample data, metadata) |
| **DSP** | Data source provider inside D365 F&O |
| **Template IR** | Typed intermediate representation of a document produced by the planner and consumed by the compiler |
| **Binding** | A dynamic reference from the document to a schema path |
| **Alias** | A short name for a collection inside a repeat scope (`line.UnitPrice`) |
| **Collection** | A repeated element; its children describe one item |
| **Expression** | A small typed boolean algebra used for conditions (no XPath, no code) |
| **Compiler** | Deterministic component that turns a validated IR into a document |
| **Generic DOCX** | A standards-compliant DOCX with no vendor-specific tagging |
| **Docentric AX** | The proprietary document automation product for Dynamics 365 F&O |
| **Compatibility gate** | The evidence-based decision point that blocks AX output |
| **`not_tested`** | Validation status meaning “cannot be evaluated here”; never a pass |
| **Golden file** | A reviewed expected artefact used for regression comparison |
| **Canonical JSON** | Sorted-key, whitespace-free serialization used for digests |
| **IR digest** | SHA-256 of the canonical IR |
| **Provider gateway** | The single contract behind OpenAI, Anthropic, Gemini and mock |
| **Baseline planner** | Deterministic, non-LLM planner used offline and as an evaluation control |
| **Artifact TTL** | Retention window after which generated files are deleted |
| **V1–V5** | Structural, semantic, logical, visual and compatibility validation levels |
