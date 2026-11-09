# Architecture

> One deterministic core, three interfaces, and a narrow AI boundary.

## Layers

```text
┌───────────────────────────────────────────────────────────────────────┐
│ Interfaces        Next.js workspace · CLI (Typer) · REST API (FastAPI) │
├───────────────────────────────────────────────────────────────────────┤
│ Application       TemplateService: plan · validate · compile · revise  │
├───────────────────────────────────────────────────────────────────────┤
│ Planning          prompt assembly · LLM gateway · mock baseline        │
├───────────────────────────────────────────────────────────────────────┤
│ Contract          Template IR v1.0 · canonical JSON · digest · JSON Schema │
├───────────────────────────────────────────────────────────────────────┤
│ Execution         validator V1–V5 · deterministic DOCX compiler    │
├───────────────────────────────────────────────────────────────────────┤
│ Domain services   DDSP parser · schema resolver · preview renderer    │
├───────────────────────────────────────────────────────────────────────┤
│ Foundation        config · errors · ids · redacted logging · storage   │
└───────────────────────────────────────────────────────────────────────┘
```

**Dependency rule:** arrows point downwards only. `template_ir` never imports the compiler; the compiler may
import `template_ir`. `core` imports nothing from the layers above it.

## Data flow

```mermaid
flowchart LR
  subgraph INPUT["Inputs"]
    DDSP["DDSP package"]
    BRIEF["Business brief"]
  end

  subgraph AI["Narrow AI boundary"]
    PLAN["Planner<br/>LLM or mock"]
  end

  subgraph DET["Deterministic core"]
    PARSE["DDSP parser"]
    SCHEMA["Normalized schema"]
    VALIDATE["Validator<br/>V1-V5"]
    COMPILE["DOCX compiler"]
    PREVIEW["Preview renderer"]
  end

  DDSP --> PARSE
  PARSE --> SCHEMA
  SCHEMA --> PLAN
  BRIEF --> PLAN
  PLAN -->|"Template IR"| IR["Typed document contract"]
  IR --> VALIDATE
  IR --> PREVIEW
  VALIDATE -->|"V1-V3 pass"| COMPILE
  COMPILE --> DOCX["Deterministic DOCX"]
  PREVIEW --> HTML["Independent HTML preview"]

  classDef input fill:#0F172A,stroke:#38BDF8,color:#E2E8F0,stroke-width:2px;
  classDef ai fill:#172554,stroke:#818CF8,color:#E2E8F0,stroke-width:2px;
  classDef det fill:#0B1220,stroke:#22D3EE,color:#E2E8F0,stroke-width:2px;
  classDef contract fill:#1E3A8A,stroke:#93C5FD,color:#FFFFFF,stroke-width:3px;
  classDef output fill:#064E3B,stroke:#34D399,color:#ECFDF5,stroke-width:2px;
  class DDSP,BRIEF input;
  class PLAN ai;
  class PARSE,SCHEMA,VALIDATE,COMPILE,PREVIEW det;
  class IR contract;
  class DOCX,HTML output;
```

The same data flow is rendered for the Technical Deep-Dive video from this
Wiki page by `scripts/render_wiki_diagrams.py`; the video and this diagram must
not diverge.

## Request lifecycle

```mermaid
sequenceDiagram
  autonumber
  actor User
  participant UI as Web / CLI / API
  participant Service as TemplateService
  participant Planner
  participant Validator
  participant Compiler

  User->>UI: brief + DDSP schema
  UI->>Service: plan
  Service->>Planner: schema evidence + brief
  Planner-->>Service: Template IR
  Service->>Validator: validate IR
  Validator-->>Service: report
  alt blocking findings
    Service-->>UI: report, no document
  else V1-V3 pass
    Service->>Compiler: compile IR + sample data
    Compiler-->>Service: DOCX
    Service-->>UI: preview + DOCX + evidence
  end
```

## Package map

| Path | Responsibility |
| --- | --- |
| `packages/ddsp-parser` | Untrusted ZIP/XML ingestion, XSD→schema, sample data, diagnostics |
| `packages/schema-resolver` | Path resolution, alias scopes, candidate search, mapping models |
| `packages/template-ir` | Typed IR, canonical serialization, digest, JSON Schema, traversal |
| `packages/template-validator` | V1–V5 checks and report rendering |
| `packages/docx-compiler` | Deterministic DOCX generation and package normalization |
| `packages/llm-gateway` | Provider contract, OpenAI/Anthropic/Gemini adapters, mock provider |
| `packages/planner` | Prompt construction, baseline planner, repair pass, revisions |
| `packages/renderer` | Independent HTML preview |
| `packages/evaluation` | Metric definitions and evaluation harness |
| `services/api` | FastAPI app, CLI, SQLite storage and artifact store |

## Determinism strategy

| Source of non-determinism | Treatment |
| --- | --- |
| Wall-clock timestamps | Fixed document properties; ZIP entries rewritten with a fixed timestamp |
| ZIP entry order | Sorted on export |
| Random identifiers | Stable relationship ids; no random content inside the package |
| Model temperature | `temperature = 0` by default; the mock planner is fully deterministic |
| Locale | English number/date formatting in the MVP, documented as a limitation |

Verified by a byte-equality test in the compiler suite and by the golden-file corpus.

## Failure philosophy

Every trust boundary fails closed:

| Boundary | Failure behaviour |
| --- | --- |
| Upload | size/entry/ratio/depth limits → structured error |
| XML | DTD/entity declarations rejected (`XML001`), no network, no recovery parsing |
| Planning | unknown fields removed and reported; invalid output triggers a bounded repair attempt |
| Validation | V1–V3 failure blocks compilation |
| Compilation | unknown target → HTTP 409 / exit 4, never a partial document |
| Artifacts | TTL, path validation, digest header, no inline execution |

## Storage

SQLite (metadata: sources, templates, versions, jobs, artifacts) plus a file store for artifacts. Sources and
artifacts expire after a TTL; template versions and job records are retained until the database is removed.

## Extension points

| Want to add… | Touch |
| --- | --- |
| A new block kind | `template_ir/models.py`, validator, compiler, preview |
| A new provider | `llm-gateway/providers.py` + gateway registration |
| A new data format | `ddsp-parser` with a new normalizer, keep `NormalizedSchema` stable |
| A new validation level | `template_validator/engine.py` + report model |
| A new output target | a compiler implementing the `compile()` contract, gated like the AX adapter |

Deeper rationale lives in the ADRs: [0001 Template IR](https://github.com/SergeyGer/Docentric-Copilot/blob/main/docs/adr/0001-template-ir.md),
[0002 LLM/compiler separation](https://github.com/SergeyGer/Docentric-Copilot/blob/main/docs/adr/0002-llm-compiler-separation.md),
[0003 Deterministic DOCX](https://github.com/SergeyGer/Docentric-Copilot/blob/main/docs/adr/0003-deterministic-docx.md),
[0004 Preview strategy](https://github.com/SergeyGer/Docentric-Copilot/blob/main/docs/adr/0004-preview-strategy.md),
[0005 Compatibility gate](https://github.com/SergeyGer/Docentric-Copilot/blob/main/docs/adr/0005-docentric-compatibility-gate.md),
[0006 Provider gateway](https://github.com/SergeyGer/Docentric-Copilot/blob/main/docs/adr/0006-provider-gateway.md).

## Template IR contract

```mermaid
classDiagram
  class Document {
    +metadata
    +sections
  }
  class Section {
    +name
    +body
    +header
    +first_page_header
    +footer
  }
  class Block
  class Paragraph
  class Heading
  class Table {
    +repeat
    +rows
    +row_template
    +footer_rows
  }
  class Repeat {
    +path
    +alias
    +blocks
  }
  class Conditional {
    +condition
    +then_blocks
  }
  class ImageBinding {
    +source
    +static_asset
    +fallback
    +preserve_aspect
  }

  Document "1" --> "*" Section
  Section "1" --> "*" Block
  Block <|-- Paragraph
  Block <|-- Heading
  Block <|-- Table
  Block <|-- Repeat
  Block <|-- Conditional
  Block <|-- ImageBinding
  Repeat "1" --> "*" Block
  Conditional "1" --> "*" Block
```

## Validation ladder

```mermaid
flowchart LR
  IR["Template IR"] --> V1["V1 Structural"]
  V1 --> V2["V2 Semantic"]
  V2 --> V3["V3 Logical"]
  V3 --> GATE{"V1-V3 pass?"}
  GATE -->|"no"| BLOCK["Compilation blocked"]
  GATE -->|"yes"| V4["V4 Visual"]
  V4 --> COMPILE["DOCX compiler"]
  COMPILE --> DOCX["Deterministic DOCX"]
  V5["V5 Compatibility"] -. "not_tested" .-> AX["Docentric AX runtime"]
  V4 -. "sample data" .-> V5
```

V1–V3 block compilation. V4 is visual/layout validation and may be skipped
without sample data. V5 is the Docentric AX compatibility gate and remains
`not_tested`; it is not a generic Word compatibility claim.

## Focused views used in the walkthrough

The data-flow diagram is deliberately repeated as two focused views so a
narration can zoom into planning and compilation without cutting labels. These
views are derived from the same graph above.

```mermaid
flowchart LR
  DDSP["DDSP package"] --> PARSE["DDSP parser"] --> SCHEMA["Normalized schema"]
  BRIEF["Business brief"] --> PLAN["Planner<br/>LLM or mock"]
  SCHEMA --> PLAN
  PLAN -->|"Template IR"| IR["Typed document contract"]
  classDef input fill:#0F172A,stroke:#38BDF8,color:#E2E8F0,stroke-width:2px;
  classDef ai fill:#172554,stroke:#818CF8,color:#E2E8F0,stroke-width:2px;
  classDef contract fill:#1E3A8A,stroke:#93C5FD,color:#FFFFFF,stroke-width:3px;
  class DDSP,BRIEF,SCHEMA input;
  class PLAN ai;
  class IR contract;
```

```mermaid
flowchart LR
  IR["Typed document contract"] --> VALIDATE["Validator<br/>V1-V5"]
  VALIDATE -->|"V1-V3 pass"| COMPILE["DOCX compiler"] --> DOCX["Deterministic DOCX"]
  IR --> PREVIEW["Preview renderer"] --> HTML["Independent HTML preview"]
  classDef contract fill:#1E3A8A,stroke:#93C5FD,color:#FFFFFF,stroke-width:3px;
  classDef det fill:#0B1220,stroke:#22D3EE,color:#E2E8F0,stroke-width:2px;
  classDef output fill:#064E3B,stroke:#34D399,color:#ECFDF5,stroke-width:2px;
  class IR contract;
  class VALIDATE,COMPILE,PREVIEW det;
  class DOCX,HTML output;
```

```mermaid
flowchart LR
  BLOCK["Block"] --> PARA["Paragraph"]
  BLOCK --> HEAD["Heading"]
  BLOCK --> TABLE["Table"]
  BLOCK --> REPEAT["Repeat"]
  BLOCK --> COND["Conditional"]
  BLOCK --> IMAGE["ImageBinding"]
  classDef root fill:#1E3A8A,stroke:#93C5FD,color:#FFFFFF,stroke-width:3px;
  classDef leaf fill:#0F172A,stroke:#38BDF8,color:#E2E8F0,stroke-width:2px;
  class BLOCK root;
  class PARA,HEAD,TABLE,REPEAT,COND,IMAGE leaf;
```

```mermaid
flowchart LR
  IR["Template IR"] --> V1["V1 Structural"] --> V2["V2 Semantic"] --> V3["V3 Logical"] --> GATE{"V1-V3 pass?"}
  GATE -->|"no"| BLOCK["Compilation blocked"]
  GATE -->|"yes"| V4["V4 Visual"]
  classDef check fill:#0F172A,stroke:#38BDF8,color:#E2E8F0,stroke-width:2px;
  classDef stop fill:#450A0A,stroke:#F87171,color:#FEE2E2,stroke-width:2px;
  class IR,V1,V2,V3,V4 check;
  class GATE,BLOCK stop;
```

```mermaid
flowchart LR
  V4["V4 Visual<br/>sample data"] --> COMPILE["DOCX compiler"] --> DOCX["Deterministic DOCX"]
  V5["V5 Compatibility"] -. "not_tested" .-> AX["Docentric AX runtime"]
  classDef check fill:#0F172A,stroke:#38BDF8,color:#E2E8F0,stroke-width:2px;
  classDef output fill:#064E3B,stroke:#34D399,color:#ECFDF5,stroke-width:2px;
  classDef stop fill:#450A0A,stroke:#F87171,color:#FEE2E2,stroke-width:2px;
  class V4,COMPILE check;
  class DOCX output;
  class V5,AX stop;
```

```mermaid
classDiagram
  direction LR
  class Document {
    +metadata
    +sections
  }
  class Section {
    +name
    +body
    +header
    +first_page_header
    +footer
  }
  class Block
  Document "1" --> "*" Section : contains
  Section "1" --> "*" Block : contains
```
