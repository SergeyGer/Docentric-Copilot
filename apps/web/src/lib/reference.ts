/**
 * Presentation helpers for the read-only reference template inspector.
 *
 * The API returns structural JSON only; nothing here evaluates a binding,
 * follows a relationship or claims runtime compatibility.
 */

import { formatNumber, humanizeKey } from "@/lib/format";
import type {
  ReferenceControl,
  ReferenceDocumentEvidence,
  ReferenceReport,
} from "@/lib/types";

export const REFERENCE_TEMPLATE_EXTENSIONS = [".docx", ".zip", ".axpp"] as const;
export const REFERENCE_SCHEMA_EXTENSIONS = [".xml", ".ddsp"] as const;

/**
 * Controls are rendered as ordinary table rows up to this size. Above it the
 * table is paginated so a very large report never mounts thousands of rows.
 */
export const REFERENCE_CONTROLS_PAGINATION_THRESHOLD = 500;
export const REFERENCE_CONTROLS_PAGE_SIZE = 100;

export const CLASSIFICATION_LABELS: Record<string, string> = {
  recognized: "Recognized",
  ambiguous: "Ambiguous",
  unknown: "Unknown",
};

export const RESOLUTION_LABELS: Record<string, string> = {
  resolved: "Resolved",
  missing_part: "Missing part",
  unknown_path: "Unknown path",
  ambiguous: "Ambiguous",
};

export const LINK_STATUS_LABELS: Record<string, string> = {
  resolved_by_id: "Resolved by SDT id",
  resolved_by_id_shared: "Resolved by shared SDT id",
  no_sdt_id: "No SDT id",
  no_project_data: "No ProjectData",
  missing_store_item: "Missing store item",
  store_item_not_project_data: "Store item is not ProjectData",
  no_element_for_id: "No element for id",
  duplicate_id_collision: "Duplicate element id collision",
  multiple_project_data_parts: "Multiple ProjectData parts",
  type_mismatch: "Element type mismatch",
};

export const PATH_STATUS_LABELS: Record<string, string> = {
  matched: "Matched",
  not_checked: "Not checked",
  unknown: "Unknown",
  section_missing: "Section missing",
  ambiguous: "Ambiguous",
};

export const GRAPH_STATUS_LABELS: Record<string, string> = {
  resolved: "Resolved",
  ambiguous: "Ambiguous",
  unknown: "Unknown",
};

export const EDGE_TYPE_LABELS: Record<string, string> = {
  bound_to: "Bound to",
  resolves_to: "Resolves to",
  iterates: "Iterates",
  condition: "Condition",
};

export const NODE_KIND_LABELS: Record<string, string> = {
  control: "Control",
  element: "Element",
  source: "Source",
  schema_field: "Schema field",
};

export const ELEMENT_KIND_LABELS: Record<string, string> = {
  field: "Field",
  list: "List",
  if: "Conditional",
  image: "Image",
  label: "Label",
  barcode: "Barcode",
  summary_field: "Summary field",
  sub_document: "Sub-document",
  group: "Group",
  unknown: "Unknown",
};

export const CONTROL_TYPE_LABELS: Record<string, string> = {
  text: "Text",
  date: "Date",
  dropdown: "Dropdown",
  picture: "Picture",
  rich_text: "Rich text",
  checkbox: "Checkbox",
  group: "Group",
  building_block: "Building block",
  citation: "Citation",
  equation: "Equation",
  repeating_section: "Repeating section",
  unknown: "Unknown",
};

export const STORY_LABELS: Record<string, string> = {
  document: "Document",
  header: "Header",
  footer: "Footer",
  footnote: "Footnote",
  endnote: "Endnote",
  comment: "Comment",
  glossary: "Glossary",
  other: "Other",
};

export const PLATFORM_LABELS: Record<string, string> = {
  ax2012: "Docentric AX 2012",
  d365: "Dynamics 365",
  mixed: "Mixed platform hints",
  unknown: "Unknown platform",
};

export const SOURCE_TYPE_LABELS: Record<string, string> = {
  docx: "DOCX document",
  zip: "ZIP package",
  axpp: "AXPP package",
  directory: "Directory",
};

export const SCHEMA_SOURCE_LABELS: Record<string, string> = {
  ddsp: "DDSP schema",
  d365_project_data: "D365 embedded schema",
  mixed: "DDSP + D365 schema",
  none: "No schema",
};

/** Exact binding resolver statuses carried by `resolves_to` edges. */
export const BINDING_STATUS_LABELS: Record<string, string> = {
  resolved: "Resolved",
  ambiguous: "Ambiguous",
  unknown_path: "Unknown path",
  type_mismatch: "Type mismatch",
  schema_unavailable: "Schema unavailable",
  unsupported_expression: "Unsupported expression",
};

export const SEVERITY_LABELS: Record<string, string> = {
  info: "Info",
  warning: "Warning",
  error: "Error",
};

export const CHANGE_LABELS: Record<string, string> = {
  added: "Added",
  removed: "Removed",
  changed: "Changed",
};

export const DIMENSION_LABELS: Record<string, string> = {
  structural: "Structural",
  semantic: "Semantic",
};

export const DIFF_ITEM_KIND_LABELS: Record<string, string> = {
  control: "Control",
  element: "Element",
  binding: "Binding",
  source: "Source",
  schema_field: "Schema field",
};

/** Labels for the before/after fields reported by ReferenceDiff. */
export const SNAPSHOT_FIELD_LABELS: Record<string, string> = {
  kind: "Kind",
  binding_path: "Binding",
  status: "Status",
  part: "Part",
  paragraph_index: "Paragraph",
  source: "Source",
  data_type: "Data type",
  collection: "Collection",
};

export function referenceEnumLabel(labels: Record<string, string>, value: string): string {
  return labels[value] ?? humanizeKey(value);
}

export interface ReferenceControlRow {
  key: string;
  document: ReferenceDocumentEvidence;
  control: ReferenceControl;
}

/** Flatten every document's controls; no row is dropped, including unknown ones. */
export function flattenReferenceControls(report: ReferenceReport): ReferenceControlRow[] {
  const rows: ReferenceControlRow[] = [];
  for (const document of report.documents) {
    for (const control of document.controls) {
      rows.push({
        key: `${document.sha256}:${control.part}:${control.ordinal}`,
        document,
        control,
      });
    }
  }
  return rows;
}

export function referenceControlLabel(control: ReferenceControl): string {
  const candidate = control.alias ?? control.tag ?? control.placeholder;
  if (candidate && candidate.trim().length > 0) {
    return candidate.trim();
  }
  return `Control ${control.ordinal}`;
}

export function referenceControlSecondary(control: ReferenceControl): string | null {
  if (control.alias && control.tag && control.alias !== control.tag) {
    return `Tag: ${control.tag}`;
  }
  if (control.placeholder && control.alias) {
    return `Placeholder: ${control.placeholder}`;
  }
  return null;
}

/** The binding shown in the table; raw OOXML data binding is the last resort. */
export function referenceControlBinding(control: ReferenceControl): string | null {
  const resolved = control.resolution.source_binding ?? control.resolution.source_binding_raw;
  if (resolved?.path) {
    return resolved.source ? `${resolved.source}: ${resolved.path}` : resolved.path;
  }
  if (control.data_binding.xpath) {
    return control.data_binding.xpath;
  }
  return control.resolution.normalized_path;
}

export function referenceControlSearchText(row: ReferenceControlRow): string {
  const { control, document } = row;
  return [
    document.filename,
    control.part,
    control.story,
    control.tag,
    control.alias,
    control.placeholder,
    control.text_preview,
    control.element_kind,
    control.classification,
    control.classification_reason,
    control.resolution.status,
    control.resolution.link_status,
    control.resolution.path_status,
    control.resolution.element_id_unsigned,
    control.resolution.element_type,
    control.resolution.normalized_path,
    control.data_binding.xpath,
    referenceControlBinding(control),
    control.resolution.diagnostic_codes.join(" "),
  ]
    .filter((value): value is string => typeof value === "string" && value.length > 0)
    .join(" ")
    .toLocaleLowerCase();
}

export function controlMatchesQuery(row: ReferenceControlRow, query: string): boolean {
  const normalized = query.trim().toLocaleLowerCase();
  if (!normalized) {
    return true;
  }
  return normalized
    .split(/\s+/)
    .filter(Boolean)
    .every((token) => referenceControlSearchText(row).includes(token));
}

/** Percent formatting for coverage ratios in the 0–1 range. */
export function formatRatio(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "—";
  }
  return `${new Intl.NumberFormat("en-GB", { maximumFractionDigits: 1 }).format(value * 100)}%`;
}

/** Signed integer delta with an explicit sign for non-zero values. */
export function formatSignedDelta(delta: number): string {
  if (!Number.isFinite(delta) || delta === 0) {
    return "0";
  }
  return `${delta > 0 ? "+" : "-"}${formatNumber(Math.abs(delta))}`;
}

/** Signed coverage delta in percentage points. */
export function formatRatioDelta(delta: number | null | undefined): string {
  if (delta === null || delta === undefined || !Number.isFinite(delta) || delta === 0) {
    return "0 pp";
  }
  const points = Math.abs(delta) * 100;
  return `${delta > 0 ? "+" : "-"}${new Intl.NumberFormat("en-GB", {
    maximumFractionDigits: 1,
  }).format(points)} pp`;
}

/** Sort a count map by descending count, then by key for deterministic UI. */
export function sortCountEntries(record: Record<string, number>): Array<[string, number]> {
  return Object.entries(record).sort((left, right) => {
    if (right[1] !== left[1]) {
      return right[1] - left[1];
    }
    return left[0].localeCompare(right[0]);
  });
}

export function referenceFileExtension(filename: string): string {
  const index = filename.lastIndexOf(".");
  return index >= 0 ? filename.slice(index).toLocaleLowerCase() : "";
}

export function hasReferenceExtension(
  filename: string,
  allowed: readonly string[],
): boolean {
  return allowed.includes(referenceFileExtension(filename));
}
