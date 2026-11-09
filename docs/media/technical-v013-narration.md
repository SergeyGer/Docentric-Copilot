# technical narration

## 1. One deterministic core. (19.3s)

The system is built around one deterministic core. A business brief and a DDSP package enter. The parser normalizes the schema. The planner, and only the planner, is inside the narrow AI boundary. It produces a typed document contract, never OOXML.

## 2. The contract has two paths. (15.7s)

The contract then takes two paths: validation and preview. If structural, semantic and logical checks pass, the compiler writes a deterministic DOCX. Preview and DOCX share the same structure, so they cannot drift by design.

## 3. The parser turns a package into a schema. (18.4s)

The parser reads the DDSP package, validates its XML boundaries and normalizes controls into a schema. Types, collection scope and sample values become explicit. Every later stage sees the same normalized view, so a path cannot mean one thing to the planner and another to the compiler.

## 4. A request is a chain of contracts. (19.2s)

A request is a sequence of narrow contracts. The web app, CLI or API calls TemplateService. Planning gets schema evidence and the brief; validation gets the typed template; compilation gets only a validated template and sample data. A blocking report returns without a document.

## 5. Evidence before generation. (13.6s)

In the live demo, the brief is split into requirements. Candidate fields carry type and scope; the reviewer sees confirmed, ambiguous and missing bindings. The planner cannot bind arbitrary strings.

## 6. The preview is an independent rendering. (15.0s)

The preview is not a screenshot of Word. It is an independent renderer that consumes the same template structure. That gives the reviewer a fast, visible check of order, hierarchy and conditional content before downloading the DOCX.

## 7. A small typed document model. (15.9s)

The contract is a small typed model: document, sections, blocks. Tables carry repeated rows, row templates and footer rows. Repeats carry a path and alias; conditions carry typed expressions; images carry source and fallback policy.

## 8. Every block has one legal shape. (21.1s)

Every block has one legal shape. Paragraphs and headings carry runs. Tables own their rows and optional footer rows. Repeats and conditions own nested blocks. Images carry source, fallback and aspect-ratio policy. The validator can check those rules because they are types, not conventions.

## 9. The gate is explicit. (22.9s)

Validation is layered. Structural checks reject malformed IR. Semantic checks reject unknown or incompatible paths. Logical checks enforce collection scope, condition types and image placement. V1 to V3 block compilation. Visual checks use sample data; compatibility with Docentric AX remains a separate untreated gate.

## 10. Compile only after the gate. (16.9s)

After the blocking gate, the visual check uses sample data when it is available. The compatibility level is separate and remains not tested. That distinction matters: a valid generic DOCX is not a claim that the document will run inside a third-party reporting runtime.

## 11. The compiler owns OOXML. (15.6s)

The compiler owns OOXML. It resolves relationships, writes real sections, headers and footers, embeds media and normalizes the ZIP. The output has stable ordering and fixed timestamps, so the same inputs produce the same bytes.

## 12. First-page headers are real parts. (16.3s)

First-page headers are real Word parts. The section sets titlePg and points to a first-page header. Later sections can inherit a header or clear it. That is why the logo appears once, while the company identity stays in the default header.

## 13. Tables are inferred, or refused. (21.2s)

Table inference reads bounded geometry and joins it to schema evidence. It handles static headers, repeated rows, optional conditional cells, footer rows and a tested nested repeat. Merged or ambiguous tables are refused with diagnostics. Images support schema data, static assets, fallback and aspect ratio.

## 14. Seventeen documents, three outcomes. (27.1s)

Reference evaluation is separate from semantic quality. Seventeen official documents parse, sixteen import and fifteen compile. The two residual failures are an unenclosed nested collection and an unsupported-only document. Thirty observed tables are classified: fifteen accepted, fifteen deliberately unsupported, zero silently dropped. The pipeline counts are deliberately separate from the semantic benchmark.

## 15. Quality is measured, not asserted. (25.9s)

The semantic benchmark runs thirty-two cases across three providers and three repeats, with technical failures separated. Two hundred seventy-four runs pass semantically. Precision is ninety-five percent; recall and F1 are higher; ten Gemini structured-output failures remain technical, not semantic. The report keeps the technical and semantic views separate, so a missing structured response cannot inflate quality.

## 16. The proof stops where the evidence stops. (18.8s)

The honest limits: Word for the web still needs a manual browser check; the videos are drafts; AT-07 remains partial because the gold labels lack independent human review; and Docentric AX runtime compatibility is not tested. A deterministic document engine can prove the document, not somebody else's runtime.

## 17. One deterministic core. A narrow AI boundary. (7.9s)

One deterministic core, a narrow AI boundary, and evidence at every step. That is Docentric Copilot.
