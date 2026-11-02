# Docentric Copilot — Web Workspace

A single-page Next.js 15 workspace for the Docentric Copilot API. It drives the existing FastAPI
backend end to end: upload a DDSP source, explore its normalized schema, plan a validated Template
IR, review and confirm field mappings and five-level validation, render the API's HTML preview,
compile a generic DOCX and request a new version from natural language. The header's **Run demo**
button hydrates the whole workspace from a bundled case in one click and starts a guided tour.

The UI is intentionally explicit about one thing: **Docentric AX compatibility is not verified.**
V5 compatibility is shown as `not tested` and is never styled as a pass.

## Requirements

- Node.js 22 and npm 10
- The API running (default `http://127.0.0.1:8000`); the web server proxies `/api/v1/*` to it

## Configuration

```bash
cp .env.example .env.local
```

| Variable | Default | Purpose |
| --- | --- | --- |
| `NEXT_PUBLIC_API_BASE_URL` | *(empty — same origin)* | Call the API at another origin directly instead of through the proxy |
| `API_PROXY_TARGET` | `http://127.0.0.1:8000` | Server-side proxy target for `/api/v1/*` (set to `http://api:8000` in Docker) |

`NEXT_PUBLIC_*` variables are inlined at build time, so rebuild (`npm run build`) after changing the
value for a production build.

The API's default CORS configuration allows `http://localhost:3000`. Run the web app on port 3000
and open it through `localhost` (not `127.0.0.1`), or adjust `DC_CORS_ORIGINS` on the API side. The
API also serves OpenAPI documentation at `/docs`.

## Run

```bash
npm install
npm run dev        # http://localhost:3000
```

Production build:

```bash
npm run build
npm start          # http://localhost:3000
```

| Script | Description |
| --- | --- |
| `npm run dev` | Next.js dev server on port 3000 |
| `npm run build` | Production build |
| `npm start` | Serve the production build on port 3000 |
| `npm run lint` | ESLint (`next lint`) |
| `npm run typecheck` | TypeScript strict check (`tsc --noEmit`) |

## Workspace panels

The sticky header contains the demo controls. **Run demo** calls `POST /api/v1/demo/sessions` with
the selected case from `GET /api/v1/demo/examples`, hydrates the source summary, schema, plan, IR,
mapping, report, preview and artifacts, shows the elapsed time in a toast, and starts the guided
tour returned by the API. The tour dims the page, spotlights each section, and supports Back, Next,
Finish, Esc and keyboard focus trapping.

1. **Data source** — drag and drop or browse for a `.ddsp`, `.xml`, `.xsd` or `.zip` package. After
   upload the panel shows the source ID, schema ID, sections, field counts, sample-data
   availability, package entries and parser diagnostics coloured by severity. Upload and schema
   discovery errors surface the API error code, message and details.
2. **Schema explorer** — a collapsible tree of `normalized_schema.sections[].nodes[]` with type
   badges (string/number/boolean/date/image/collection/object), required markers, attributes,
   filter box, expand/collapse actions and a details pane. Hovering a value in the preview
   highlights and expands the matching field here. Clicking a path copies it; the insert action
   appends the path to the prompt. Keyboard: arrow keys navigate, Enter toggles containers, `C`
   copies and `I` inserts.
3. **Prompt & provider** — an example prompt, provider catalogue from `GET /providers`
   (unconfigured providers are disabled, mock is always available), model with provider defaults,
   design style, language and advanced plan options (strict validation, cost cap, repair attempts).
   Planning publishes the Template IR and its artifact bundle.
4. **Mapping review** — summary counters for `confirmed`, `schema_valid`, `needs_review`,
   `conflict`, `missing` and `invalid`, then a table of requirements, status, selected binding or
   candidates, confidence and explanation. Each row shows its concept label, placement, evidence
   score, supporting fields and any `Conflicts with req_xx` chips. Reviewable rows expose their
   candidate paths, a reviewer note, **Use this field** (`POST .../mappings/{requirement_id}/confirm`
   with `selected_field_path`) and **Confirm as is** (same endpoint with `selected_field_path: null`).
   A successful review switches to the returned version, refreshes the preview from the returned IR
   and shows `Review recorded — version N`. Removed bindings from the planner are listed too.
5. **Validation** — five independent level chips (V1–V5), overall status, per-level checks and
   findings in tabs. `not_tested` uses a neutral dashed treatment, never green. Planner warnings are
   listed here as well.
6. **Preview** — requests `POST /templates/preview` and renders the returned HTML inside
   `<iframe srcdoc sandbox="allow-same-origin">`. Scripts stay disabled; the parent attaches plain
   DOM listeners to every `[data-path]` value so hover/focus highlights the schema field and mapping
   row, and clicking scrolls the mapping row into view and selects its candidate list.
7. **Artifacts & download** — compile options (file name, render mode, compatibility stamp, sample
   data), compile statistics and warnings, and the artifacts from the most recent API response
   (kind, filename, size, digest, expiry, download/view links). Compiling downloads the DOCX
   automatically. The button is disabled with an explanation while mappings still need review,
   because the API refuses to compile unreviewed versions.
8. **Revision** — apply a natural-language change, inspect the structural change summary
   (added/removed/changed), and browse version history. **Compare versions** opens a modal with the
   previous and new previews side by side (both fetched with `POST /templates/preview` using
   `{source_id, template_id, version}`), summary counters and grouped added/removed/changed paths.
   Each pane has **Restore version**, which loads that version's IR, mapping, report and preview
   into the workspace and updates the active marker. Revision uses `POST /templates/revise`; version
   loading uses `GET /templates/{template_id}/export/{version}`.

Across the page, the header reports API health, and a sticky amber notice repeats the compatibility
disclaimer. All request errors are normalised by `src/lib/api.ts` into an `ApiError` with the API's
`code`, `message` and `details`; `ErrorAlert` renders them inline per panel.

## Project structure

```
apps/web/
├── src/app/                 # App Router layout and the client workspace page
├── src/components/
│   ├── ui/                  # Vendored shadcn-style primitives (Button, Card, Tabs, Modal, …)
│   ├── workspace/           # One component per workspace panel plus shared UI
│   ├── api-status-badge.tsx
│   ├── app-header.tsx       # Run demo controls and API status
│   ├── app-footer.tsx
│   ├── compatibility-notice.tsx
│   └── workflow-stepper.tsx
├── src/hooks/
│   ├── use-workspace.ts     # Client state and all API actions
│   └── workspace-context.tsx # Shared controller for the header and panels
├── src/lib/                 # Typed API client, API types, schema/validation helpers
├── .env.example
└── README.md
```

## Limitations

- The workspace is client-side state only. Refreshing the browser starts a new session; API sources,
  templates and artifacts remain on the backend until their TTL expires.
- Only the `generic-docx` target is exercised. The Docentric AX adapter is intentionally not offered,
  because V5 compatibility is not verified.
- The HTML preview is sandboxed with `allow-same-origin` only. Scripts and top-level navigation stay
  disabled; the parent attaches passive listeners so hover and click can reveal bindings. The API's
  HTML is never inserted into the React document directly.
- The demo depends on the API's bundled demo package. If demo routes are unavailable, the header
  falls back to the `quotation` case and the workspace shows the API's error message and code.
- Visual checks (V4) can be skipped when the API has no compiled package to inspect; the UI reports
  the exact status rather than inferring success.
