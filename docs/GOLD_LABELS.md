# Gold labels — annotation guide and adjudication record

| Field | Value |
| --- | --- |
| Dataset | [benchmarks/gold_cases.json](../benchmarks/gold_cases.json) |
| Dataset version | `2.0.0` (schema `gold-cases/v2`) |
| Canonical cases SHA-256 | `a36cf286c0c8cad59a4e770927488f6d5a931d2d2423740277d5c7a3c77943ed` |
| Case count | 32 |
| Split | 20 calibration / 12 holdout, fixed before the first live run |
| Rule pass | [benchmarks/gold_dataset.py](../benchmarks/gold_dataset.py) |
| Independent adjudicator | [benchmarks/adjudicate_labels.py](../benchmarks/adjudicate_labels.py) (deterministic proxy, not a human) |
| Adjudication report | [benchmarks/adjudication_report.json](../benchmarks/adjudication_report.json) |
| Runner | [benchmarks/gold_evaluation.py](../benchmarks/gold_evaluation.py) |
| Review status | `adjudicated_proxy`; AT-07 **partial** |
| Related | [EVALUATION](EVALUATION.md), [ADR-0014](adr/0014-gold-dataset-and-reference-benchmark.md), [ADR-0015](adr/0015-label-adjudication-and-candidate-filtering.md) |

This guide describes what a gold label means, how the 32 cases were composed, how the
calibration/holdout split was fixed, and what was and was not reviewed. It is part of the
reproducibility contract: a metric is only comparable when its dataset version and hash are quoted.

The v0.10 full report ([benchmarks/gold_report.json](../benchmarks/gold_report.json), 288 runs) is
preserved as a historical artifact for dataset `1.0.0`. The current v0.11 report is the affected
subset in [benchmarks/gold_report_v011_subset.json](../benchmarks/gold_report_v011_subset.json);
it was generated from dataset `2.0.0` and must not be spliced with the v0.10 aggregate.

## 1. What this dataset is

The gold set is a **semantic** benchmark for the prompt-to-template planner. Each case is a short
business request over a committed synthetic DDSP schema. The expected answer is not a literal
document; it is a set of **concepts** that a correct plan must bind, the schema paths that can
satisfy each concept, the paths that are explicitly wrong for the request, and the structural blocks
that must exist.

The dataset deliberately separates four questions:

| Question | Evidence |
| --- | --- |
| Did the plan bind the right business concepts? | `required_bindings`, `allowed_alternatives`, `forbidden_paths` |
| Did it put them in the right structural place? | `expected_context`, `expected_blocks`, `expected_type` |
| Is the result a technically valid template? | deterministic validation + generic DOCX compilation, reported separately |
| What did the run cost? | verified/estimated/unavailable cost, never an unknown rendered as `$0.00` |

It is **not** a Docentric AX runtime test, a visual-fidelity benchmark, a customer acceptance suite,
or a statistically powered model comparison. The fixtures are synthetic; no Docentric corpus
content, licensed template or vendor artifact is committed.

## 2. Label model

Each case has the following fields:

| Field | Meaning |
| --- | --- |
| `id` | Stable, lower-case case identifier. Never reuse an id for a different prompt. |
| `prompt` | The exact requirement text sent to the planner. Multilingual prompts keep their language. |
| `package` | Relative path to the committed synthetic DDSP fixture. |
| `family` | The primary annotation family (one of the ten families in §4). |
| `category` | The business category used by the specification: `purchase_order`, `sales_order`, `conditional_complex` or `adversarial`. |
| `difficulty` | Author's judgement: `easy`, `medium` or `hard`. Not derived from a model score. |
| `split` | `calibration` or `holdout`. Frozen; see §5. |
| `language` | Prompt language (`en`, `de`, `fr`). The schema paths remain English. |
| `required_bindings` | Concept-level requirements. At least one per case unless the case is block-only. |
| `forbidden_paths` | Paths that a correct answer must not bind for this request. |
| `expected_blocks` | `repeat`, `table`, `conditional` or `image` blocks that must exist. |
| `labels` | Cross-cutting tags. The `family` value must be present. |
| `notes` | Human-readable rationale for the label, including the adjudication decision. |

### 2.1 Required bindings

Every requirement has:

| Field | Meaning |
| --- | --- |
| `id` | Requirement identity, unique within the case. |
| `concept` | Business concept, independent of the planner's own clause ids. It is the anchor used when a plan binds the right idea to the wrong path. |
| `expected_paths` | Absolute schema paths that satisfy the requirement. First choice; at least one is required unless `satisfiable` is false. |
| `allowed_alternatives` | Additional domain-acceptable paths. A match via an alternative is a true positive, not a false positive. |
| `required` | `true` means an unmatched requirement is a false negative. `false` means a miss lowers coverage only. |
| `expected_type` | Optional type check against the schema (`string`, `number`, `boolean`, `date`, `image`). |
| `expected_context` | Optional placement check: `body`, `header`, `footer`, `repeat` or `conditional`. |
| `satisfiable` | `false` marks a request the schema cannot express. Such a requirement is excluded from recall and coverage denominators; a plan that invents a binding for it is charged as `wrong_binding`. |
| `note` | Why this requirement exists, especially for alternatives and unsatisfiable requests. |

Rules:

1. **Annotate concepts, not the planner's clause names.** The same concept may appear in several
   cases or clause ids; the scorer matches by path and by optional concept evidence, not by the
   planner's identifier.
2. **`expected_paths` are absolute and alias-free.** Collection-scoped fields use the full
   `...Line.ItemId` path; the `expected_context` carries the repeat/scope expectation.
3. **Do not force one answer when the business request is genuinely ambiguous.** Put defensible
   paths in `allowed_alternatives` and explain the ambiguity in `note`. If the prompt explicitly
   permits either answer (for example "email or address"), both are acceptable.
4. **Producing two acceptable variants is redundant, not wrong.** Since v0.10 the scorer marks every
   produced path that belongs to a matched requirement's acceptable set as used; it is neither an
   extra true positive nor a false positive. Forbidden paths are never exempted.
5. **Optional requirements are not free passes.** A missing optional requirement still lowers
   coverage; it does not lower recall. Use them only when the business request is genuinely optional.
6. **Unsatisfiable requirements must have no paths.** The deterministic rule pass enforces this. A
   run that binds any path whose concept matches an unsatisfiable requirement is charged with
   `wrong_binding`.

### 2.2 Forbidden paths

`forbidden_paths` are deliberate scope guards. They exist where the schema contains a plausible but
wrong field:

- the company VAT number when the customer VAT number was requested;
- company bank details when the customer's IBAN was requested;
- the company name when the customer name was requested;
- a schema flag (`Parameters.ShowVatNotice`) that is not the condition the prompt describes;
- columns explicitly excluded by the prompt ("only these three columns").

A forbidden hit reduces precision and fails the semantic gate. If a path is both acceptable and
forbidden, the case is invalid; the rule pass rejects it. Forbidden paths must exist in the case's
schema, so a typo cannot silently weaken the guard.

### 2.3 Expected blocks

| Kind | Meaning |
| --- | --- |
| `repeat` | A collection iteration with the given absolute collection path. |
| `table` | A table whose rows repeat over the given collection path. |
| `conditional` | At least one conditional block; the condition expression is scored through the conditional-context requirement. |
| `image` | An image binding at the given path. |

Block paths are checked against the schema: `repeat`/`table` paths must be collection nodes and
`image` paths must have the `image` type. A conditional block must not declare a path, because the
condition is expressed by a requirement with `expected_context: "conditional"`.

### 2.4 Type and context rules

- `string` and `date` are treated as interchangeable by the scorer because providers frequently
  expose ISO dates as strings. All other type mismatches are failures.
- `expected_context: "repeat"` requires the produced binding to be inside a repeat/table row scope.
- `expected_context: "conditional"` requires the binding to be used by a condition expression.
- `body`, `header` and `footer` are placement checks. A missing context is "not checked", not a
  failure; the harness never guesses a placement the IR did not record.
- A collection or object bound where a scalar was requested is charged as `wrong_context`, even if
  the path is otherwise nearby. This is the metric that catches "bind the whole line instead of the
  line's item number".

### 2.5 Provenance and label status

Schema `gold-cases/v2` adds per-label provenance. Every case declares:

| Field | Meaning |
| --- | --- |
| `label_status` | `verified` or `gap`. A `gap` case is excluded from semantic denominators; it is not silently dropped from the run matrix. |
| `provenance` | Case-level `author`, `adjudicator`, `review_status`, `agreement` and a note. |
| `required_bindings[].provenance` | Per-requirement `author`, `adjudicator`, `agreement` (boolean) and a note. |
| `forbidden_provenance` | Per-forbidden-path provenance. `agreement: false` means the author added a scope guard that the independent pass did not derive; it is a documented reviewer note, not a silent rewrite. |
| `block_provenance` | Parallel to `expected_blocks`, with the same author/adjudicator/agreement fields. |
| `image_subtype` | Image-family subtype. All three committed image cases are `company_logo`; product image, image collection and optional image are not covered. |

The dataset-level `provenance` block records `review_status: adjudicated_proxy`,
`human_review: false`, `at07_status: partial`, the adjudicator id and the report path. A v2 dataset
with `human_review: true` fails the rule pass until a real human review exists.

## 3. Ambiguity

Ambiguity is annotated, not hidden. The rules are:

1. If the prompt is genuinely underspecified (for example "show the VAT number" on a document with a
   customer and a company VAT number), list the first-choice path in `expected_paths` and the other
   defensible path in `allowed_alternatives`. Both are true positives.
2. If the prompt explicitly offers a choice ("either the email or the address"), both paths are
   acceptable; one is enough, and producing both is not penalised.
3. If no field can express the request, use `satisfiable: false` rather than inventing a nearby
   field. The missing cases are intentional negative tests, not annotation gaps.
4. If the business answer depends on information the fixture does not contain, the case is rejected
   rather than annotated with a guess. The rule pass cannot detect this; the annotator must.
5. A forbidden path is never used to express ambiguity. Ambiguity widens the acceptable set;
   forbidden scope narrows it.

## 4. Composition

The 32 cases cover the ten families required by PR-04 and the four specification categories.

| Family | Cases | Split (calibration / holdout) |
| --- | ---: | --- |
| `flat_fields` | 5 | 4 / 1 |
| `images` | 3 | 2 / 1 |
| `collections` | 4 | 2 / 2 |
| `nested_lists` | 3 | 2 / 1 |
| `conditions` | 3 | 1 / 2 |
| `missing` | 2 | 1 / 1 |
| `ambiguous` | 3 | 2 / 1 |
| `multilingual` | 3 | 2 / 1 |
| `long_tables` | 3 | 2 / 1 |
| `forbidden_scope` | 3 | 2 / 1 |
| **Total** | **32** | **20 / 12** |

| Category | Cases | Split (calibration / holdout) |
| --- | ---: | --- |
| Purchase order | 10 | 7 / 3 |
| Sales order | 10 | 7 / 3 |
| Conditional / complex | 6 | 3 / 3 |
| Adversarial / negative | 6 | 3 / 3 |

| Difficulty | Cases |
| --- | ---: |
| Easy | 4 |
| Medium | 20 |
| Hard | 8 |

| Language | Cases |
| --- | ---: |
| English (`en`) | 29 |
| German (`de`) | 2 |
| French (`fr`) | 1 |

Both splits contain every family. That is deliberate: a holdout that omits a family cannot detect a
family-specific regression, and a calibration set that omits one cannot be used for tuning that
family. The category split is also stratified (3 holdout cases from each category).

The full case list, prompts and requirements are in the dataset; this guide does not duplicate them.

## 5. Split policy

- The split was fixed **before the first live run** of the gold runner and is stored per case in the
  dataset. The calibration set has 20 cases; the holdout set has 12.
- **Calibration** cases may be used to change prompts, routing, repair logic or decoding settings.
  Any such change must be recorded in the changelog and the next report must name the new commit.
- **Holdout** cases must not be used for prompt, router or model tuning. They are the closest thing
  this project has to an out-of-sample check. If a holdout case is used for debugging, that fact
  must be disclosed in the next report and the case should be treated as calibration from then on.
- Holdout results are reported separately in `gold_report.json` (`by_split.holdout`), the CSV and the
  HTML. An aggregate that mixes calibration and holdout is never the only number shown.
- A split change is a **major** dataset version change (see §8). It invalidates comparison with
  earlier reports and must be called out explicitly.

## 6. Adjudication record — honest version

**No independent human double review was available for this dataset.** The specification asks for
at least two reviewers and an adjudication journal. The project has one implementer; pretending
otherwise would be worse than the limitation. v0.11 adds a **deterministic independent adjudicator**,
but it is explicitly a proxy, not a second person.

What actually happened:

1. The implementer authored the 32 cases and their labels against the synthetic fixtures.
2. A **deterministic rule pass** (`benchmarks/gold_dataset.py --check`) verifies the mechanical
   contract: every path exists in the case's DDSP, types and contexts match the schema, forbidden
   paths are not also expected, block paths are collections/images, the family invariants hold, the
   split sizes and family coverage are exact, and no path points at private corpus material.
3. In v0.11, `benchmarks/adjudicate_labels.py` re-derived each case's required paths, alternatives,
   forbidden guards and blocks from the prompt and schema **without reading the author's answers to
   derive them**. It uses its own bounded lexicon and schema-evidence rules; it does not import the
   planner's candidate-retrieval code, so it is not a circular check of the same path.
4. The adjudicator reproduced **32/32 cases and 98/98 requirement labels** (`agreement_rate: 1.0` in
   [adjudication_report.json](../benchmarks/adjudication_report.json)). It flagged no unresolved
   requirement conflict after two prompt corrections (below). It did report the author's
   forbidden-scope guards as *stricter* than its own derivation in a few cases; those are recorded
   as `gold_additional` notes and deliberately **not** loosened.
5. The adjudicator is deterministic and makes no model calls, but it is **not human review** and its
   lexicon was developed against this fixture set. It cannot establish business correctness or
   generalisation. AT-07 therefore remains **partial**.

Status against the specification: AT-07 is **partial**. The dataset has 32 cases, concept-level
labels, a version, a hash, a fixed split, per-label provenance and an independent deterministic
adjudication, but not independent human double review. Reports must state this; the HTML report
carries the limitation in its Limits section.

### 6.1 Label changes in version 2.0.0

Two genuine annotation errors were found and corrected. Neither change loosens a metric to make a
model look better: both make an unstated requirement explicit.

| Case | v1.0.0 problem | v2.0.0 correction | Why |
| --- | --- | --- | --- |
| `cc-nested-service-tasks` | Prompt did not mention the line description, but the label required it. | Prompt now says "showing the line description". | The expected path is legitimate, but the request must state it. |
| `cc-nested-task-effort` | Prompt said "Show each service line..." while the label required a table block. | Prompt now says "Create a service order table...". | A table requirement must be explicit; the alternative would have been to weaken the block label. |

Everything else in the author's labels was reproduced by the independent pass. The nested-scope
labels (`table` + outer `repeat` + inner `repeat`) are unchanged; a model that uses only a paragraph
repeat still fails the block requirement, as it should.

### 6.2 Image-family decision

The v0.10 report showed a 0% image-family semantic pass for all three providers. Before treating
that as an image-recognition result, v0.11 checked every image case against the fixture:

- All three image cases request the company logo and annotate the same top-level image path,
  `GeneralData.Company.CompanyLogo`, with an `image` block.
- The path exists in the schema and has `data_type: image`; the prompt and block agree.
- The v0.10 raw runs produced the required image binding in **27/27 image runs**. The semantic gate
  failed because the same plans also bound forbidden or unrequested paths (for example the vendor
  or customer name), not because the image path was impossible.

Decision per case: **the label was not wrong and it is not a gap.** All three image cases stay
`label_status: "verified"`, are not excluded from semantic denominators, and are reported in a
separate image scorecard in the v0.11 subset report. In the v0.11 affected subset, the required
image binding was present in **18/18 image runs** and the image family passed **100%** for all three
providers (v0.10: 0%). The 0% was a precision/scope-adherence failure;
the v0.11 candidate filter is the remedy. The remaining image-family gap is coverage: only company
logo is represented; product image, image collection, optional image, a similar text field, a
missing image and a wrong-collection image are not yet cases.

### 6.3 Genuinely contested author calls

| Case(s) | Question | Decision | Why |
| --- | --- | --- | --- |
| `po-ambiguous-supplier-contact` | Is "contact the supplier" the email or the address? | Accept both; email is first choice. | The prompt explicitly allows either channel; penalising the address would encode an arbitrary preference. |
| `so-ambiguous-vat-number` | Whose VAT number? | Accept customer and company VAT numbers. | The prompt does not say; both are defensible on a quotation. |
| `adv-ambiguous-address` | Which address is "at the top"? | Company address first, customer address accepted. | Top-of-document normally means the issuing company, but some layouts put the customer there. |
| `adv-missing-requisition-number` | Should the planner invent a requisition field? | No; unsatisfiable requirement. | The purchase-order schema has no such field. A substitute identifier would be a wrong binding. |
| `adv-missing-customer-po-reference` | Can the invoice number stand in for the customer PO reference? | No; different concept. | The invoice number is the seller's identifier, not the buyer's reference. |
| `adv-forbidden-customer-bank` | Are the schema's bank details the customer's? | No; forbidden. | The fixture's `BankDetails` belong to the selling company. |
| `cc-conditional-eu-vat` | Is `Parameters.ShowVatNotice` the requested condition? | No; forbidden. | The prompt conditions on the customer's EU status, not on a rendering flag. |
| `adv-collection-forbidden-columns` | Are extra line columns harmless? | No; forbidden. | The prompt says "only" three columns; adding warehouse/discount/note is a scope violation. |
| `so-long-table-all-columns` | Twelve required columns is harsh. | Keep all twelve. | The case exists to stress long-table recall; dropping columns would hide the stress. |
| `po-footer-vendor-scope` | Vendor or company identity in the footer? | Vendor only; company name forbidden. | The request is explicitly about the supplier. |

The independent adjudicator reproduced these calls. It also suggested additional counterpart guards
(for example a company name when a customer name was requested) in a few cases; those suggestions
are recorded as advisory notes, not applied automatically. They are a candidate for real human
review, not evidence that the existing guard is wrong.

## 7. Deterministic rule pass

Run:

```bash
.venv/bin/python benchmarks/gold_dataset.py --check
.venv/bin/python benchmarks/gold_dataset.py --check --json
```

The pass checks, among other things:

- `schema == "gold-cases/v2"`, version `2.0.0`, date, case count 32;
- unique ids and required metadata (`prompt`, `package`, `family`, `category`, `difficulty`, `split`,
  `labels`);
- each `required_bindings` entry has a unique id and concept; `expected_paths` and
  `allowed_alternatives` are non-empty where required; unsatisfiable requirements declare no paths;
- every path exists in the case's schema; every `expected_type` is compatible; every `repeat` path is
  under a collection;
- forbidden paths exist and are not also expected;
- block paths exist; table/repeat blocks point at collections; image blocks point at images;
- family invariants: flat fields have no blocks/repeat context; images have an image; collections
  have a table/repeat and repeat bindings; nested lists have a `Tasks.Task` repeat; conditions have a
  conditional block and a conditional-context binding; missing cases have an unsatisfiable
  requirement; ambiguous cases have allowed alternatives; multilingual cases are non-English; long
  tables have a table and at least three columns; forbidden-scope cases have forbidden paths;
- exact family and category counts, split sizes 20/12, and every family represented in both splits;
- no package path is absolute, escapes the repository, or points at `.tools`/corpus material;
- v2 provenance: dataset `human_review: false`, `at07_status: partial`, every case has a valid
  `label_status`, every requirement has author/adjudicator/agreement, forbidden and block provenance
  match their paths, and no dataset claims human dual review.

Run the independent adjudicator as well:

```bash
.venv/bin/python benchmarks/adjudicate_labels.py --write   # write the report
.venv/bin/python benchmarks/adjudicate_labels.py --check   # fail on a requirement conflict
```

The rule pass is intentionally mechanical. It is a guard against typos, stale paths and accidental
split drift, not a substitute for domain review. The adjudicator is an independent deterministic
proxy; it is stronger than the rule pass on business paths, but it is still not a human.

## 8. Versioning and change process

The dataset uses semantic versioning independent of the distribution version:

| Change | Version bump | Required action |
| --- | --- | --- |
| Typo in `notes`, comment or documentation; no label change | Patch (`2.0.x`) | Update the file hash in reports; live results remain comparable. |
| Added case, corrected path, added allowed alternative, changed a difficulty or family | Minor (`2.x.0`) | Re-run the affected cases and publish a new report; quote the new hash. Old and new results are not directly comparable. |
| Moved a case between calibration and holdout, removed a case, changed the scoring contract or the family/category taxonomy | Major (`x.0.0`) | Treat as a new benchmark. Re-run all cases; do not splice old and new aggregates. |

Every change must:

1. update `version` and `created_at` in the dataset, and re-run
   `benchmarks/adjudicate_labels.py --apply` so per-label provenance matches the new content;
2. pass `gold_dataset.py --check`;
3. update this guide if the label rules changed;
4. be committed with the reports generated from the new hash;
5. state in the changelog which results are superseded.

Labels are never edited to make a model look better. If a label is found to be wrong after a run,
the correction and its rationale go in the changelog and the old report stays in git history. This is
the only honest way to keep a benchmark versionable.

## 9. Reporting rules

- Always quote `dataset.version`, the canonical `sha256` and the split. The report writer does this
  automatically; a screenshot or a hand-written table without them is not evidence.
- Calibration and holdout are shown separately. A single mixed percentage is not a result.
- Precision, recall, F1, coverage, type/context correctness and `valid_template_rate` are separate
  metrics. Compilation success is not semantic correctness.
- Costs carry `verified`, `estimated` or `unavailable`. Gemini is unpriced and is reported as
  estimated with the named proxy; it is never `$0.00`.
- The sample is small and the repeats are not a population sample. Reports say "observations, not
  significance" and do not declare a single winner.
- Per-run JSONL stays in the git-ignored `benchmarks/gold_runs.jsonl` (the v0.11 subset uses
  `benchmarks/gold_runs_v011_subset.jsonl`); committed reports contain aggregates only, with no
  prompt text, raw provider output, credentials or corpus content.

### 9.1 v0.11 counters

- **`pass@k`** is computed per `(provider, case)` group: the fraction of groups with at least one
  semantic pass among the first `k` executed repeats. A group with fewer than `k` runs is excluded
  from that `k`'s denominator and the report says so; it is not silently treated as a failure.
  `gap` cases are excluded from both numerator and denominator.
- **`abstention_rate`** is the fraction of executed runs where at least one requirement was returned
  as `needs_review` with **no selected path**. A bound ambiguous alternative is a review row but not
  an abstention; the report also publishes `review_rate` and `review_requirements`.
- **`family_semantic_pass`** reports semantic pass and pass@k per family and provider. The image
  family has its own scorecard so an aggregate cannot hide a family failure.
- **`counters`** publishes planned, executed, skipped, succeeded, failed, valid-template, semantic
  pass, semantic-excluded and abstained runs with two explicit invariants:
  `planned = executed + skipped` and `executed = succeeded + failed`. The v2 report separately names
  `valid_template_runs`; that is not the same counter as a successful run.
- **`governance.at07_status`** is `partial` because `second_human_annotator` is `false` and the
  adjudicator is a deterministic proxy. No report may upgrade it without a real second annotator.
- **`comparison`** (written by `benchmarks/compare_subset.py`) holds the v0.10 → v0.11 before/after
  block for the same 12 cases. It reads the committed v0.10 per-case metrics, states the 3-repeat vs
  2-repeat difference, and records baseline abstention as `not_measured`, not zero.

## 10. Known limitations

- **Single annotator plus a deterministic proxy.** No independent human double review; the v0.11
  adjudicator is deterministic and independent of the planner, but it is not a person. AT-07 stays
  partial; see §6.
- **Synthetic fixtures.** The cases encode this project's judgement on synthetic schemas, not a
  customer's business rules. They do not prove generalisation to real Docentric templates.
- **Small holdout.** Twelve cases cannot support a confidence interval or a claim of significance.
- **Model drift.** Provider model versions change; a report is only reproducible for the recorded
  model id and date.
- **v0.11 subset measurement.** The v0.11 report covers the affected 12 cases × 3 providers × 2
  repeats, not the full 288-run matrix. It is a before/after check on the changed families, not a new
  full ranking. The v0.10 full report remains the only full-matrix artifact.
- **Path-level precision is strict.** Extra bindings that were not requested are false positives even
  when they are harmless to a reader. That is deliberate: the benchmark measures adherence to the
  request, not document aesthetics.
- **Not a Docentric runtime test.** `runtime_compatibility` remains `not_tested` in every report.
