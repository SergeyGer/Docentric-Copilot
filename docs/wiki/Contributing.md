# Contributing

> Small, reviewable changes with tests, docs and no unverified claims.

## Ground rules

1. **Correctness over plausibility.** A feature that produces plausible output without evidence is not done.
2. **No compatibility claims.** Never describe generic DOCX output as Docentric-compatible.
3. **Tests first.** Every behaviour change ships with a test; golden files are updated deliberately.
4. **Docs follow code.** Update the Wiki page or `docs/` in the same change.
5. **Status and roadmap live in the Wiki.** Update [Honest Status](Honest-Status) for workstream status,
   AT-07 and limitations, and [Roadmap](Roadmap) for issue/target changes. GitHub Issues is the source
   of truth; the README links to these pages and does not duplicate their tables.
6. **English only** in code, comments, commits, docs and UI.

## Definition of Done

A change is complete when:

- [ ] the problem, expected behaviour, inputs, outputs and limits are described;
- [ ] unit tests (and integration/golden tests where relevant) are added;
- [ ] diagnostics and documentation are updated;
- [ ] no unverified compatibility claim is introduced;
- [ ] untrusted-input and secret handling have been considered;
- [ ] CI is green (lint, types, tests, coverage gate, web build, docker builds, security scans);
- [ ] breaking changes include a migration note.

## Local workflow

```bash
git clone https://github.com/SergeyGer/Docentric-Copilot.git
cd Docentric-Copilot

make install-dev          # python + dev tools
cd apps/web && npm ci && cd ..

make lint typecheck test-cov
make bench eval           # optional, before a release
```

## Commit style

```
<type>(<scope>): <imperative summary>

<body: what changed and why>
```

Types: `feat`, `fix`, `docs`, `test`, `refactor`, `chore`, `perf`, `security`.

## Architecture decisions

Non-trivial decisions are recorded as ADRs in `docs/adr/`. Add a new numbered record rather than editing
history.

## Reporting bugs

Use the issue templates. Include the command, the version, the DDSP shape (synthetic if possible) and the
full error envelope (`{error: {code, message, details}}`).

## Security issues

Do **not** open a public issue. See [SECURITY.md](https://github.com/SergeyGer/Docentric-Copilot/blob/main/SECURITY.md).
