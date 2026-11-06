# Gold Dataset Audit Trail

> **Status: owner self-review.** No independent human reviewer was involved.
> AT-07 remains **partial**; the deterministic adjudicator is a documented
> proxy, not a second annotator. This document is generated from
> `benchmarks/gold_adjudication_log.json`; edit the log, not this file.

## Pinned identity

| Field | Value |
| --- | --- |
| Dataset file | `benchmarks/gold_cases.json` |
| Dataset version | `2.0.0` |
| Dataset schema | `gold-cases/v2` |
| Dataset SHA-256 | `8489e4c07f9a8c87e76c0e7fa4a7da8c7f9d6ec0ca0b04eb36cfcd4fe003fd4b` |
| Canonical cases SHA-256 | `a36cf286c0c8cad59a4e770927488f6d5a931d2d2423740277d5c7a3c77943ed` |
| Audit log SHA-256 | `d7437a63b43252e2391a01d608fdd9ccda262ec6adbeee88c4c56063a2be84b2` |
| Manifest SHA-256 | `1c21bbb7102d2012582fff14449b1ae68975cd03107b32561af991302d7defb4` |
| Audit date | 2026-11-06 |
| Reviewer | dataset owner (implementer) (owner self-review) |
| Independent human review | **not performed** |
| AT-07 | **partial** |

## Summary

| Metric | Value |
| --- | --- |
| Cases audited | 32 |
| Requirement labels audited | 98 |
| Expected blocks audited | 26 |
| `reviewed_by_owner` | 14 |
| `no_change` | 18 |
| `unresolved` | 0 |
| Clarifications recorded | 14 |
| Label corrections | 0 |

Every case carries an explicit audit status. A missing entry is a
consistency error, not an implicit pass.

## Case audit

| # | Case | Family | Audit status | Change type | Req. | Decision |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `po-flat-order-identity` | flat_fields | no_change | no_change | 2 | Deterministic adjudication reproduced 2 requirement label(s) and 0 expected block(s); case agreement=agree. Self-review by the dataset owner; no independent human review… |
| 2 | `po-flat-vendor-identity` | flat_fields | reviewed_by_owner | clarification | 3 | Deterministic adjudication reproduced 3 requirement label(s) and 0 expected block(s); case agreement=agree. Interpretation recorded; the dataset labels themselves are un… |
| 3 | `po-flat-commercial-terms` | flat_fields | no_change | no_change | 4 | Deterministic adjudication reproduced 4 requirement label(s) and 0 expected block(s); case agreement=agree. Self-review by the dataset owner; no independent human review… |
| 4 | `po-image-logo-header` | images | reviewed_by_owner | clarification | 2 | Deterministic adjudication reproduced 2 requirement label(s) and 1 expected block(s); case agreement=agree. Interpretation recorded; the dataset labels themselves are un… |
| 5 | `po-collection-line-items` | collections | no_change | no_change | 5 | Deterministic adjudication reproduced 5 requirement label(s) and 2 expected block(s); case agreement=agree. Self-review by the dataset owner; no independent human review… |
| 6 | `po-collection-line-summary` | collections | no_change | no_change | 2 | Deterministic adjudication reproduced 2 requirement label(s) and 2 expected block(s); case agreement=agree. Self-review by the dataset owner; no independent human review… |
| 7 | `po-multilingual-de` | multilingual | reviewed_by_owner | clarification | 3 | Deterministic adjudication reproduced 3 requirement label(s) and 0 expected block(s); case agreement=agree. Interpretation recorded; the dataset labels themselves are un… |
| 8 | `po-multilingual-fr` | multilingual | reviewed_by_owner | clarification | 3 | Deterministic adjudication reproduced 3 requirement label(s) and 0 expected block(s); case agreement=agree. Interpretation recorded; the dataset labels themselves are un… |
| 9 | `po-footer-vendor-scope` | forbidden_scope | reviewed_by_owner | clarification | 2 | Deterministic adjudication reproduced 2 requirement label(s) and 0 expected block(s); case agreement=agree. Interpretation recorded; the dataset labels themselves are un… |
| 10 | `po-ambiguous-supplier-contact` | ambiguous | no_change | no_change | 1 | Deterministic adjudication reproduced 1 requirement label(s) and 0 expected block(s); case agreement=agree. Self-review by the dataset owner; no independent human review… |
| 11 | `so-flat-quotation-identity` | flat_fields | no_change | no_change | 3 | Deterministic adjudication reproduced 3 requirement label(s) and 0 expected block(s); case agreement=agree. Self-review by the dataset owner; no independent human review… |
| 12 | `so-flat-invoice-identity` | flat_fields | no_change | no_change | 3 | Deterministic adjudication reproduced 3 requirement label(s) and 0 expected block(s); case agreement=agree. Self-review by the dataset owner; no independent human review… |
| 13 | `so-image-logo-footer` | images | reviewed_by_owner | clarification | 3 | Deterministic adjudication reproduced 3 requirement label(s) and 1 expected block(s); case agreement=agree. Interpretation recorded; the dataset labels themselves are un… |
| 14 | `so-image-logo-header-invoice` | images | reviewed_by_owner | clarification | 2 | Deterministic adjudication reproduced 2 requirement label(s) and 1 expected block(s); case agreement=agree. Interpretation recorded; the dataset labels themselves are un… |
| 15 | `so-collection-wide-lines` | collections | no_change | no_change | 4 | Deterministic adjudication reproduced 4 requirement label(s) and 2 expected block(s); case agreement=agree. Self-review by the dataset owner; no independent human review… |
| 16 | `so-long-table-all-columns` | long_tables | no_change | no_change | 12 | Deterministic adjudication reproduced 12 requirement label(s) and 2 expected block(s); case agreement=agree. Self-review by the dataset owner; no independent human revie… |
| 17 | `so-long-table-40-rows` | long_tables | no_change | no_change | 4 | Deterministic adjudication reproduced 4 requirement label(s) and 2 expected block(s); case agreement=agree. Self-review by the dataset owner; no independent human review… |
| 18 | `so-long-table-long-descriptions` | long_tables | no_change | no_change | 3 | Deterministic adjudication reproduced 3 requirement label(s) and 2 expected block(s); case agreement=agree. Self-review by the dataset owner; no independent human review… |
| 19 | `so-multilingual-de` | multilingual | reviewed_by_owner | clarification | 4 | Deterministic adjudication reproduced 4 requirement label(s) and 0 expected block(s); case agreement=agree. Interpretation recorded; the dataset labels themselves are un… |
| 20 | `so-ambiguous-vat-number` | ambiguous | reviewed_by_owner | clarification | 1 | Deterministic adjudication reproduced 1 requirement label(s) and 0 expected block(s); case agreement=agree. Interpretation recorded; the dataset labels themselves are un… |
| 21 | `cc-nested-service-tasks` | nested_lists | no_change | no_change | 4 | Deterministic adjudication reproduced 4 requirement label(s) and 3 expected block(s); case agreement=agree. Self-review by the dataset owner; no independent human review… |
| 22 | `cc-nested-task-effort` | nested_lists | no_change | no_change | 4 | Deterministic adjudication reproduced 4 requirement label(s) and 3 expected block(s); case agreement=agree. Self-review by the dataset owner; no independent human review… |
| 23 | `cc-nested-service-amounts` | nested_lists | no_change | no_change | 4 | Deterministic adjudication reproduced 4 requirement label(s) and 3 expected block(s); case agreement=agree. Self-review by the dataset owner; no independent human review… |
| 24 | `cc-conditional-eu-vat` | conditions | reviewed_by_owner | clarification | 2 | Deterministic adjudication reproduced 2 requirement label(s) and 0 expected block(s); case agreement=agree. Interpretation recorded; the dataset labels themselves are un… |
| 25 | `cc-conditional-reverse-charge` | conditions | no_change | no_change | 3 | Deterministic adjudication reproduced 3 requirement label(s) and 0 expected block(s); case agreement=agree. Self-review by the dataset owner; no independent human review… |
| 26 | `cc-conditional-eu-vat-invoice` | conditions | reviewed_by_owner | clarification | 3 | Deterministic adjudication reproduced 3 requirement label(s) and 0 expected block(s); case agreement=agree. Interpretation recorded; the dataset labels themselves are un… |
| 27 | `adv-missing-requisition-number` | missing | reviewed_by_owner | clarification | 2 | Deterministic adjudication reproduced 2 requirement label(s) and 0 expected block(s); case agreement=agree. Interpretation recorded; the dataset labels themselves are un… |
| 28 | `adv-missing-customer-po-reference` | missing | no_change | no_change | 2 | Deterministic adjudication reproduced 2 requirement label(s) and 0 expected block(s); case agreement=agree. Self-review by the dataset owner; no independent human review… |
| 29 | `adv-ambiguous-address` | ambiguous | reviewed_by_owner | clarification | 1 | Deterministic adjudication reproduced 1 requirement label(s) and 0 expected block(s); case agreement=agree. Interpretation recorded; the dataset labels themselves are un… |
| 30 | `adv-forbidden-customer-bank` | forbidden_scope | reviewed_by_owner | clarification | 2 | Deterministic adjudication reproduced 2 requirement label(s) and 0 expected block(s); case agreement=agree. Interpretation recorded; the dataset labels themselves are un… |
| 31 | `adv-forbidden-company-as-customer` | forbidden_scope | no_change | no_change | 2 | Deterministic adjudication reproduced 2 requirement label(s) and 0 expected block(s); case agreement=agree. Self-review by the dataset owner; no independent human review… |
| 32 | `adv-collection-forbidden-columns` | collections | no_change | no_change | 3 | Deterministic adjudication reproduced 3 requirement label(s) and 2 expected block(s); case agreement=agree. Self-review by the dataset owner; no independent human review… |

## Interpretation decisions

Clarifications keep the authored labels and record an interpretation rule.
They are not label corrections; `before` and `after` are identical for every
entry in this version.

### `po-flat-vendor-identity`

Deterministic adjudication reproduced 3 requirement label(s) and 0 expected block(s); case agreement=agree. Interpretation recorded; the dataset labels themselves are unchanged. The gold guard is stricter than the independent derivation: GeneralData.Company.Name. Retained author scope guard(s) 'GeneralData.Company.Name'; the independent pass did not derive them and they forbid wrong-scope bindings, so the safer label is kept rather than loosened. Self-review by the dataset owner; no independent human review was performed.

Case note: The company name is the deliberate wrong-scope alternative for the vendor name.

### `po-image-logo-header`

Deterministic adjudication reproduced 2 requirement label(s) and 1 expected block(s); case agreement=agree. Interpretation recorded; the dataset labels themselves are unchanged. The gold guard is stricter than the independent derivation: MainData.PurchaseOrder.Vendor.Name. Retained author scope guard(s) 'MainData.PurchaseOrder.Vendor.Name'; the independent pass did not derive them and they forbid wrong-scope bindings, so the safer label is kept rather than loosened. Self-review by the dataset owner; no independent human review was performed.

Case note: An image block and a scalar in the header; the vendor name is the wrong-scope trap.

### `po-multilingual-de`

Deterministic adjudication reproduced 3 requirement label(s) and 0 expected block(s); case agreement=agree. Interpretation recorded; the dataset labels themselves are unchanged. The gold guard is stricter than the independent derivation: GeneralData.Company.Name. Retained author scope guard(s) 'GeneralData.Company.Name'; the independent pass did not derive them and they forbid wrong-scope bindings, so the safer label is kept rather than loosened. Self-review by the dataset owner; no independent human review was performed.

Case note: German brief; schema paths stay English, so the model must translate the concepts, not the paths.

### `po-multilingual-fr`

Deterministic adjudication reproduced 3 requirement label(s) and 0 expected block(s); case agreement=agree. Interpretation recorded; the dataset labels themselves are unchanged. The gold guard is stricter than the independent derivation: GeneralData.Company.Name. Retained author scope guard(s) 'GeneralData.Company.Name'; the independent pass did not derive them and they forbid wrong-scope bindings, so the safer label is kept rather than loosened. Self-review by the dataset owner; no independent human review was performed.

Case note: French brief with one vendor-scope guard.

### `po-footer-vendor-scope`

Deterministic adjudication reproduced 2 requirement label(s) and 0 expected block(s); case agreement=agree. Interpretation recorded; the dataset labels themselves are unchanged. The gold guard is stricter than the independent derivation: GeneralData.Company.Name. Retained author scope guard(s) 'GeneralData.Company.Name'; the independent pass did not derive them and they forbid wrong-scope bindings, so the safer label is kept rather than loosened. Self-review by the dataset owner; no independent human review was performed.

Case note: Footer placement plus a scope guard: the buying company is not the vendor.

### `so-image-logo-footer`

Deterministic adjudication reproduced 3 requirement label(s) and 1 expected block(s); case agreement=agree. Interpretation recorded; the dataset labels themselves are unchanged. The gold guard is stricter than the independent derivation: MainData.Quotation.Customer.Address, MainData.Quotation.Customer.Name. Retained author scope guard(s) 'MainData.Quotation.Customer.Address', 'MainData.Quotation.Customer.Name'; the independent pass did not derive them and they forbid wrong-scope bindings, so the safer label is kept rather than loosened. Self-review by the dataset owner; no independent human review was performed.

Case note: Company identity in the footer; customer identity is forbidden.

### `so-image-logo-header-invoice`

Deterministic adjudication reproduced 2 requirement label(s) and 1 expected block(s); case agreement=agree. Interpretation recorded; the dataset labels themselves are unchanged. The gold guard is stricter than the independent derivation: MainData.Invoice.Customer.Name. Retained author scope guard(s) 'MainData.Invoice.Customer.Name'; the independent pass did not derive them and they forbid wrong-scope bindings, so the safer label is kept rather than loosened. Self-review by the dataset owner; no independent human review was performed.

Case note: Header composition with an image and a scalar; the customer name is the wrong-scope trap.

### `so-multilingual-de`

Deterministic adjudication reproduced 4 requirement label(s) and 0 expected block(s); case agreement=agree. Interpretation recorded; the dataset labels themselves are unchanged. The gold guard is stricter than the independent derivation: MainData.Quotation.Customer.Name. Retained author scope guard(s) 'MainData.Quotation.Customer.Name'; the independent pass did not derive them and they forbid wrong-scope bindings, so the safer label is kept rather than loosened. Self-review by the dataset owner; no independent human review was performed.

Case note: German brief with four concepts and a customer/company guard.

### `so-ambiguous-vat-number`

Deterministic adjudication reproduced 1 requirement label(s) and 0 expected block(s); case agreement=agree. Interpretation recorded; the dataset labels themselves are unchanged. Advisory counterpart guards (not applied): MainData.Quotation.Customer.VatNumber. Self-review by the dataset owner; no independent human review was performed.

Case note: Genuine ambiguity between customer and company VAT numbers; the alternative is accepted, not guessed.

### `cc-conditional-eu-vat`

Deterministic adjudication reproduced 2 requirement label(s) and 0 expected block(s); case agreement=agree. Interpretation recorded; the dataset labels themselves are unchanged. Advisory counterpart guards (not applied): GeneralData.Company.Name. Self-review by the dataset owner; no independent human review was performed.

Case note: The schema has a separate Parameters.ShowVatNotice flag; the prompt conditions on the customer's EU status, so the flag is forbidden.

### `cc-conditional-eu-vat-invoice`

Deterministic adjudication reproduced 3 requirement label(s) and 0 expected block(s); case agreement=agree. Interpretation recorded; the dataset labels themselves are unchanged. Advisory counterpart guards (not applied): GeneralData.Company.VatNumber. Self-review by the dataset owner; no independent human review was performed.

Case note: Conditional VAT rendering on the invoice fixture; the total stays unconditional.

### `adv-missing-requisition-number`

Deterministic adjudication reproduced 2 requirement label(s) and 0 expected block(s); case agreement=agree. Interpretation recorded; the dataset labels themselves are unchanged. Advisory counterpart guards (not applied): GeneralData.Company.Name. Self-review by the dataset owner; no independent human review was performed.

Case note: Unsatisfiable requirement excluded from recall/coverage; hallucinating a path is charged as wrong_binding.

### `adv-ambiguous-address`

Deterministic adjudication reproduced 1 requirement label(s) and 0 expected block(s); case agreement=agree. Interpretation recorded; the dataset labels themselves are unchanged. Advisory counterpart guards (not applied): MainData.Quotation.Customer.Address. Self-review by the dataset owner; no independent human review was performed.

Case note: Ambiguity is explicit in the label; both addresses are accepted alternatives.

### `adv-forbidden-customer-bank`

Deterministic adjudication reproduced 2 requirement label(s) and 0 expected block(s); case agreement=agree. Interpretation recorded; the dataset labels themselves are unchanged. Advisory counterpart guards (not applied): GeneralData.Company.Name. Self-review by the dataset owner; no independent human review was performed.

Case note: The schema's BankDetails belong to the company, not the customer; binding them is a scope error.

## Known ambiguities in the labels

- **`po-flat-order-identity`** — Two scalar identifiers with no ambiguity; the easiest anchor for a purchase-order prompt.
- **`po-ambiguous-supplier-contact`** — Ambiguity resolved by the prompt itself; acceptable alternatives are annotated rather than guessed.
- **`so-flat-invoice-identity`** — Invoice identifier triad; checks date/date disambiguation.
- **`so-ambiguous-vat-number`** — Genuine ambiguity between customer and company VAT numbers; the alternative is accepted, not guessed.
- **`adv-missing-requisition-number`** — Unsatisfiable requirement excluded from recall/coverage; hallucinating a path is charged as wrong_binding.
- **`adv-missing-customer-po-reference`** — A subtler missing field: the only nearby identifier is the invoice number, which is a different concept.
- **`adv-ambiguous-address`** — Ambiguity is explicit in the label; both addresses are accepted alternatives.

These cases encode this project's judgement, including explicit
alternatives and unsatisfiable requirements. They are not a customer's
ground truth and were not validated by an independent human.

## Consistency checks

- [x] dataset SHA-256 and version match the committed dataset
- [x] audit covers all 32 case ids exactly once and in dataset order
- [x] audit status and change type use the documented values
- [x] before/after snapshots and required fields are structurally valid
- [x] every expected and forbidden path exists in the case DDSP schema
- [x] no expected/forbidden path conflicts are present
- [x] every label change carries a rationale and a recorded diff
- [x] the generated report matches the machine-readable audit log
- [x] independent human review is not claimed and AT-07 is partial

## Reproduce

```bash
python benchmarks/gold_audit.py --check
python benchmarks/gold_audit.py --check --json
python benchmarks/adjudicate_labels.py --check
```

The manifest pins the dataset hash, the audit-log hash, the prompt
(`planner-v1`, compact `compact-ir-v2`), planner
`0.12.0`, evaluator `1.0.0` and runner
`1.0.0` versions.

## Limitations

- The reviewer is the dataset owner; this is not independent human review.
- AT-07 remains partial and does not block v0.12 while this audit trail,
  the hashes and the consistency checks are in place.
- The audit checks consistency against the committed DDSP schemas; it does
  not prove that the labels describe every valid business interpretation.
- Docentric AX runtime compatibility remains **not_tested** and is out of
  scope for this audit.
