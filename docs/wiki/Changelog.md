# Changelog

The canonical history is [`CHANGELOG.md`](https://github.com/SergeyGer/Docentric-Copilot/blob/main/CHANGELOG.md)
in the repository root (Keep a Changelog format).

## 0.2.0 — documentation and hardening release

### Added
- Complete project Wiki with a navigation sidebar and interface screenshots.
- Social preview image and repository topics.
- Dependabot configuration with grouped weekly updates.
- Baseline security headers for the web workspace.

### Changed
- README rewritten for a non-technical audience; engineering detail moved to the Wiki.

### Fixed
- `postcss` and `minimatch` security advisories in the web dependency tree (`npm audit`: 0 vulnerabilities).

## 0.1.0 — first public MVP

### Added
- Safe DDSP ingestion, normalized schema, semantic mapping.
- Template IR v1.0 with canonical JSON, digest and JSON Schema.
- Validation V1–V5 with `not_tested` semantics.
- Deterministic generic DOCX compiler and independent HTML preview.
- Provider gateway (OpenAI, Anthropic, Gemini) plus an offline deterministic planner.
- FastAPI service, CLI, Next.js workspace.
- 191 tests, golden files, benchmarks, evaluation harness, CI and Docker images.
