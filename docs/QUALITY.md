# Document quality engine

Status: IR-level analysis and typed layout optimisation are implemented. LibreOffice rendering is
optional, labelled visual evidence ([RENDERING](RENDERING.md)).

## What is checked

`POST /api/v1/templates/quality` analyses the validated Template IR and returns explainable checks,
each pointing at the element it belongs to.

| Check | Question | Fails when |
| --- | --- | --- |
| `table_layout` | Does every table fit the text area? | a table is wider than the page (warning) |
| `text_fit` | Would a table cell wrap beyond four lines? | a bound sample string is estimated over four lines (warning) |
| `image_clipping` | Are images inside the margins? | an image is wider than the text area |
| `page_overflow` | Does every section have content? | a section is empty |
| `header_footer` | Is there running header/footer content? | absent (warning; the compiler still adds page numbers) |
| `page_breaks` | Are explicit breaks and headings consistent? | reported as information |
| `typography` | Are type sizes readable? | any run outside 7–24 pt (warning) |
| `content_safety` | Can a value overflow the page? | an unbreakable value longer than 120 characters |

`overall` is `failed` if any check fails, `warning` if any warning remains, otherwise `passed`.

### Text-fit estimate

`text_fit` estimates wrapped lines from the bound sample data rather than from a renderer:

- the bound sample string, taking the worst value across all rows of a repeating table;
- the column width in millimetres and the effective table font size (a style override, otherwise the
  compiler's 9.5 pt default);
- 3.2 mm of compiled left/right cell padding, a 0.5 em average character width and greedy word
  wrapping (words longer than a line are split, as Word does for unbreakable text).

The budget is four lines. At a normal ~80 mm column and 9 pt, that is roughly 200 characters. The
check is deterministic and needs no office runtime, but it is an estimate, not a measurement of Word
line breaking. The finding carries the structural cell path, for example
`sections[0].body[4].row_template[1]`, and the message names the estimated line count.

## Optimisation

`POST /api/v1/templates/optimize` applies only typed IR changes:

- proportional scaling of table columns to the text width;
- for `text_fit`, widening the offending column by rebalancing slack from the other columns (never
  below 12 mm each) while keeping the table inside the text width;
- if the warning survives at the widest useful layout, lowering the table font by 0.5 pt at a time,
  with a floor of 8.0 pt;
- capping oversized images at the text width;
- enabling the header row on repeating tables.

Every fix records its structural IR path and its before/after values, for example
`sections[0].body[4].columns[1].width_mm` from `62.0` to `88.7` and
`sections[0].body[4].style.font_size_pt` from `9.5` to `9.0`.

The response also contains `ir_diff`, a compact list of the width and font fields that actually
changed. Only changed `*.width_mm` and `*.font_size_pt` fields are included; `before` and `after` are
the IR values:

```json
{
  "ir_diff": [
    {
      "path": "sections[0].body[4].columns[1].width_mm",
      "kind": "changed",
      "before": 62.0,
      "after": 88.7
    },
    {
      "path": "sections[0].body[4].style.font_size_pt",
      "kind": "changed",
      "before": 9.5,
      "after": 9.0
    }
  ]
}
```

It writes a **new immutable version**, re-runs validation and returns the before/after reports. If
the edit would turn a warning into a failure, the original document is returned unchanged.

## Honest limits

`text_fit` estimates wrapping from character counts, column widths and font sizes; it cannot see
kerning, font substitution or hyphenation. It is a review signal, not a rendering guarantee.

This is not Word pagination and not a Docentric rendering proof. PDF rendering via LibreOffice, when
enabled through the optional `api-pdf` target, is labelled *LibreOffice rendering*: it is a useful
independent visual check, not evidence of identical pagination in Microsoft Word or Docentric AX.
See [RENDERING.md](RENDERING.md) for what the images prove and do not prove, and
[DOCX_OPENING.md](DOCX_OPENING.md) for opening the compiled DOCX.

The `not_tested` compatibility status is unaffected by any quality result.
