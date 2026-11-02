# Why Docentric Copilot

> A business document should be generated from a data contract, not hand-assembled from memory.

## The problem, in one paragraph

Every enterprise document — a quotation, an invoice, a purchase order — is a contract between a data model
and a reader. Producing it today usually means a specialist opens a designer, finds field paths by trial and
error, wires repeating tables by hand, writes a condition expression, and hopes nothing changed downstream.
When the data model evolves, the template quietly breaks, and the first person to notice is the customer who
receives a blank line where a price should be.

AI appears to solve this, until the generated document looks perfect and binds a field that does not exist.

## What we do differently

| Common approach | Docentric Copilot |
| --- | --- |
| The model writes the document directly | The model writes a **typed plan**; deterministic code builds the document |
| A broken binding is discovered at render time | Every binding is resolved against the schema **before** anything is compiled |
| “It rendered, therefore it works” | Five validation levels, with `not_tested` kept distinct from `passed` |
| Output is a binary blob nobody can diff | Output is a canonical JSON **Template IR** plus a deterministic DOCX |
| Compatibility claims are marketing | Compatibility is a gate with named, unfulfilled evidence |

## Five design principles

### 1. Correctness over plausibility

A beautiful document built on a field that does not exist is a defect, not a demo. Unknown paths are
removed by a deterministic repair pass and reported as `invalid` mappings; compilation refuses to proceed
when semantic or logical validation fails.

### 2. Deterministic execution

The language model operates inside a narrow, typed space. Everything downstream — path resolution,
validation, compilation, packaging — is ordinary code that reads no clock and performs no network I/O.
The same inputs produce byte-identical output, which is what makes golden-file testing possible.

### 3. Fail closed

An unsupported target, an unverified adapter or a truncated schema stops the pipeline with a structured
error. There is no “best effort” mode that silently degrades a document.

### 4. Provider independence

OpenAI, Anthropic and Gemini sit behind one gateway contract; a deterministic offline planner (`mock`) can
drive the entire pipeline without a key. Provider differences never leak into the domain model.

### 5. Honest reporting

The report distinguishes what was checked locally from what can only be checked inside a licensed Docentric
environment. `not_tested` is a first-class status and is never rendered as a pass.

## Who benefits

| Role | What changes |
| --- | --- |
| **D365 F&O functional consultant** | Turn a written requirement into a reviewable template plan in minutes. |
| **Template designer** | Start from a correct skeleton instead of a blank page; review bindings, not syntax. |
| **D365 developer** | Generate a document for an existing data source without a designer session. |
| **Solution architect** | Standardise document output across entities with one auditable contract. |
| **Independent consultant** | Prototype a client deliverable on synthetic data, with no environment access. |

## What this project is not

- It is **not** a Word replacement or a layout tool.
- It is **not** a Docentric AX compatibility claim (see [Docentric AX Compatibility](Docentric-AX-Compatibility)).
- It is **not** a service that sends your data to a cloud provider without consent and configuration.
- It is **not** finished: the [Roadmap](Roadmap) lists what is deliberately deferred.
