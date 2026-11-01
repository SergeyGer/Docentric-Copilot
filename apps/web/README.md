# Docentric Copilot — Web Workspace

A single-page Next.js 15 workspace for the Docentric Copilot API. It drives the existing FastAPI
backend end to end: upload a DDSP source, explore its normalized schema, plan a validated Template
IR, review the field mapping and five-level validation, render the API's HTML preview, compile a
generic DOCX and request a new version from natural language.

The UI is intentionally explicit about one thing: **Docentric AX compatibility is not verified.**
V5 compatibility is shown as `not tested` and is never styled as a pass.

## Requirements

- Node.js 22 and npm 10
- The API running (default `http://localhost:8000`)

## Configuration

```bash
cp .env.example .env.local
```

| Variable | Default | Purpose |
| --- | --- | --- |
| `NEXT_PUBLIC_API_BASE_URL` | `http://localhost:8000` | Base URL of the FastAPI backend, without a trailing slash |

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

1. **Data source** — drag and drop or browse for a `.ddsp`, `.xml`, `.xsd` or `.zip` package. After
   upload the panel shows the source ID, schema ID, sections, field counts, sample-data
   availability, package entries and parser diagnostics coloured by severity. Upload and schema
   discovery errors surface the API error code, message and details.
2. **Schema explorer** — a collapsible tree of `normalized_schema.sections[].nodes[]` with type
   badges (string/number/boolean/date/image/collection/object), required markers, attributes,
   filter box, expand/collapse actions and a details pane. Clicking a path copies it; the insert
   action appends the path to the prompt. Keyboard: arrow keys navigate, Enter toggles containers,
   `C` copies and `I` inserts.
3. **Prompt & provider** — an example prompt, provider catalogue from `GET /providers`
   (unconfigured providers are disabled, mock is always available), model with provider defaults,
   design style, language and advanced plan options (strict validation, cost cap, repair attempts).
   Planning publishes the Template IR and its artifact bundle.
4. **Mapping review** — summary counters for resolved/ambiguous/missing/invalid mappings, then a
   table of requirements, status, selected binding or candidates, confidence and explanation.
   Selecting a candidate shows its exact path and type above the table; removed bindings from the
   planner are listed too.
5. **Validation** — five independent level chips (V1–V5), overall status, per-level checks and
   findings in tabs. `not_tested` uses a neutral dashed treatment, never green. Planner warnings are
   listed here as well.
6. **Preview** — requests `POST /templates/preview` and renders the returned HTML inside
   `<iframe srcdoc sandbox="">`, with a refresh button and stale-version warning.
7. **Artifacts & download** — compile options (file name, render mode, compatibility stamp, sample
   data), compile statistics and warnings, and the artifacts from the most recent API response
   (kind, filename, size, digest, expiry, download/view links). Compiling downloads the DOCX
   automatically; the artifact remains available for a second download.
8. **Revision** — apply a natural-language change, inspect the structural change summary
   (added/removed/changed), and browse version history. The active version is highlighted; loading
   another version swaps the IR, mapping, validation and preview panes. Revision uses
   `POST /templates/revise`; version loading uses the backend's
   `GET /templates/{template_id}/export/{version}` endpoint.

Across the page, the header reports API health, and a sticky amber notice repeats the compatibility
disclaimer. All request errors are normalised by `src/lib/api.ts` into an `ApiError` with the API's
`code`, `message` and `details`; `ErrorAlert` renders them inline per panel.

## Project structure

```
apps/web/
├── src/app/                 # App Router layout and the client workspace page
├── src/components/
│   ├── ui/                  # Vendored shadcn-style primitives (Button, Card, Tabs, …)
│   ├── workspace/           # One component per workspace panel plus shared UI
│   ├── api-status-badge.tsx
│   ├── app-header.tsx
│   ├── app-footer.tsx
│   ├── compatibility-notice.tsx
│   └── workflow-stepper.tsx
├── src/hooks/use-workspace.ts  # Client state and all API actions
├── src/lib/                 # Typed API client, API types, schema/validation helpers
├── .env.example
└── README.md
```

## Limitations

- The workspace is client-side state only. Refreshing the browser starts a new session; API sources,
  templates and artifacts remain on the backend until their TTL expires.
- Only the `generic-docx` target is exercised. The Docentric AX adapter is intentionally not offered,
  because V5 compatibility is not verified.
- The HTML preview is sandboxed with scripts and top-level navigation disabled. The API's HTML is
  never inserted into the React document directly.
- Visual checks (V4) can be skipped when the API has no compiled package to inspect; the UI reports
  the exact status rather than inferring success.
