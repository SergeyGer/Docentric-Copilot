# ADR-0003: Make DOCX output byte-deterministic

| Field | Value |
| --- | --- |
| Status | Accepted |
| Date | 2026-11-01 |
| Related | [ARCHITECTURE §6](../ARCHITECTURE.md#6-determinism-strategy), [SRS NFR-01](../SRS.md#nfr-01--determinism-and-reproducibility) |

## Context

`python-docx` produces a valid OOXML package, but the ZIP container is not deterministic by default:
entry order depends on creation order, timestamps reflect the current time, permissions may vary, and
core properties such as `created`/`modified`/`revision` are filled from the clock. Without
normalisation, two identical compilations produce different bytes and possibly different SHA-256
values, which makes golden tests, artifact digests and "did the input change or the environment?"
questions unreliable.

## Decision

Normalise every produced package before it leaves the compiler:

1. Rebuild the ZIP with **sorted entry names** and no directory entries.
2. Set a **fixed timestamp** (`2024-01-01T00:00:00`), fixed `0644` permissions and a fixed deflate
   level (9).
3. Set deterministic core properties: fixed `created`, `modified`, `revision = 1`, author
   "Docentric Copilot", title/subject/keywords/category/language derived only from the IR, and a
   comment that states the document is generic and compatibility is `not_tested`.
4. Keep the compiler free of clock reads, random ids, unordered iteration and network access.
5. Expose an IR digest (SHA-256 over canonical IR JSON) and an artifact digest (SHA-256 over the final
   bytes) so callers can compare outputs.

The fixed timestamp is intentionally artificial. It means the DOCX metadata does not tell a reader when
the file was produced; the artifact/job records do. Reproducibility was chosen over metadata realism.

## Consequences

**Positive**

- Identical IR + sample data + compiler version ⇒ byte-identical DOCX (asserted by tests; observed
  SHA-256 `c882f0b1…` for the quotation fixture across CLI and API runs).
- Golden fixtures can compare stable projections and, where needed, exact bytes.
- Artifact digests are stable and useful for idempotency and review.
- No hidden dependence on the host clock, locale or filesystem ordering.

**Negative / costs**

- DOCX `created`/`modified` and `revision` no longer reflect reality; downstream tooling that relies on
  them will be misled.
- Any change to python-docx's serialization, the ZIP library or the normalisation code can change bytes
  and requires golden updates. The compiler version is part of the determinism contract.
- Compression level 9 is slower than the default; the trade-off is reproducibility, not file size
  optimality.
- The DIGEST is a fingerprint, not a signature; it proves identity of bytes, not authorship.

## Alternatives considered

- **Accept non-determinism and compare normalised projections only:** cheaper, but loses the strongest
  regression signal and makes artifact digests meaningless across runs.
- **Post-process with an external deterministic ZIP tool:** adds a dependency and still requires fixed
  core properties.
- **Timestamp from a build id:** deterministic per build but not per input; harder to reason about.

## Follow-up

- Any change to `normalize_package`, core properties or the compiler version must update golden files
  and the compiler version constant.
- Do not introduce time, randomness or unordered containers into the compile path; review rejects it
  (see SRS NFR-01 and the Definition of Done).
