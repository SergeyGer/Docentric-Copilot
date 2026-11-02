# Document quality engine

Status: IR-level analysis and typed layout optimisation are implemented. PDF rendering is optional
and not enabled by default.

## What is checked

`POST /api/v1/templates/quality` analyses the validated Template IR and returns explainable checks,
each pointing at the element it belongs to.

| Check | Question | Fails when |
| --- | --- | --- |
| `table_layout` | Does every table fit the text area? | a table is wider than the page (warning) |
| `image_clipping` | Are images inside the margins? | an image is wider than the text area |
| `page_overflow` | Does every section have content? | a section is empty |
| `header_footer` | Is there running header/footer content? | absent (warning; the compiler still adds page numbers) |
| `page_breaks` | Are explicit breaks and headings consistent? | reported as information |
| `typography` | Are type sizes readable? | any run outside 7–24 pt (warning) |
| `content_safety` | Can a value overflow the page? | an unbreakable value longer than 120 characters |

`overall` is `failed` if any check fails, `warning` if any warning remains, otherwise `passed`.

## Optimisation

`POST /api/v1/templates/optimize` applies only typed IR changes:

- proportional scaling of table columns to the text width;
- capping oversized images at the text width;
- enabling the header row on repeating tables.

It writes a **new immutable version**, re-runs validation and returns the before/after reports. If
the edit would turn a warning into a failure, the original document is returned unchanged.

## Honest limits

This is not Word pagination and not a Docentric rendering proof. PDF rendering via LibreOffice, if
enabled, is labelled *LibreOffice rendering*: it is a useful independent visual check, not evidence
of identical pagination in Microsoft Word or Docentric AX.

The `not_tested` compatibility status is unaffected by any quality result.
