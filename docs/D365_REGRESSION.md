# D365 real-corpus regression (V012-04)

This page describes the private-corpus regression runner added for v0.12 and the
reviewed aggregate it produced. The runner is public; the 11 source DOCX files,
their hashes, schema paths, graph payloads and diagnostics are **not**.

| Field | Value |
| --- | --- |
| Runner | [scripts/d365_regression.py](../scripts/d365_regression.py) |
| Tests | [tests/unit/test_d365_regression.py](../tests/unit/test_d365_regression.py) |
| Frozen baseline | [benchmarks/baseline_v011.json](../benchmarks/baseline_v011.json) |
| Public aggregate | [benchmarks/d365_regression_v012.json](../benchmarks/d365_regression_v012.json) |
| Private outputs | `.local-artifacts/d365-regression/` (git-ignored) |
| Runtime compatibility | `not_tested` |

## What it does

The runner expands the private corpus in memory, requires exactly 11 D365 DOCX
files, extracts the embedded `ProjectData` schema with the existing adapter,
builds the read-only `ReferenceGraph`, and records per document:

- input SHA-256, extractor contract version and graph digest;
- graph node/edge counts, resolved edges and evidence coverage;
- binding totals and every resolution status;
- diagnostics, duplicate `resolves_to` edges and list/scalar scope mismatches;
- a second analysis to prove the graph digest is reproducible.

It then compares the aggregate with the v0.11 baseline (246 bindings, 233
resolved, 13 unresolved) and returns a verdict. Missing/extra documents, failed
extraction, lost resolved bindings, new unresolved bindings, unstable digests
and scope mismatches fail the gate. The aggregate is written only when
`--publish` is passed; the per-document record and full graph payloads stay in
the git-ignored output directory.

## Run it

```bash
export DOCENTRIC_PRIVATE_CORPUS_DIR=/path/to/private/d365
python scripts/d365_regression.py --json
python scripts/d365_regression.py --publish /tmp/d365-summary.json
```

The private directory must be the 11-document D365 folder. Pointing at a parent
folder that also contains AX 2012 examples is reported as extra documents and
fails, rather than silently analysing a mixed corpus.

Exit codes: `0` passed, `1` regression or incomplete run, `2` missing corpus or
usage error.

## v0.12 result

Produced with the runner on the maintainer's private corpus. The committed
summary records the exact commit and timestamp of the run; the values below are
from that file.

| Metric | Baseline (v0.11) | v0.12 run |
| --- | ---: | ---: |
| Documents processed | 11 | **11 / 11** |
| Unique document payloads | 10 | 10 |
| Bindings | 246 | 246 |
| Resolved | 233 | **233** |
| Resolved with evidence | 233 | 233 |
| Resolved without evidence | 0 | 0 |
| Unresolved | 13 | **13** |
| `ambiguous` | 0 | 0 |
| `unknown_path` | 4 | 4 |
| `type_mismatch` | 1 | 1 |
| `unsupported_expression` | 8 | 8 |
| `schema_unavailable` | 0 | 0 |
| Graph nodes | — | 794 |
| Graph edges | — | 862 |
| Evidence coverage | — | 0.9243 |
| Duplicate `resolves_to` edges | — | 0 |
| Scope mismatches | — | 0 |
| Digest stable across two runs | — | **yes (11/11)** |
| Verdict | — | **passed** |

All 13 previously unresolved bindings remain classified exactly as before:
four `unknown_path`, eight `unsupported_expression` and one `type_mismatch`.
There are no new unresolved bindings and no lost resolved bindings.

The 13 non-resolved bindings are not failures of the graph builder: they are
bindings the available evidence could not resolve (unsupported static
expressions, paths outside the extracted schema and one result-type mismatch).
They remain visible in the report and are never silently mapped to a nearby
field.

## Privacy review

| Artifact | Git | Private storage |
| --- | --- | --- |
| Runner and tests | yes | — |
| Synthetic fixtures | yes | — |
| 11 source DOCX | **no** | yes |
| Per-document hashes, labels and diagnostics | **no** | `.local-artifacts/d365-regression/private/` |
| Full graph payloads and schema locations | **no** | `.local-artifacts/d365-regression/private/graphs/` |
| Aggregate counts | yes, after review | yes |
| API keys / credentials | **never** | environment only |

The aggregate contains no document names, hashes, schema paths, diagnostic
messages or customer values. The committed summary is reviewed against that
rule before publication; a test asserts the same property.

## Limitations

- The corpus is private. This evidence proves that the runner processed 11
  documents locally and that the aggregate matches the frozen baseline; it does
  not publish or prove their content.
- The 233/13 baseline is the v0.11 audit observation, not a guarantee. A future
  extractor change must explain any delta rather than re-baseline silently.
- Docentric AX runtime compatibility remains **not_tested**. Static extraction,
  graph construction and binding resolution are not execution in Dynamics 365
  F&O.
- Hashes are deliberately not published. Their metadata risk has not been
  assessed for redistribution.
