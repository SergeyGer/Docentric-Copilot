# Pull request

## Summary

<!-- What does this change, and why? Link the issue or requirement (for example FR-05). -->

Fixes #

## Type of change

- [ ] Bug fix
- [ ] New feature
- [ ] Refactor (no behaviour change)
- [ ] Documentation
- [ ] Tests / tooling / CI
- [ ] Breaking change (Template IR, API contract, storage schema)

## Compatibility statement

Docentric AX compatibility is **unverified** and gated. Confirm one:

- [ ] This change does not touch the compatibility gate, the AX target, or any compatibility claim.
- [ ] This change touches compatibility behaviour and includes the evidence required by
      `docs/DOCENTRIC_AX_COMPATIBILITY.md` (a new ADR is mandatory in that case).

No wording in this PR describes output as "verified", "certified", "compatible" or "works with"
Docentric AX.

## Definition of Done

- [ ] **Tests:** behaviour is covered by a test that fails without this change (or the PR explains
      why a test is not possible).
- [ ] **Lint/formats:** `ruff check .` and `ruff format --check .` pass.
- [ ] **Types:** `mypy packages services` passes.
- [ ] **Coverage:** `make test-cov` passes the 85% gate (or the PR explains and justifies a change).
- [ ] **Docs:** affected documents are updated — `docs/SRS.md` (status/evidence), `docs/TEMPLATE_IR.md`
      (IR changes), `docs/API_SPEC.md` + `docs/openapi.json` (endpoint/schema changes),
      `docs/DDSP_COMPATIBILITY.md` (parser/diagnostics/limits), `docs/THREAT_MODEL.md` (new trust
      boundary), README feature matrix, `docs/ROADMAP.md`.
- [ ] **No unverified compatibility claim** was introduced anywhere (code, docs, comments, UI copy).
- [ ] **No secrets or real data:** no API keys, `.env`, customer data, third-party templates or
      proprietary DDSP packages in code, tests, fixtures, logs or screenshots.
- [ ] **Determinism preserved:** no clock, randomness, network or unordered iteration in parse,
      validate, serialize or compile paths; golden files updated only for intentional changes and
      reviewed.
- [ ] **Error contract coherent:** a new failure mode has a `CopilotError` subclass, a stable code, an
      HTTP status, a CLI exit code (if reachable) and an API_SPEC entry.
- [ ] **CHANGELOG.md** updated for user-visible changes.
- [ ] **`make ci`** passes locally (paste the result below), and the web checks
      (`npm run lint`, `npm run typecheck`, `npm run build`) pass if `apps/web` changed.

## Verification

<!-- Commands run and their results. Include the validation statuses, IR digest or test counts where relevant. -->

```text
$ make ci
...
```

## Notes for reviewers

<!-- Trade-offs, follow-up work, known limitations. -->
