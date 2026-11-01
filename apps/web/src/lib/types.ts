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

export type MappingStatus = "resolved" | "ambiguous" | "missing" | "invalid";

export interface FieldMapping {
  requirement_id: string;
  requirement: string;
  candidate_field_paths: string[];
  selected_field_path: string | null;
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
  template_id: string | null;
  version: number | null;
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
