# Opening the compiled DOCX

Status: the compiler produces a **generic DOCX**. Docentric AX compatibility remains **`not_tested`**.
Opening the file in Word or LibreOffice does not change that status.

## Where the file comes from

The compiled document is an artifact returned by the API or the demo:

- `POST /api/v1/templates/compile` returns a `docx` artifact; download it from
  `GET /api/v1/artifacts/{artifact_id}`.
- `POST /api/v1/demo/sessions` with `case_id: "quotation-long-items"` returns the same artifact shape
  with the long item descriptions.
- The CLI and the Streamlit demo use the same compiler and can save the same bytes.

The artifact URL is time-limited by the artifact TTL; save the `.docx` locally before opening it.

## Open in Microsoft Word

1. Download the artifact and keep the `.docx` extension.
2. In Word choose **File → Open → Browse**, select the file and confirm **Open**.
3. If Word shows a protected-view banner, choose **Enable Editing** only when you intend to edit a
   copy; editing the artifact is outside the versioned workflow.
4. Check the item table: headings, the Description column width, and where descriptions wrap.

Word is the reference consumer for pagination, but this project makes no claim that Word output was
recorded for these artifacts.

## Open in LibreOffice

1. Download the artifact and keep the `.docx` extension.
2. Start **LibreOffice Writer**, choose **File → Open**, select the file and confirm **Open**.
3. Alternatively, on a machine with LibreOffice on `PATH`:
   `soffice --writer path/to/document.docx`.
4. LibreOffice may substitute fonts. Treat its pagination as **LibreOffice rendering**, not as proof of
   what Word or Docentric AX will show.

If neither Word nor LibreOffice is installed, render the file with the optional `api-pdf` Docker
target. The script refuses to run with a clear message when `soffice` is missing; the exact commands
are in [RENDERING.md](RENDERING.md).

## Recorded evidence

The recorded evidence is two **PDF pages rendered by LibreOffice** and rasterised with `pdftoppm`, not
screenshots of Word and not the product's HTML preview:

| File | What it shows |
| --- | --- |
| [quality-before-libreoffice.png](assets/quality-before-libreoffice.png) | Page 1 before optimisation: Description is 62 mm and the long descriptions wrap over many lines. |
| [quality-after-libreoffice.png](assets/quality-after-libreoffice.png) | Page 1 after optimisation: Description is 88.7 mm, the table font is 9.0 pt and the same descriptions use fewer lines. |

Both are labelled **LibreOffice rendering (not Word fidelity)**. They are full page 1 at 150 dpi
(1241 x 1754 px), produced by LibreOffice Writer 25.2 inside the `api-pdf` image built from this
working tree. No Word or LibreOffice installation exists on this host; the conversion therefore ran
in Docker, not natively.

The quality finding and the typed fixes behind the after image are recorded on the
`quotation-long-items` demo case: `text_fit` warning before optimisation, `fit_text_width` and
`fit_text_font` fixes, then `text_fit` passed. See [QUALITY.md](QUALITY.md) for the rule itself.

## Compatibility status

Opening or rendering the DOCX does not verify Docentric AX compatibility. The validation report keeps
`docentric_compatibility: "not_tested"`, the compiler refuses the AX target, and no AX environment has
been used. See [DOCENTRIC_AX_COMPATIBILITY.md](DOCENTRIC_AX_COMPATIBILITY.md) for the gate and its
evidence requirements.
