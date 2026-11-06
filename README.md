# Docentric Copilot

### Turn a business brief and a data source into a finished, checked document — in minutes.

[![CI](https://github.com/SergeyGer/Docentric-Copilot/actions/workflows/ci.yml/badge.svg)](https://github.com/SergeyGer/Docentric-Copilot/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/SergeyGer/Docentric-Copilot?color=2563eb)](https://github.com/SergeyGer/Docentric-Copilot/releases)
[![License](https://img.shields.io/badge/license-Apache--2.0-2563eb)](LICENSE)
[![Demo video](https://img.shields.io/badge/demo%20video-2%3A46-0f2a54)](docs/media/demo-v4.mp4)
[![Live demo](https://img.shields.io/badge/live%20demo-Streamlit-ff4b4b)](https://docentric-copilot-bqpx8652tmmliwk9c2d5rq.streamlit.app)
[![Docs](https://img.shields.io/badge/documentation-wiki-0f172a)](https://github.com/SergeyGer/Docentric-Copilot/wiki)
[![Compatibility](https://img.shields.io/badge/Docentric%20AX%20compatibility-unverified-d97706)](https://github.com/SergeyGer/Docentric-Copilot/wiki/Docentric-AX-Compatibility)

![Docentric Copilot](docs/assets/social-preview.png)

**Docentric Copilot** is an open-source AI assistant for enterprise document production. You give it a data
source and describe the document you need in plain language. It answers with a finished Word document, a
reviewable plan of every decision it made, and a validation report that tells you exactly what was checked —
and what wasn't.

No designer sessions. No manual field hunting. No surprises in front of a customer.

---

## Configure an AI provider

The deterministic `mock` provider needs no key. To use a real model, create `.env` from the template
and fill in the key:

```bash
cp .env.example .env      # then edit .env
uvicorn docentric_copilot.api.main:app --port 8000
```

`GET /api/v1/providers` reports which providers are configured. `.env` is git-ignored; real
environment variables always override it. Without a key the application keeps working offline.

## Try it now

**[Open the live demo →](https://docentric-copilot-bqpx8652tmmliwk9c2d5rq.streamlit.app)**

The Streamlit demo runs the real pipeline — schema parsing, requirement mapping, validation, DOCX
compilation and revision — on the deterministic provider. No API key, no model calls, nothing to install.

| You can | What you see |
| --- | --- |
| Pick a bundled package | Sales quotation, tax invoice or purchase order with sample data |
| Inspect the plan | Every requirement, its concept, placement and confidence |
| Review a mapping | Nine confirmed bindings and one genuine ambiguity, resolved by you |
| Download the document | A real `.docx`, compiled from the validated template |
| Change it in plain language | A targeted revision with a before/after preview |
| Check the evidence | Validation statuses and the honest `not tested` compatibility note |

Prefer to watch first? **[Watch the 2:46 demo video](docs/media/demo-v4.mp4)** — a typed brief, a live Auto
routing decision, an honest 20-case benchmark, zoomed document checks and revision.

Prefer to run it yourself? `streamlit run streamlit_app.py` serves the same demo locally.

---

## How it works

| Step | You | The Copilot |
| --- | --- | --- |
| **1** | Upload the data source (`.ddsp`) | Shows every available field, type and repeating table |
| **2** | Describe the document in one paragraph | Proposes a complete document structure and links each requirement to a real field |
| **3** | Review the decisions | Explains every choice, flags anything ambiguous, never invents a field |
| **4** | Download | Delivers DOCX + plan + mapping + validation report |

```text
   Your brief                          The Copilot                          Your document
   ──────────                          ───────────                          ─────────────
   "A sales quotation         →   field-by-field plan + checks   →   quotation.docx
    with logo, items,                                                     plan.json
    totals and bank details"                                              validation.html
```

---

## A five-minute result, not a five-day template

![Workspace](docs/assets/workspace-hero.png)

Everything happens in one workspace: the data source, a searchable schema explorer, the brief, the
field-mapping review, five independent validation levels, a live document preview, the download bundle, and
a revision box that produces a new version instead of silently editing a file.

---

## What makes it different

| | |
| --- | --- |
| **It refuses to guess.** | If a field does not exist in your data, it cannot appear in your document. The plan is rejected or the binding is removed and reported — never fabricated. |
| **You can see the reasoning.** | Every requirement maps to a concrete field, with alternatives, a confidence score and the evidence behind the choice. |
| **Documents become testable.** | The same inputs always produce the same file, byte for byte. You can diff, archive and regression-test a document like code. |
| **It is honest about compatibility.** | It tells you plainly what it has verified and what it has not. No green check marks for things nobody tested. |
| **It runs without a cloud.** | A built-in offline assistant produces deterministic results with no API key — perfect for demos, reviews and CI. |
| **You choose the AI.** | OpenAI, Anthropic and Google Gemini are supported behind one interface; nothing is sent anywhere unless you configure it. |

---

## See it

| Schema explorer | Mapping review |
| --- | --- |
| ![Schema explorer](docs/assets/schema-explorer.png) | ![Mapping review](docs/assets/mapping-review.png) |
| **Every field, typed and searchable** — with keyboard navigation and one-click path insertion. | **Every decision, explained** — requirement, chosen field, alternatives and confidence. |

| Validation | Preview |
| --- | --- |
| ![Validation](docs/assets/validation.png) | ![Preview](docs/assets/preview.png) |
| **Five independent checks** — structure, meaning, logic, layout and compatibility, each reported separately. | **See the document before you compile it**, rendered from the real sample data. |

| Download bundle | Revision |
| --- | --- |
| ![Artifacts](docs/assets/artifacts.png) | ![Revision](docs/assets/revision.png) |
| **DOCX plus evidence** — the document, its plan, the mapping and the validation report. | **Change by describing the change** — a new version, a visible diff, and one-click rollback. |

---

## Who it is for

- **Functional consultants** who need a customer-ready document that matches a written requirement.
- **Template designers** who want a correct starting skeleton and a fast review loop.
- **D365 developers** who need document generation inside an automated pipeline.
- **Solution architects** who need one auditable contract across document types.
- **Independent consultants** who need a convincing prototype without a customer environment.

---

## Honest status

> **Docentric AX compatibility is unverified.** This release produces **generic DOCX** documents.
> The engine verifies its own correctness — structure, field bindings, logic and layout — and reports
> Docentric AX compatibility as **not tested**. Compatibility requires an independent verification inside a
> licensed Docentric environment that has not been performed.
> [Read what would change this status →](https://github.com/SergeyGer/Docentric-Copilot/wiki/Docentric-AX-Compatibility)

This is a deliberate product decision, not a missing feature: a beautiful document built on an unverified
assumption is a liability, not a deliverable.

### Reference Template Intelligence — v0.10 P0 status

The reference inspector is static analysis, not a Docentric runtime. The v0.10 P0 increment is
deliberately partial and is reported as such:

| Workstream | Status |
| --- | --- |
| PR-01 baseline docs, corpus manifest and consistency | Done — version strings, feature matrix and changelog now agree |
| PR-02 D365 embedded schema extraction | Done — reads `ProjectData` XSD, `PreviewData` and field metadata with OOXML provenance |
| PR-03 canonical schema and binding resolver | Done — six exact statuses; every `resolved` carries source, path, scope, type and evidence |
| PR-04 gold semantic dataset | Done — 32 versioned cases, ten families, 20/12 calibration/holdout split, deterministic rule pass; single-annotator labels, no independent human double review |
| PR-05 live gold benchmark | Done — 288-run matrix (32 cases × 3 providers × 3 repeats), calibration/holdout separated, cost and error taxonomy; see the [gold report](benchmarks/gold_report.json) |
| Reference → generic Template IR, visual diff, persistence | Implemented P1, partial — see below |
| Docentric AX runtime compatibility | `not_tested` — unchanged |

The D365 adapter does not require a standalone DDSP when the document contains a usable embedded
schema. Absence of evidence is returned as `schema_unavailable`; an unknown or unsupported
construction is never reported as resolved. See
[Reference Templates](docs/REFERENCE_TEMPLATES.md#d365-embedded-schema-and-binding-resolution-v010-p0)
and [ADR-0013](docs/adr/0013-d365-embedded-schema-and-binding-resolution.md).

The gold dataset and its annotation rules are in [GOLD_LABELS](docs/GOLD_LABELS.md); the measured
run is in [EVALUATION §2.7](docs/EVALUATION.md#27-gold-semantic-benchmark-v010-pr-05). The committed
run completed 288/288 planned calls for **$6.8849 verified + $0.2910 estimated = $7.1759**, under the
$10 cap. Recall and coverage were saturated; precision separated the providers (0.226 OpenAI, 0.220
Anthropic, 0.184 Gemini), and semantic pass was 55.2% / 69.8% / 64.6%. The labels were authored by
the implementer and checked by a deterministic rule pass. There is no independent human double
review, so the annotation gate is reported as partial, not passed. The benchmark is synthetic; it is
not Docentric corpus content and it does not change the AX `not_tested` status.

### Reference workflow — v0.11 P1 status (released in 0.11.0)

The v0.11 P1 increment is implemented on top of the same read-only inspector. The distribution
version was `0.11.0`; these changes are now released as `0.12.0`.

| Workstream | Status |
| --- | --- |
| #26 D365 evidence in the unified ReferenceGraph | Done — `schema_source`, `source_id`, `part#xpath` evidence, exact binding status on `resolves_to` edges, evidence coverage and unresolved-by-status summary; synthetic tests plus the v0.12 11-document regression (V012-04) |
| #27 safe Reference → Generic Template IR | Partial — Field, Label, List→Repeat, If, Image; every skip listed; strict/`--allow-unsupported`; generic DOCX target only |
| #28 independent visual reference diff | Done — LibreOffice page rendering, page/blank/ink/shifted-region comparison, `report.json` + safe `report.html`; **not Word fidelity**; real pinned LibreOffice/Poppler CI (V012-07) |
| #29 persistence, reopen and export | Done — local SQLite with a report-specific TTL, delete/retention, JSON/HTML export, web `?id=` reopen and committed Playwright E2E (V012-08/09) |
| #30 hardening and docs | Done for this branch — ADR-0016 (ADR-0015 was already used), CHANGELOG/REFERENCE_TEMPLATES/EVALUATION/wiki/feature status |
| Docentric AX runtime compatibility | `not_tested` — unchanged; `target=docentric-ax` remains fail-closed |

The importer explicitly refuses to guess: unknown, ambiguous, type-mismatched, schema-unavailable
and unsupported constructs become `skipped[]` entries instead of a wrong generic document. The
visual diff reports `renderer_unavailable` rather than a pass or fail when LibreOffice/poppler is
missing. Details and the full partial list:
[Reference Templates](docs/REFERENCE_TEMPLATES.md#what-is-not-implemented-or-only-partial),
[wiki: Safe IR import and visual diff](docs/wiki/Reference-IR-Import-and-Visual-Diff.md) and
[ADR-0016](docs/adr/0016-ir-import-and-visual-diff.md).

### Reference reliability — v0.12 status

v0.12 is a release of **provable reliability**, not new surface area. The full
evidence package is in [RELEASE_EVIDENCE_V0_12](docs/RELEASE_EVIDENCE_V0_12.md).

| V012 ID | Workstream | Status |
| --- | --- | --- |
| V012-01 | Gold dataset audit trail, hashes, consistency report | **Passed** — [GOLD_AUDIT](docs/GOLD_AUDIT.md); AT-07 remains `partial` (owner self-review, no independent human) |
| V012-02 | Full 32 × 3 × 3 semantic benchmark | **Passed** — [BENCHMARKS §10](docs/BENCHMARKS.md#10-v012-full-benchmark-32--3--3-v012-02); 288 runs, 284 completed, 4 technical, 277 semantic passes |
| V012-03 | Image-family expansion | **Deferred** — issue #37, target v0.13 (the v0.12 dataset is frozen for the 288-run benchmark) |
| V012-04 | D365 real-corpus regression | **Passed** — [D365_REGRESSION](docs/D365_REGRESSION.md); 11/11, 246 bindings, 233 resolved, 13 unresolved, stable digests |
| V012-05 | Gemini nested table / Anthropic Repeat alias | **Passed** — [V012-05](docs/V012_05_REGRESSIONS.md); targeted live subset 23/23 evaluable correct, 4 Gemini technical failures |
| V012-06 | Reference → IR table inference | **Deferred** — issue #40, target v0.13 (skips stay explicit) |
| V012-07 | Real LibreOffice/Poppler Visual CI | **Passed** — [VISUAL_CI](docs/VISUAL_CI.md); real renderer, five fixtures, tolerance and artifacts |
| V012-08 | Playwright E2E | **Passed** — [E2E](docs/E2E.md); happy path, negative paths and trace/screenshot probe in CI |
| V012-09 | Report retention/deletion | **Passed** — [REPORT_RETENTION](docs/REPORT_RETENTION.md); 24 h default TTL, DELETE, verified 404 |
| V012-10 | Responsive and release docs | **Passed** — [RESPONSIVE](docs/RESPONSIVE.md); 1280/768/390 px, version/changelog/roadmap/OpenAPI aligned |

Docentric AX runtime compatibility remains **`not_tested`** and is outside the
v0.12 scope. No P1 item is reported as passed without an artifact.

---

## Try it

```bash
git clone https://github.com/SergeyGer/Docentric-Copilot.git
cd Docentric-Copilot
docker compose up --build
```

Then open **http://localhost:3000** — the workspace ships with a synthetic example and an offline assistant,
so it works immediately with no API key and no data leaving your machine.

Prefer the command line?

```bash
pip install -e ".[dev]"
docentric-copilot inspect examples/quotation/sales-quotation.ddsp
docentric-copilot plan --ddsp examples/quotation/sales-quotation.ddsp \
  --prompt-file examples/quotation/prompt.txt --output plan.json
docentric-copilot compile --ddsp examples/quotation/sales-quotation.ddsp \
  --plan plan.json --output quotation.docx
```

More options: [Quick Start](https://github.com/SergeyGer/Docentric-Copilot/wiki/Quick-Start).

### Test the browser flow

The committed Playwright suite drives the real API and web app with synthetic
fixtures — no key, no provider call, no private corpus:

```bash
npm --prefix apps/web ci
.venv/bin/pytest tests/e2e --e2e -q
```

It covers upload → inspect/save → Overview/Controls/Graph/Diff → reload → reopen
→ JSON/HTML export, plus invalid, oversized, missing-report and storage-failure
paths. See [E2E](docs/E2E.md) for ports, debugging and artifacts.


---

## Documentation

The complete documentation lives in the **[project Wiki](https://github.com/SergeyGer/Docentric-Copilot/wiki)**.

| Start with | Then explore |
| --- | --- |
| [Why Docentric Copilot](https://github.com/SergeyGer/Docentric-Copilot/wiki/Why-Docentric-Copilot) | The problem, the principles and what the product refuses to do |
| [Feature Tour](https://github.com/SergeyGer/Docentric-Copilot/wiki/Feature-Tour) | Every screen, with screenshots |
| [Use Cases](https://github.com/SergeyGer/Docentric-Copilot/wiki/Use-Cases) | Quotations, invoices, purchase orders, nested data, multilingual |
| [Quick Start](https://github.com/SergeyGer/Docentric-Copilot/wiki/Quick-Start) | Docker, local CLI and the web workspace |
| [Architecture](https://github.com/SergeyGer/Docentric-Copilot/wiki/Architecture) | How a brief becomes a checked document |
| [API Reference](https://github.com/SergeyGer/Docentric-Copilot/wiki/API-Reference) · [CLI Reference](https://github.com/SergeyGer/Docentric-Copilot/wiki/CLI-Reference) | Automate it |
| [Testing](https://github.com/SergeyGer/Docentric-Copilot/wiki/Testing) · [Benchmarks & Evaluation](https://github.com/SergeyGer/Docentric-Copilot/wiki/Benchmarks-and-Evaluation) | The evidence behind the claims |
| [Security & Threat Model](https://github.com/SergeyGer/Docentric-Copilot/wiki/Security-and-Threat-Model) | How untrusted input and personal data are handled |
| [Roadmap](https://github.com/SergeyGer/Docentric-Copilot/wiki/Roadmap) | What is next, and what is blocked |

---

## Project facts

| | |
| --- | --- |
| **Version** | 0.12.0 |
| **Licence** | Apache-2.0 |
| **Interfaces** | Web workspace · command line · REST API |
| **AI providers** | OpenAI · Anthropic · Google Gemini · offline deterministic assistant |
| **Quality gate** | 541 automated tests · 86% branch coverage (85% gate) · every CI job green |
| **Status** | Working MVP, actively developed |

Docentric Copilot is an independent open-source project. It is not an official Docentric product and is not
endorsed by Docentric.
