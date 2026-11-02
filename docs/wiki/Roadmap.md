# Roadmap

> What is done, what is deliberately deferred, and what is blocked by external evidence.

## Milestones

| Milestone | Scope | Status |
| --- | --- | --- |
| **M0 Feasibility** | Format research, licensing analysis, go/no-go | Done — path B recorded |
| **M1 Schema engine** | Safe DDSP ingestion, normalization, CLI | Done |
| **M2 AI planning** | Template IR, gateway, mapping, expressions, validators | Done |
| **M3 Compilation** | Generic DOCX, preview, golden files | Done |
| **M4 Web + CLI** | API, workspace, jobs, artifacts, Docker | Done |
| **M5 Release** | CI, security scans, docs, benchmarks, release | Done for 0.2.0 |

## Now — hardening the MVP

| Item | Status |
| --- | --- |
| Replace `next lint` with the ESLint CLI before Next 16 | Planned |
| Strict Content-Security-Policy with nonces | Planned |
| Standalone Next.js server in the web image | Planned |
| Bump to Next 16 after the lint migration | Planned |
| Broader V4 visual checks | Planned |

## Next — deeper realism

| Item | Why it matters |
| --- | --- |
| Real DDSP fixtures (permitted) | The parser is currently validated on synthetic packages only |
| Hosted-provider evaluation baseline | Turns “works with a model” into a measured claim |
| Locale-aware number and date formatting | Documents are English-formatted today |
| More block kinds (group, summary fields, barcodes) | Expands the expressible layout space |
| PDF preview via a headless renderer | Removes the “HTML only” limitation |

## Blocked — external evidence required

| Item | Blocking condition |
| --- | --- |
| Docentric AX adapter | Permitted format knowledge + licensed verification environment |
| Verified compatibility metric | Independent execution of Field/List/Image/If |
| Word-fidelity pagination | A rendering stack that matches Word |

## Explicitly out of scope

Word add-in, direct D365 F&O connection, SaaS billing, enterprise SSO, collaborative editing,
Kubernetes without measured need.
