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

/** How the prompt panel chooses the model for a plan. */
export type RoutingMode = "manual" | "auto";

export interface PlanRequest {
  source_id: string;
  prompt: string;
  /** Required for manual planning; omitted when `routing` is `"auto"`. */
  provider?: string;
  /** Required for manual planning (`null` uses the provider default); omitted for auto. */
  model?: string | null;
  /**
   * `auto` asks the router to classify the brief and execute its choice.
   * Manual mode omits the field entirely and keeps the explicit provider/model.
   */
  routing?: "auto";
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
  /** `null` when the model has no published price (N/A, not free). */
  estimated_cost_usd: number | null;
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

export interface RoutingExecutionTrace {
  decision: RouteDecision;
  actual_provider: string;
  actual_model: string | null;
  /** The preferred tier was unavailable (including the deterministic fallback). */
  fallback: boolean;
  /** True only when the recommended provider equals the executed provider. */
  match: boolean;
  run_id: string;
  started_at: string;
  finished_at: string;
  usage: GenerationUsage | null;
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
  /** Present only for `routing: "auto"`. */
  routing: RoutingExecutionTrace | null;
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
  before?: number | null;
  after?: number | null;
}

export interface IrDiffEntry {
  path: string;
  kind: "changed";
  before: number | null;
  after: number | null;
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
  /** Only changed width and font fields, with structural IR paths. */
  ir_diff: IrDiffEntry[];
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

/* ------------------------------------------------------- reference inspector */

export type ReferenceRuntimeCompatibility = "not_tested";
export type ReferenceSourceType = "docx" | "zip" | "axpp" | "directory";
export type ReferencePlatformHint = "ax2012" | "d365" | "mixed" | "unknown";
export type ReferenceArtifactKind =
  | "docx"
  | "ddsp"
  | "xml"
  | "xsd"
  | "axpp"
  | "zip"
  | "xpo"
  | "project"
  | "text"
  | "other";
export type ReferenceSeverity = "info" | "warning" | "error";
export type ReferenceStoryPart =
  | "document"
  | "header"
  | "footer"
  | "footnote"
  | "endnote"
  | "comment"
  | "glossary"
  | "other";
export type ReferenceControlType =
  | "text"
  | "date"
  | "dropdown"
  | "picture"
  | "rich_text"
  | "checkbox"
  | "group"
  | "building_block"
  | "citation"
  | "equation"
  | "repeating_section"
  | "unknown";
export type ReferenceElementKind =
  | "field"
  | "list"
  | "if"
  | "image"
  | "label"
  | "barcode"
  | "summary_field"
  | "sub_document"
  | "group"
  | "unknown";
export type ReferenceClassification = "recognized" | "ambiguous" | "unknown";
export type ReferenceResolutionStatus =
  | "resolved"
  | "missing_part"
  | "unknown_path"
  | "ambiguous";
export type ReferenceLinkStatus =
  | "resolved_by_id"
  | "resolved_by_id_shared"
  | "no_sdt_id"
  | "no_project_data"
  | "missing_store_item"
  | "store_item_not_project_data"
  | "no_element_for_id"
  | "duplicate_id_collision"
  | "multiple_project_data_parts"
  | "type_mismatch";
export type ReferencePathStatus =
  | "matched"
  | "not_checked"
  | "unknown"
  | "section_missing"
  | "ambiguous";
export type ReferenceSchemaSource = "ddsp" | "d365_project_data" | "mixed" | "none";
export type ReferenceBindingStatus =
  | "resolved"
  | "ambiguous"
  | "unknown_path"
  | "type_mismatch"
  | "schema_unavailable"
  | "unsupported_expression";
export type ReferenceGraphNodeKind = "control" | "element" | "source" | "schema_field";
export type ReferenceGraphEdgeType = "bound_to" | "resolves_to" | "iterates" | "condition";
export type ReferenceGraphStatus = "resolved" | "ambiguous" | "unknown";
export type ReferenceDiffItemKind =
  | "control"
  | "element"
  | "binding"
  | "source"
  | "schema_field";
export type ReferenceChangeType = "added" | "removed" | "changed";
export type ReferenceChangeDimension = "structural" | "semantic";

export interface ReferenceVersionHints {
  platform: ReferencePlatformHint;
  product_versions: string[];
  evidence: string[];
}

export interface ReferenceInventoryEntry {
  path: string;
  name: string;
  parent: string | null;
  kind: ReferenceArtifactKind;
  size_bytes: number;
  sha256: string;
  nested_depth: number;
  is_archive: boolean;
  expanded: boolean;
  platform_hint: ReferencePlatformHint;
  product_version: string | null;
  warnings: string[];
}

export interface ReferenceDuplicateGroup {
  sha256: string;
  kind: ReferenceArtifactKind;
  occurrences: number;
  paths: string[];
}

export interface ReferenceInventory {
  source_type: ReferenceSourceType;
  source_name: string;
  source_sha256: string;
  source_size_bytes: number;
  container: ReferenceVersionHints;
  entries: ReferenceInventoryEntry[];
  duplicates: ReferenceDuplicateGroup[];
  nested_archives: string[];
  warnings: string[];
}

export interface ReferenceDataBinding {
  xpath: string | null;
  store_item_id: string | null;
  prefix_mappings: string | null;
}

export interface ReferenceSourceBinding {
  source: string | null;
  path: string | null;
  result_data_type: string | null;
  data_kind: string | null;
}

export interface ReferenceControlResolution {
  status: ReferenceResolutionStatus;
  link_status: ReferenceLinkStatus;
  path_status: ReferencePathStatus;
  element_id_unsigned: string | null;
  element_type: string | null;
  source_binding: ReferenceSourceBinding | null;
  source_binding_raw: ReferenceSourceBinding | null;
  normalized_path: string | null;
  schema_section: string | null;
  schema_source: ReferenceSchemaSource;
  diagnostic_codes: string[];
  path_suggestions: string[];
}

export interface ReferenceControl {
  part: string;
  story: ReferenceStoryPart;
  paragraph_index: number;
  ordinal: number;
  depth: number;
  tag: string | null;
  alias: string | null;
  sdt_id_signed: number | null;
  sdt_id_unsigned: string | null;
  control_type: ReferenceControlType;
  placeholder: string | null;
  data_binding: ReferenceDataBinding;
  text_preview: string;
  has_dc_namespace: boolean;
  dc_namespaces: string[];
  markers: string[];
  element_kind: ReferenceElementKind;
  classification: ReferenceClassification;
  classification_reason: string;
  resolution: ReferenceControlResolution;
}

export interface ReferenceProjectDataPart {
  part: string;
  store_item_id: string | null;
  product_id: string | null;
  product_version: string | null;
  data_sources: string[];
  element_count: number;
  duplicate_element_ids: number;
}

export interface ReferenceSchemaStats {
  node_count: number;
  scalar_count: number;
  collection_count: number;
  attribute_count: number;
  max_depth: number;
}

export interface ReferenceDdspDataSectionEvidence {
  name: string;
  root_elements: string[];
  field_count: number;
  collection_count: number;
  max_depth: number;
  sample_values_present: boolean;
  schema_present: boolean;
}

export interface ReferenceDdspSchemaEvidence {
  schema_format: string;
  schema_id: string;
  schema_digest: string;
  root_element: string | null;
  namespace: string | null;
  contract_version: string | null;
  product_version: string | null;
  flavour: string | null;
  flavour_label: string | null;
  language: string | null;
  template_id: string | null;
  docu_type_id: string | null;
  locales: string[];
  sections: string[];
  data_sections: ReferenceDdspDataSectionEvidence[];
  label_count: number;
  field_count: number;
  collection_count: number;
  repeating_sections: string[];
  sample_values_present: boolean;
  unsupported_constructs: string[];
  stats: ReferenceSchemaStats;
}

export interface ReferenceElementEvidence {
  element_id_unsigned: string;
  element_type: string;
  element_kind: ReferenceElementKind;
  project_data_part: string;
  source_binding: ReferenceSourceBinding | null;
  effective_binding: ReferenceSourceBinding | null;
  binding_notes: string[];
  child_element_ids: string[];
  parent_element_ids: string[];
  attributes: Record<string, string>;
  properties: Record<string, string>;
}

export interface ReferenceDocumentEvidence {
  sha256: string;
  paths: string[];
  filename: string;
  size_bytes: number;
  platform: ReferencePlatformHint;
  product_version: string | null;
  project_data: ReferenceProjectDataPart[];
  schema_source: ReferenceSchemaSource;
  schema_sections: string[];
  schema_paths: number;
  schema_evidence: ReferenceDdspSchemaEvidence | null;
  metadata_elements: ReferenceElementEvidence[];
  control_count: number;
  classification_counts: Record<string, number>;
  resolution_counts: Record<string, number>;
  link_status_counts: Record<string, number>;
  path_status_counts: Record<string, number>;
  joined_count: number;
  join_coverage_ratio: number;
  coverage_ratio: number;
  has_macros: boolean;
  has_active_x: boolean;
  has_embedded_objects: boolean;
  has_external_relationships: boolean;
  warnings: string[];
  controls: ReferenceControl[];
}

export interface ReferenceCounts {
  artifacts: number;
  distinct_artifacts: number;
  docx_artifacts: number;
  distinct_docx: number;
  controls_total: number;
  by_element_kind: Record<string, number>;
  by_classification: Record<string, number>;
  by_resolution: Record<string, number>;
  by_link_status: Record<string, number>;
  by_path_status: Record<string, number>;
  by_part: Record<string, number>;
  by_story: Record<string, number>;
  classification_recognized: number;
  classification_ambiguous: number;
  classification_unknown: number;
  resolved: number;
  missing_part: number;
  unknown_path: number;
  ambiguous: number;
  joined_by_id: number;
  join_coverage_ratio: number;
  duplicate_groups: number;
  duplicate_occurrences: number;
  nested_archives: number;
  coverage_ratio: number;
}

export interface ReferenceDiagnostic {
  code: string;
  severity: ReferenceSeverity;
  message: string;
  document_sha256: string | null;
  part: string | null;
  ordinal: number | null;
  details: Record<string, string>;
}

export interface ReferenceReport {
  reference_version: string;
  inspector: string;
  runtime_compatibility: ReferenceRuntimeCompatibility;
  source_type: ReferenceSourceType;
  source_name: string;
  source_sha256: string;
  container: ReferenceVersionHints;
  counts: ReferenceCounts;
  duplicates: ReferenceDuplicateGroup[];
  nested_archives: string[];
  documents: ReferenceDocumentEvidence[];
  diagnostics: ReferenceDiagnostic[];
  warnings: string[];
  inventory: ReferenceInventory;
  report_digest: string;
}

/* ----------------------------------------------------------- reference graph */

export interface ReferenceGraphNode {
  id: string;
  kind: ReferenceGraphNodeKind;
  label: string;
  status: ReferenceGraphStatus;
  document_sha256: string | null;
  document_name: string | null;
  part: string | null;
  ordinal: number | null;
  paragraph_index: number | null;
  depth: number | null;
  element_id: string | null;
  element_kind: ReferenceElementKind | null;
  source_name: string | null;
  binding_path: string | null;
  normalized_path: string | null;
  schema_path: string | null;
  data_type: string | null;
  collection: boolean;
  origin: string | null;
  reason: string | null;
  schema_source: ReferenceSchemaSource | null;
  source_id: string | null;
  evidence_location: string | null;
  evidence: Record<string, string>;
}

export interface ReferenceGraphEdge {
  id: string;
  type: ReferenceGraphEdgeType;
  source: string;
  target: string;
  status: ReferenceGraphStatus;
  resolution_status: ReferenceBindingStatus | null;
  reason: string | null;
  evidence: Record<string, string>;
}

export interface ReferenceGraphStructure {
  node_id: string;
  kind: ReferenceElementKind;
  label: string;
  binding_path: string | null;
  source_name: string | null;
  target_count: number;
  status: ReferenceGraphStatus;
  detail: string | null;
}

export interface ReferenceGraphStructures {
  lists: ReferenceGraphStructure[];
  conditions: ReferenceGraphStructure[];
}

export interface ReferenceGraphUnresolved {
  node_id: string;
  kind: ReferenceGraphNodeKind;
  label: string;
  status: ReferenceGraphStatus;
  reason: string;
}

export interface ReferenceGraphSummary {
  node_count: number;
  edge_count: number;
  by_node_kind: Record<string, number>;
  by_node_status: Record<string, number>;
  by_edge_type: Record<string, number>;
  by_edge_status: Record<string, number>;
  resolved_edges: number;
  ambiguous_edges: number;
  unknown_edges: number;
  edge_coverage_ratio: number;
  controls_total: number;
  controls_resolved: number;
  controls_ambiguous: number;
  controls_unknown: number;
  controls_bound: number;
  elements_total: number;
  sources_total: number;
  schema_fields_total: number;
  schema_fields_resolved: number;
  resolves_to_edges: number;
  resolves_to_resolved: number;
  resolves_to_with_evidence: number;
  evidence_coverage_ratio: number;
  unresolved_by_status: Record<string, number>;
  unresolved_reasons: Record<string, number>;
  lists_detected: number;
  conditions_detected: number;
  unresolved_total: number;
}

export interface ReferenceGraph {
  graph_version: string;
  reference_version: string;
  runtime_compatibility: ReferenceRuntimeCompatibility;
  ir_kind: "reference";
  compilable: false;
  note: string;
  source_type: ReferenceSourceType;
  source_name: string;
  source_sha256: string;
  platform: ReferencePlatformHint;
  schema_source: ReferenceSchemaSource;
  schema_provider_types: string[];
  schema_ids: string[];
  schema_sections: string[];
  schema_digests: string[];
  nodes: ReferenceGraphNode[];
  edges: ReferenceGraphEdge[];
  structures: ReferenceGraphStructures;
  unresolved: ReferenceGraphUnresolved[];
  summary: ReferenceGraphSummary;
  diagnostics: ReferenceDiagnostic[];
  graph_digest: string;
}

export type ReferenceReportKind = "inspection" | "graph" | "diff";
export type ReferenceReportExportFormat = "json" | "html";

/** Persisted reference report envelope (`POST/GET /api/v1/reference/reports`). */
export interface StoredReferenceReport {
  report_version: string;
  runtime_compatibility: ReferenceRuntimeCompatibility;
  id: string;
  kind: ReferenceReportKind;
  schema_version: string;
  created_at: number;
  expires_at: number;
  source_name: string;
  source_sha256: string | null;
  report: ReferenceReport | null;
  graph: ReferenceGraph | null;
  diff: ReferenceDiff | null;
  warnings: string[];
}

/* ------------------------------------------------------------ reference diff */

export interface ReferenceDiffSnapshot {
  kind: string | null;
  binding_path: string | null;
  status: ReferenceGraphStatus;
  part: string | null;
  paragraph_index: number | null;
  source: string | null;
  data_type: string | null;
  collection: boolean | null;
}

export interface ReferenceDiffItem {
  key: string;
  kind: ReferenceDiffItemKind;
  change: ReferenceChangeType;
  dimension: ReferenceChangeDimension;
  before: ReferenceDiffSnapshot | null;
  after: ReferenceDiffSnapshot | null;
  fields: string[];
}

export interface ReferenceDiffCountPair {
  left: number;
  right: number;
  delta: number;
}

export interface ReferenceDiffCounts {
  controls: ReferenceDiffCountPair;
  elements: ReferenceDiffCountPair;
  sources: ReferenceDiffCountPair;
  schema_fields: ReferenceDiffCountPair;
  edges: ReferenceDiffCountPair;
  parts: ReferenceDiffCountPair;
  parts_added: string[];
  parts_removed: string[];
}

export interface ReferenceDiffDimension {
  dimension: ReferenceChangeDimension;
  added: number;
  removed: number;
  changed: number;
  total: number;
  by_kind: Record<string, number>;
  keys: string[];
}

export interface ReferenceDiffSummary {
  added: number;
  removed: number;
  changed: number;
  total: number;
  ambiguous: number;
  structural: number;
  semantic: number;
  by_kind: Record<string, number>;
  by_change: Record<string, number>;
  status_transitions: Record<string, number>;
  added_keys: string[];
  removed_keys: string[];
  changed_keys: string[];
}

export interface ReferenceCoverageDelta {
  left_edge_coverage: number;
  right_edge_coverage: number;
  edge_delta: number;
  delta: number;
  left_control_coverage: number;
  right_control_coverage: number;
  control_delta: number;
}

export interface ReferenceUnresolvedDelta {
  left: number;
  right: number;
  delta: number;
  added_keys: string[];
  removed_keys: string[];
}

export interface ReferenceDiffSide {
  source_type: ReferenceSourceType;
  source_name: string;
  source_sha256: string;
  graph_version: string;
  graph_digest: string;
  schema_source: ReferenceSchemaSource;
  schema_ids: string[];
  summary: ReferenceGraphSummary;
}

export interface ReferenceDiff {
  diff_version: string;
  reference_version: string;
  runtime_compatibility: ReferenceRuntimeCompatibility;
  ir_kind: "reference";
  compilable: false;
  note: string;
  left: ReferenceDiffSide;
  right: ReferenceDiffSide;
  items: ReferenceDiffItem[];
  structural: ReferenceDiffDimension;
  semantic: ReferenceDiffDimension;
  summary: ReferenceDiffSummary;
  counts: ReferenceDiffCounts;
  coverage_delta: ReferenceCoverageDelta;
  unresolved_delta: number;
  unresolved: ReferenceUnresolvedDelta;
  diff_digest: string;
}
