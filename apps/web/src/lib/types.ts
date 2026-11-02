/**
 * TypeScript mirrors of the FastAPI Pydantic models in
 * `services/api/src/docentric_copilot/api/schemas.py` and the domain models they
 * embed. Shapes are deliberately structural (the API serialises JSON directly).
 */

/* ----------------------------------------------------------------- schema */

export type DataType =
  | "string"
  | "number"
  | "boolean"
  | "date"
  | "image"
  | "collection"
  | "any";

export type DiagnosticSeverity = "error" | "warning" | "info";

export interface Diagnostic {
  code: string;
  severity: DiagnosticSeverity;
  message: string;
  location: string | null;
}

export interface SchemaStats {
  node_count: number;
  scalar_count: number;
  collection_count: number;
  attribute_count: number;
  max_depth: number;
}

export interface SchemaAttribute {
  name: string;
  data_type: string;
  sample_value: string | number | boolean | null;
  source: string | null;
}

export interface SchemaNode {
  name: string;
  path: string;
  data_type: string;
  collection: boolean;
  required: boolean;
  source: string | null;
  description: string | null;
  sample_value: string | number | boolean | null;
  attributes: SchemaAttribute[];
  children: SchemaNode[];
}

export interface SchemaSection {
  name: string;
  nodes: SchemaNode[];
  source: string | null;
}

export interface NormalizedSchema {
  schema_id: string;
  source: string;
  format_version: string | null;
  container_format: string;
  sections: SchemaSection[];
  diagnostics: Diagnostic[];
  sample_data_available: boolean;
  locales: string[];
}

export interface SourceView {
  source_id: string;
  filename: string;
  schema_id: string;
  sections: string[];
  stats: SchemaStats;
  sample_data_available: boolean;
  diagnostics: Diagnostic[];
  entry_names: string[];
}

export interface SchemaView {
  source_id: string;
  normalized_schema: NormalizedSchema;
  stats: SchemaStats;
  diagnostics: Diagnostic[];
}

/* --------------------------------------------------------------- mappings */

export type MappingStatus =
  | "confirmed"
  | "schema_valid"
  | "needs_review"
  | "conflict"
  | "missing"
  | "invalid";

export type MappingPlacement = "header" | "footer" | "body" | "table" | "totals";

export interface FieldMapping {
  requirement_id: string;
  requirement: string;
  concept: string | null;
  placement: MappingPlacement | null;
  candidate_field_paths: string[];
  selected_field_path: string | null;
  supporting_field_paths: string[];
  conflict: boolean;
  conflicts_with: string[];
  evidence_score: number | null;
  data_type: string | null;
  schema_evidence: string | null;
  confidence_score: number | null;
  status: MappingStatus;
  explanation: string;
}

export interface MappingReport {
  mappings: FieldMapping[];
  schema_id: string | null;
}

/* ------------------------------------------------------------- validation */

export type CheckStatus =
  | "passed"
  | "failed"
  | "warning"
  | "skipped"
  | "not_tested";

export type ValidationLevel =
  | "structural"
  | "semantic"
  | "logical"
  | "visual"
  | "compatibility";

export type FindingSeverity = "error" | "warning" | "info";

export interface Finding {
  code: string;
  severity: FindingSeverity;
  message: string;
  location: string | null;
}

export interface CheckResult {
  id: string;
  level: ValidationLevel;
  name: string;
  status: CheckStatus;
  summary: string;
  findings: Finding[];
}

export interface ValidationReport {
  schema_id: string | null;
  target: string;
  ir_digest: string;
  checks: CheckResult[];
  package: Record<string, unknown> | null;
}

export interface ValidationStatuses {
  structural: CheckStatus;
  semantic: CheckStatus;
  logical: CheckStatus;
  visual: CheckStatus;
  docentric_compatibility: CheckStatus;
}

export type OverallStatus =
  | "passed"
  | "passed_unverified_compatibility"
  | "failed";

/* --------------------------------------------------------------- quality */

export type QualityStatus = "passed" | "warning" | "failed";

export interface QualityCheck {
  id: string;
  label: string;
  status: QualityStatus;
  message: string;
  path?: string | null;
}

export interface QualityMetrics {
  page: string;
  text_width_mm: number;
  tables: number;
  images: number;
  blocks: number;
}

export interface QualityReport {
  overall: QualityStatus;
  checks: QualityCheck[];
  metrics: QualityMetrics;
}

/* -------------------------------------------------------------- routing */

export type Complexity = "simple" | "standard" | "complex" | "ambiguous";

export type RoutingTier = "fast" | "balanced" | "advanced";

export interface RoutingPolicyEntry {
  tier: RoutingTier;
  providers: string[];
  budget_usd: number;
  strategy: string;
}

export type RoutingPolicy = Record<Complexity, RoutingPolicyEntry>;

export interface RouteDecision {
  complexity: Complexity;
  provider: string;
  model: string | null;
  reason: string[];
  budget_usd: number;
  requires_review: boolean;
  fallback_used: boolean;
}

/* ------------------------------------------------------------------ IR */

export interface TemplateIrBlock {
  kind: string;
  [key: string]: unknown;
}

export interface TemplateIrSection {
  kind: "section";
  name: string;
  body: TemplateIrBlock[];
  header: TemplateIrBlock[] | null;
  footer: TemplateIrBlock[] | null;
}

export interface TemplateIrMetadata {
  template_name: string;
  source_schema_id: string;
  design_style: "classic" | "modern" | "minimal" | null;
  intent: string | null;
  generator: string | null;
  notes: string | null;
}

export interface TemplateIrPage {
  size: string;
  orientation: string;
  margin_top_mm: number;
  margin_right_mm: number;
  margin_bottom_mm: number;
  margin_left_mm: number;
}

export interface TemplateIr {
  kind: "document";
  ir_version: string;
  title: string;
  language: string;
  target: string;
  page: TemplateIrPage;
  metadata: TemplateIrMetadata;
  sections: TemplateIrSection[];
}

/* ------------------------------------------------------------- artifacts */

export interface ArtifactView {
  id: string;
  kind: string;
  filename: string;
  media_type: string;
  size_bytes: number;
  digest: string;
  url: string;
  expires_at: number;
}

/* ---------------------------------------------------------------- system */

export interface ProviderView {
  name: string;
  configured: boolean;
  default_model: string | null;
  models: string[];
}

export interface HealthView {
  status: string;
  version: string;
  environment: string;
  docentric_ax_adapter_enabled: boolean;
}

export interface CompilerCapability {
  target: string;
  available: boolean;
  verified: boolean;
  status: string;
}

export interface CapabilitiesView {
  compilers: CompilerCapability[];
  features: Record<string, boolean>;
  limits: Record<string, number>;
}

export interface JobView {
  job_id: string;
  kind: string;
  status: string;
  duration_ms: number | null;
  result: Record<string, unknown> | null;
  error: Record<string, unknown> | null;
}

/* --------------------------------------------------------------- requests */

export type DesignStyle = "classic" | "modern" | "minimal";
export type CompileTarget = "generic-docx" | "docentric-ax";
export type RenderMode = "auto" | "sample" | "placeholder";

export interface PlanOptionsRequest {
  language: string;
  strict_validation: boolean;
  max_generation_cost_usd: number;
  max_repair_attempts: number;
}

export interface PlanRequest {
  source_id: string;
  prompt: string;
  provider: string;
  model: string | null;
  design_style: DesignStyle;
  target: CompileTarget;
  options: PlanOptionsRequest;
}

export interface CompileOptionsRequest {
  render_mode: RenderMode;
  include_compatibility_stamp: boolean;
  document_name: string;
  use_sample_data: boolean;
}

export interface CompileRequest {
  source_id: string;
  template_id: string | null;
  version: number | null;
  target: CompileTarget;
  options: CompileOptionsRequest;
}

export interface RevisionRequest {
  source_id: string;
  template_id: string;
  version: number | null;
  instruction: string;
  provider: string;
  model: string | null;
}

export interface ValidateRequest {
  source_id: string;
  template_id: string | null;
  version: number | null;
  target: CompileTarget;
}

export interface PreviewRequest {
  source_id: string;
  template_id?: string | null;
  version?: number | null;
  /** Render an inline IR instead of loading a stored version. */
  ir?: TemplateIr | null;
}

export interface RouteRequest {
  source_id: string;
  prompt: string;
}

export interface QualityRequest {
  source_id: string;
  template_id?: string | null;
  version?: number | null;
  /** Analyse an inline IR instead of loading a stored version. */
  ir?: TemplateIr | null;
}

export interface OptimizeRequest {
  source_id: string;
  template_id: string;
  version: number;
}

export interface CompareTarget {
  provider: string;
  model: string | null;
}

export interface CompareRequest {
  source_id: string;
  prompt: string;
  targets: CompareTarget[];
}

export interface ConfirmMappingRequest {
  selected_field_path: string | null;
  note: string | null;
}

export interface ConfirmMappingResponse {
  template_id: string;
  /** The new immutable version created by the review action. */
  version: number;
  requirement_id: string;
  selected_field_path: string | null;
  mapping: MappingReport;
  report: ValidationReport;
  validation: ValidationStatuses;
  ir: TemplateIr;
  ir_digest: string;
  rebind_count: number;
}

/* ------------------------------------------------------------------ demo */

export interface DemoCase {
  id: string;
  title: string;
  description: string;
  prompt: string;
}

export interface DemoTourStep {
  target: string;
  title: string;
  body: string;
}

export interface DemoSessionRequest {
  case_id: string;
}

/** Shape of `POST /api/v1/demo/sessions`. */
export interface DemoSessionResponse {
  case: DemoCase;
  source_id: string;
  schema_id: string;
  sections: string[];
  stats: SchemaStats;
  diagnostics: Diagnostic[];
  template_id: string;
  version: number;
  ir: TemplateIr;
  ir_digest: string;
  mapping: MappingReport;
  report: ValidationReport;
  validation: ValidationStatuses;
  preview_html: string;
  /** Present on every demo case; seeded into the quality dashboard. */
  quality?: QualityReport | null;
  docx_artifact_id: string;
  artifacts: ArtifactView[];
  tour: DemoTourStep[];
  elapsed_ms: number;
}

/* -------------------------------------------------------------- responses */

export interface GenerationUsage {
  prompt_tokens: number;
  completion_tokens: number;
  estimated_cost_usd: number;
}

export interface GenerationInfo {
  provider: string;
  model: string;
  usage: GenerationUsage;
  latency_ms: number;
  finish_reason: string | null;
  attempts: number;
}

export interface RemovedBinding {
  path: string;
  reason: string;
  block_kind: string;
}

export interface PlanResponse {
  job_id: string;
  status: string;
  template_id: string;
  version: number;
  ir_digest: string;
  ir: TemplateIr;
  mapping: MappingReport;
  report: ValidationReport;
  validation: ValidationStatuses;
  warnings: string[];
  removed_bindings: RemovedBinding[];
  generation: GenerationInfo | null;
  artifacts: ArtifactView[];
}

export interface CompileResponse {
  job_id: string;
  status: string;
  artifact_id: string;
  ir_digest: string;
  validation: ValidationStatuses;
  report: ValidationReport;
  warnings: string[];
  stats: Record<string, number>;
  artifacts: ArtifactView[];
}

export interface ValidateResponse {
  validation: ValidationStatuses;
  overall: string;
  report: ValidationReport;
}

export interface RouteResponse {
  decision: RouteDecision;
  policy: RoutingPolicy;
  requirements: number;
}

export interface QualityResponse {
  report: QualityReport;
  ir_digest: string;
}

export interface OptimizeFix {
  id: string;
  message: string;
  path?: string | null;
}

export interface OptimizeResponse {
  template_id: string;
  /** The new immutable version created by the optimisation. */
  version: number;
  fixes: OptimizeFix[];
  before: QualityReport;
  after: QualityReport;
  ir: TemplateIr;
  ir_digest: string;
  validation: Record<string, string>;
}

export interface CompareRun {
  provider: string;
  model: string | null;
  ok: boolean;
  error?: string | null;
  latency_ms: number;
  tokens: number;
  cost_usd?: number | null;
  counts: Partial<Record<MappingStatus, number>>;
  validation: Record<string, string>;
  ir_digest?: string | null;
  requirements: number;
}

export interface CompareResponse {
  runs: CompareRun[];
  recommended: string | null;
  note: string;
}

export interface RevisionChange {
  path: string;
  kind: "added" | "removed" | "changed";
  before: unknown;
  after: unknown;
}

export interface RevisionChangeSummary {
  total: number;
  counts: {
    added: number;
    removed: number;
    changed: number;
  };
  examples: RevisionChange[];
}

export interface RevisionResponse {
  job_id: string;
  status: string;
  template_id: string;
  version: number;
  ir_digest: string;
  ir: TemplateIr;
  mapping: MappingReport;
  report: ValidationReport;
  validation: ValidationStatuses;
  change_summary: RevisionChangeSummary;
  changes: RevisionChange[];
  warnings: string[];
  artifacts: ArtifactView[];
}

export interface VersionSummary {
  version: number;
  created_at: number;
  provider: string | null;
  model: string | null;
}

export interface VersionsResponse {
  template_id: string;
  versions: VersionSummary[];
}

/** Shape of `GET /api/v1/templates/{template_id}/export/{version}`. */
export interface TemplateVersionDetail {
  template_id: string;
  version: number;
  ir_digest: string;
  ir: TemplateIr;
  mapping: MappingReport;
  validation: ValidationReport;
  canonical_ir: string;
}
