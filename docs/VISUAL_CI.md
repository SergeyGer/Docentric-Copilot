# Visual Diff CI — LibreOffice/Poppler (V012-07)

The v0.12 release gate uses a **real** DOCX → PDF → PNG pipeline. The stub
renderer is not used for the gate: `scripts/visual_ci.py` requires `soffice` and
`pdftoppm`, records their versions and fails closed when either is missing or
does not match the lock file.

| Field | Value |
| --- | --- |
| Gate | [scripts/visual_ci.py](../scripts/visual_ci.py) |
| Workflow | [.github/workflows/visual.yml](../.github/workflows/visual.yml) |
| Version lock | [benchmarks/visual_renderer_lock.json](../benchmarks/visual_renderer_lock.json) |
| Tests | [tests/unit/test_visual_ci.py](../tests/unit/test_visual_ci.py) |
| Renderer | LibreOffice Writer `24.2.7.2` (headless) |
| Rasteriser | Poppler `24.02.0` (`pdftoppm`) |
| Fonts | DejaVu Sans `2.37-8` |
| Locale | `C.UTF-8` |
| DPI | 150 |
| Tolerance | `0.005` (0.5% changed pixels per page) |
| Runtime compatibility | `not_tested` |

## Fixtures

All five pairs are generated deterministically with `python-docx`; no binary is
committed.

| Fixture | Expected | What changes |
| --- | --- | --- |
| `identical` | `visual_pass` | The same DOCX bytes on both sides |
| `page_break_shift` | `visual_different` | A page break moves from paragraph 3 to paragraph 6 |
| `table_width_change` | `visual_different` | A fixed-layout table changes from 60 mm to 130 mm |
| `image_displacement` | `visual_different` | The same image moves from left to right |
| `missing_font` | recorded | Text requests a font that is not installed; substitution is recorded, never silently called a pass |

The identical pair must match within tolerance. Each positive fixture must
produce at least one changed page. The missing-font case must complete with the
real renderer; its status is recorded (identical or different), because font
substitution is a renderer behaviour, not a defect oracle.

## Statuses

| Status | Meaning |
| --- | --- |
| `visual_pass` | Real rendering completed and all compared pages are within tolerance |
| `visual_different` | Real rendering completed and at least one page changed |
| `visual_not_checked` | No real renderer was available; never a pass or a fail |

Renderer failure, missing tools, version drift or a positive fixture that is not
detected make the job fail. The summary also carries `runtime_compatibility:
not_tested`.

## Run it locally

```bash
# Debian/Ubuntu (the same pinned packages as CI)
sudo apt-get install -y --no-install-recommends \
  libreoffice-writer=4:24.2.7-0ubuntu0.24.04.7 \
  poppler-utils=24.02.0-1ubuntu9.11 \
  fonts-dejavu-core=2.37-8
LC_ALL=C.UTF-8 LANG=C.UTF-8 python scripts/visual_ci.py --output-dir visual-ci
```

The script writes:

```text
visual-ci/
├── fixtures/
│   ├── identical/
│   │   ├── left.pdf, right.pdf
│   │   ├── left-pages/page-1.png …
│   │   ├── right-pages/page-1.png …
│   │   ├── report.json
│   │   └── report.html
│   └── … (one directory per fixture)
└── summary.json
```

`summary.json` records the renderer, Poppler, font and locale identity, flags,
DPI, tolerance, per-fixture status, changed pages, failures and the
`LibreOffice rendering (not Word fidelity)` label. CI uploads the whole tree as
`visual-diff-evidence`.

## Limitations

- LibreOffice is not Microsoft Word. Font substitution, table splitting and
  pagination can differ from Word; the output never claims Word or Docentric AX
  fidelity.
- A visual difference is evidence of change, not automatically a defect.
- The tolerance is documented, not hidden. It is a per-page changed-pixel
  fraction, not a perceptual score.
- Runtime compatibility remains `not_tested`; rendering a DOCX does not prove it
  executes in Docentric AX.
- The fixtures are synthetic. They prove the renderer and comparison pipeline,
  not a customer template's visual correctness.
