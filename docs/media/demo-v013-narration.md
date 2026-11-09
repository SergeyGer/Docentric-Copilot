# demo narration

## 1. A brief is not a document. (22.4s)

A business brief looks simple: a logo, customer and supplier details, line items, totals, payment terms. The hard part is turning it into a Word document that survives the real file. The logo must stay on the first page. Later pages need the company identity, but not the logo again. And every number must come from the right field.

## 2. Start with evidence, not a blank prompt. (15.1s)

Here is the same brief in the live demo. The data source is a DDSP package: typed fields, collections and sample values. The planner is not allowed to invent a field. It can only choose from schema evidence.

## 3. The schema is the source of truth. (17.6s)

The schema is the source of truth. Fields have types, collections have scope, and sample data shows how values are shaped. The planner can search those candidates, but the resolver decides whether a path is legal. That is why a confident sentence cannot become a wrong binding.

## 4. The brief becomes typed requirements. (13.4s)

Generate the document and the brief becomes concrete requirements. Each requirement points to a candidate field, with its type and scope visible. That is the difference between a prompt and a reviewable plan.

## 5. Every binding is visible. (16.8s)

The mapping review separates confirmed bindings from ambiguous or missing ones. When a choice is ambiguous, a reviewer can confirm the correct field. The decision is recorded, and a blocking mapping stops compilation. Nothing silently falls through.

## 6. One structure, two outputs. (14.2s)

The preview and the Word file are built from the same template structure, so headers and layout follow the same rules. When the mapping is ready, download the document. The demo also records the artifact hash for verification.

## 7. The download is evidence, not a trick. (16.1s)

The demo does not stop at pixels. Downloading the file records its size and SHA-256. The same hash is reproduced by the deterministic local build, so a reviewer can verify that the demo and the evidence describe the same artifact.

## 8. The logo stays on page one. (12.5s)

Open the result in Word. The logo appears only on the first page. The invoice number, customer and supplier details, items and totals are all there, and the table stays aligned.

## 9. Later pages keep the identity, not the logo. (12.2s)

Page two keeps the company name and VAT in the header, without repeating the logo. The footer keeps its page numbers. That is the first-page header rule working in a real document.

## 10. The brief became a checked document. (16.3s)

The brief became a typed plan, the plan became a validated document, and every binding has evidence. The same pipeline covers quotations, invoices and purchase orders. Docentric Copilot is a narrow AI boundary around a deterministic document engine.
