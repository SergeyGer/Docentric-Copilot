# LibreOffice rendering evidence

Status: **optional, labelled evidence.** The default API image and the CI build do not include
LibreOffice. This page describes the optional `api-pdf` Docker target, the `scripts/docx_to_pdf.py`
helper, and the two recorded page images in [assets](assets/).

Everything produced this way is **LibreOffice rendering**. It is not a Microsoft Word fidelity proof
and not a Docentric AX rendering proof.

## What the rendering proves

- A real consumer opens the compiled DOCX without an OOXML repair prompt and produces a PDF.
- The page count and the rendered table split can be observed instead of inferred from the IR.
- Text actually wraps in the cells; a long description visibly occupies more lines than a short one.
- A before/after pair shows whether the typed layout changes (column width, table font size) survive
  compilation and change what a renderer draws.
- The table stays inside the text area; an overflow would be visible as a column crossing the margin.

## What it does not prove

- **Not Word fidelity.** Word and LibreOffice use different line-breaking, font substitution and
  pagination engines. A page count or a break position can differ in Word.
- **Not Docentric AX fidelity.** The AX compatibility status remains `not_tested`; see
  [DOCENTRIC_AX_COMPATIBILITY.md](DOCENTRIC_AX_COMPATIBILITY.md).
- **Not deterministic evidence.** LibreOffice and font versions affect output. The PDFs and PNGs are
  illustrative artifacts, not golden files in the test suite.
- **Not a layout guarantee for arbitrary machines.** A viewer without the expected fonts may wrap
  the same DOCX differently.
- **Not the HTML preview.** The product preview is a separate, independent rendering; its layout
  already differs from Word/Docentric pagination and is not the subject of these images.

## Build and run

Build the optional target. It starts from the normal API image and adds `libreoffice-writer`,
`libreoffice-core`, `fonts-dejavu` and `poppler-utils`:

```bash
docker build --target api-pdf -t docentric-copilot-api-pdf .
```

Convert a DOCX and rasterise page 1 at 150 dpi:

```bash
mkdir -p .render
docker run --rm --user "$(id -u):$(id -g)" \
  -v "$PWD:/work" -w /work docentric-copilot-api-pdf \
  python scripts/docx_to_pdf.py .render/quotation.docx \
    --png .render/quotation-page1.png --dpi 150
```

On a workstation that already has LibreOffice and poppler installed, the same script runs directly:

```bash
python scripts/docx_to_pdf.py document.docx -o document.pdf --png page1.png --dpi 150
python scripts/docx_to_pdf.py document.docx --png-dir pages/ --dpi 150
```

The script calls `soffice --headless --convert-to pdf` with a temporary LibreOffice profile, then
`pdftoppm` for the PNG. It exits with code 2 and a clear message when `soffice` or `pdftoppm` is
missing. `--help` lists all options.

The target is not built by `docker compose up`, the default `docker build .` or the CI Docker job:
the final stage remains the slim `runtime` image, and `api-pdf` is reached only with `--target`.

## Recorded evidence

The evidence below was produced from the bundled `quotation-long-items` demo package, compiled to
DOCX before and after `POST /api/v1/templates/optimize`. Both images are **full page 1 at 150 dpi**
(1241 x 1754 px), rasterised from the PDF written by LibreOffice Writer 25.2 and `pdftoppm`.

### Before optimisation

![Before optimisation: LibreOffice rendering of the long-description quotation](assets/quality-before-libreoffice.png)

The Description column is 62 mm at 9.5 pt. Both item descriptions visibly wrap over many lines; the
IR quality report has one `text_fit` warning covering two table cells (estimated at seven lines).

### After optimisation

![After optimisation: LibreOffice rendering of the widened Description column](assets/quality-after-libreoffice.png)

Optimisation widened Description from 62.0 mm to 88.7 mm by rebalancing SKU, Qty, Unit, Unit price
and Amount, then lowered the table font from 9.5 pt to 9.0 pt. The same text now uses fewer lines
(about five in this rendering), the table still fits the 170 mm text area, and `text_fit` passes. The
document remains two pages in this rendering; the evidence here is the table wrap, not a page-count
claim.

Reproduce the pair by compiling the demo package before and after optimisation and running the
commands above. See [DOCX_OPENING.md](DOCX_OPENING.md) for where the artifact comes from and how to
open it.
