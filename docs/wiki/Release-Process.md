# Release Process

> Every release is reproducible from a tag, verified by CI, and states its compatibility status.

## Versioning

Semantic versioning for the application, and a separate version for the contract:

| Artifact | Version | Where |
| --- | --- | --- |
| Application | `MAJOR.MINOR.PATCH` | `pyproject.toml`, `__version__`, `package.json` |
| Template IR | `1.0` | `ir_version` in every document |
| HTTP API | `/api/v1` | route prefix |
| CLI exit codes | `0–6` | CLI reference |

A change to the IR models is a **contract change**: bump the IR version and add a migration.

## Release checklist

1. **Green main** — all CI jobs succeed (python, web, docker, security).
2. **Quality gates** — `make lint typecheck test-cov`; coverage ≥ 85%.
3. **Reproducibility** — `build_examples.py --check`, `update_golden --check`, OpenAPI diff clean.
4. **Dependencies** — `pip-audit` and `npm audit` report no vulnerabilities.
5. **Docs** — Wiki and `docs/` updated; CHANGELOG has an entry.
6. **Compatibility wording** — grep for “compatible” and confirm nothing overclaims.
7. **Tag** — annotated tag `vX.Y.Z` on the verified commit.
8. **Push** — `git push origin main --tags`; the Release workflow builds the wheel and both images.
9. **Publish** — GitHub release notes list features, verification evidence and known limitations.

## What the release workflow does

```text
tag push → build wheel + sdist
         → install the wheel in a clean venv, run version + inspect
         → build API and web Docker images
         → attach distributions to the GitHub release
```

## Post-release

| Step | Detail |
| --- | --- |
| Verify the release page | Notes, assets, tag commit |
| Check Dependabot | New advisories within 48 hours |
| Announce | Only with the compatibility status stated |

## Rolling back

Because artifacts are deterministic, a rollback is a revert commit plus a new patch tag. Never delete a
published tag: consumers may pin it.
