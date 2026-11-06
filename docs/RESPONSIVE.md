# Responsive verification — Reference Inspector (V012-10)

The `/reference` page is checked at three viewport widths by the committed
Playwright suite. The checks are functional layout checks, not pixel-perfect
visual regression.

| Viewport | Size | Result |
| --- | --- | --- |
| Desktop | 1280 × 900 | Passed — no horizontal overflow; all tabs and actions visible |
| Tablet | 768 × 1024 | Passed — no horizontal overflow; all tabs and actions visible |
| Narrow | 390 × 844 | Passed — no horizontal overflow; all tabs and actions visible |

**Minimum supported width: 390 px.** Below that the layout is not tested and
the minimum may need to increase; it must not be described as responsive without
a test at the target width.

## What is checked

For each viewport, the suite:

1. opens `/reference` and asserts the heading and **Inspect reference** action;
2. asserts `document.documentElement.scrollWidth` and `document.body.scrollWidth`
   do not exceed `window.innerWidth` (no horizontal page overflow);
3. uploads a generated synthetic DOCX and saves a report;
4. opens Overview, Controls, Graph and Diff and asserts each panel renders;
5. asserts the saved-report badge and export action are visible;
6. asserts no "Reference inspection failed" alert.

The narrow viewport exercises the wrapping header, the horizontally scrollable
tab list, the report id badge (`break-all`) and the export controls. The checks
are repeated after each tab switch.

## Run it

```bash
npm --prefix apps/web ci
.venv/bin/pytest tests/e2e/test_reference_responsive.py --e2e -q
```

The fixture starts the real API and built web app; see [E2E](E2E.md).

## Limits

- Chromium only; no touch-gesture or mobile-browser matrix.
- 320 px and below are untested. Do not claim mobile support for them.
- The check is page-level overflow plus visible actions, not a design review of
  every table or long value.
- The workspace page `/` is not part of this v0.12 check; only the reference
  inspector is claimed.
