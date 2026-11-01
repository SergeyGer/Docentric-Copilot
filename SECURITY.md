# Security Policy

## Supported versions

| Version | Supported | Notes |
| --- | --- | --- |
| 0.1.x | Yes (best effort) | Current MVP line |
| < 0.1 | No | Pre-release development only |

This project is pre-1.0: security fixes are applied to the current line only. There are no long-term
support branches and no guaranteed backport window. If you need a maintained branch, open an issue to
discuss it before relying on it.

## Reporting a vulnerability

**Do not open a public issue, discussion or pull request for a suspected vulnerability.**

Report privately through GitHub's private vulnerability reporting for this repository:

<https://github.com/SergeyGer/Docentric-Copilot/security/advisories/new>

If private advisories are unavailable to you, open a minimal public issue that asks the maintainers to
establish a private channel, **without** including exploit details, credentials or personal data.

Please include, where applicable:

- affected version/commit and component (parser, API, CLI, compiler, planner, web);
- a description of the issue and its security impact;
- reproduction steps or a minimal proof of concept using **synthetic** data;
- whether the issue requires authentication, a specific configuration or a hostile input package;
- any suggested mitigation;
- how you would like to be credited (or that you prefer anonymity).

Do not include real customer data, DDSP packages, API keys or personal data in a report. Redact logs
and documents. If a proof of concept needs a hostile package, generate a synthetic one with
`scripts/build_examples.py` or a minimal inline XML fixture.

### What to expect

This is a small project with no guaranteed response SLA. Maintainers will:

1. acknowledge the report as soon as practical;
2. reproduce and assess it against the [threat model](docs/THREAT_MODEL.md);
3. agree a disclosure timeline with you before publishing details;
4. credit you in the advisory and changelog unless you ask otherwise.

Please give the maintainers a reasonable opportunity to fix the issue before public disclosure.

## Scope

### In scope

- Bypass of the DDSP parser protections: XXE/DTD, entity expansion, zip bombs, path traversal, nested
  archives, encrypted entries, limit circumvention.
- Denial of service through unbounded parsing, validation, compilation or artifact generation.
- Prompt-injection paths that cause the system to emit a template violating the Template IR contract,
  or that leak data beyond the documented boundary.
- Secret leakage through API responses, CLI output, logs, error details or stored data.
- Unauthorised artifact access (enumeration, path traversal, TTL bypass).
- Path traversal or arbitrary file write through filenames, artifact names or document names.
- Vulnerabilities in the web frontend (XSS, SSRF, unsafe rendering of API content).
- Dependency vulnerabilities with a plausible exploit path in this project.

### Out of scope

- **Missing authentication/authorisation.** This is a documented MVP limitation, not a vulnerability
  (see [THREAT_MODEL R-01](docs/THREAT_MODEL.md#7-residual-risk-register)). Reports about exposed
  deployments are still welcome, but the fix is a deployment/architecture change, not a patch.
- **Docentric AX compatibility.** Unverified by design; see
  [DOCENTRIC_AX_COMPATIBILITY](docs/DOCENTRIC_AX_COMPATIBILITY.md). A document not being accepted by a
  third-party product is a compatibility issue, not a security vulnerability.
- Rendering differences in Word/LibreOffice/PDF exporters.
- Provider-side incidents, data retention or model behaviour (report to the provider).
- Social engineering, physical access, host compromise, container escapes.
- Denial of service against a deployment you do not own or have permission to test.
- Automated scanner output without a reproducible, project-specific impact.

## Security design summary

The controls below are documented in detail in [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md):

- DDSP input is treated as untrusted: size/entry/size-ratio/node/depth limits, no DTD or entity
  processing, no network access from the XML parser, no extraction to disk.
- Model output is untrusted: validated against a strict IR, sanitised deterministically, and compiled
  only if validation passes.
- Compiled packages are inspected for VBA macros, embedded OLE/ActiveX objects and external
  relationships.
- Logs redact secret-looking keys and token formats; provider credentials are never returned by the API
  or written to storage.
- Artifacts are addressed by unguessable ids, expire after a TTL and are served with `nosniff` and
  `no-store`.
- The compatibility gate fails closed; no document is labelled compatible.

## Known residual risks

The following are known and documented, not unknown vulnerabilities:

| Risk | Status |
| --- | --- |
| No authentication/authorisation | Out of MVP scope; deploy behind an authenticating proxy |
| Prompt text is sent verbatim to hosted providers | Documented; PII redaction not implemented |
| HTML artifact `/view` has no CSP | Tracked (THREAT_MODEL R-04) |
| Preview accepts `data:image/svg+xml` | Tracked (THREAT_MODEL R-05) |
| No quotas/rate limiting; single-process SQLite | Tracked (THREAT_MODEL R-07) |
| No committed Python lockfile; container image scanning pending | Tracked (THREAT_MODEL R-08) |
| No CSP/security headers in the Next.js app | Tracked (THREAT_MODEL R-13) |
| No committed browser E2E or accessibility suite | Tracked (THREAT_MODEL R-14) |
| No independent security review | Tracked (THREAT_MODEL R-12) |

## Safe harbour

We will not pursue legal action against researchers who:

- act in good faith and only test systems they own or have explicit permission to test;
- avoid privacy violations, data destruction and service disruption;
- report findings privately and allow reasonable time for remediation;
- do not exploit a finding beyond the minimum needed to demonstrate it.

## Security updates

Security-relevant changes are noted in [CHANGELOG.md](CHANGELOG.md) under a `Security` heading.
Subscribe to repository releases/advisories for notifications.
