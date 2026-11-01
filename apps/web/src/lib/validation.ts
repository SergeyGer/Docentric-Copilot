/**
 * Validation status derivation.
 *
 * The backend deliberately reports `not_tested` as a first-class status and the
 * five levels are never collapsed into a boolean. These helpers mirror
 * `ValidationReport.level_status()` / `.statuses()` from the Python package so
 * that a version loaded through the export endpoint can be reviewed with the
 * same semantics as a fresh plan response.
 */

import type {
  CheckResult,
  CheckStatus,
  OverallStatus,
  ValidationLevel,
  ValidationReport,
  ValidationStatuses,
} from "@/lib/types";

export interface ValidationLevelMeta {
  key: keyof ValidationStatuses;
  level: ValidationLevel;
  code: string;
  label: string;
  description: string;
}

export const VALIDATION_LEVELS: readonly ValidationLevelMeta[] = [
  {
    key: "structural",
    level: "structural",
    code: "V1",
    label: "Structural",
    description: "IR shape, schema paths and package integrity.",
  },
  {
    key: "semantic",
    level: "semantic",
    code: "V2",
    label: "Semantic",
    description: "Bindings target real fields with compatible types.",
  },
  {
    key: "logical",
    level: "logical",
    code: "V3",
    label: "Logical",
    description: "Expressions, repeats and conditions are coherent.",
  },
  {
    key: "visual",
    level: "visual",
    code: "V4",
    label: "Visual",
    description: "Layout and generated package are inspected.",
  },
  {
    key: "docentric_compatibility",
    level: "compatibility",
    code: "V5",
    label: "Docentric compatibility",
    description: "AX adapter checks. Reported as not tested unless enabled.",
  },
];

export function statusLabel(status: CheckStatus): string {
  switch (status) {
    case "passed":
      return "Passed";
    case "failed":
      return "Failed";
    case "warning":
      return "Warning";
    case "skipped":
      return "Skipped";
    case "not_tested":
      return "Not tested";
    default:
      return status;
  }
}

export function overallLabel(overall: OverallStatus): string {
  switch (overall) {
    case "passed":
      return "Passed";
    case "passed_unverified_compatibility":
      return "Passed · compatibility unverified";
    case "failed":
      return "Failed";
    default:
      return overall;
  }
}

export function levelStatus(checks: CheckResult[], level: ValidationLevel): CheckStatus {
  const results = checks.filter((check) => check.level === level);
  if (results.length === 0) {
    return "skipped";
  }
  if (results.some((check) => check.status === "failed")) {
    return "failed";
  }
  const active = results.filter(
    (check) => check.status !== "not_tested" && check.status !== "skipped",
  );
  if (active.length === 0) {
    return results.some((check) => check.status === "not_tested") ? "not_tested" : "skipped";
  }
  if (active.some((check) => check.status === "warning")) {
    return "warning";
  }
  return "passed";
}

export function deriveStatuses(report: ValidationReport): ValidationStatuses {
  return {
    structural: levelStatus(report.checks, "structural"),
    semantic: levelStatus(report.checks, "semantic"),
    logical: levelStatus(report.checks, "logical"),
    visual: levelStatus(report.checks, "visual"),
    docentric_compatibility: levelStatus(report.checks, "compatibility"),
  };
}

export function overallFromStatuses(statuses: ValidationStatuses): OverallStatus {
  const compilable = [statuses.structural, statuses.semantic, statuses.logical].every(
    (status) => status === "passed" || status === "warning",
  );
  if (!compilable) {
    return "failed";
  }
  if (statuses.docentric_compatibility === "not_tested") {
    return "passed_unverified_compatibility";
  }
  return "passed";
}

export interface ReportCounts {
  checks: number;
  errors: number;
  warnings: number;
  infos: number;
}

export function countFindings(report: ValidationReport | null): ReportCounts {
  if (!report) {
    return { checks: 0, errors: 0, warnings: 0, infos: 0 };
  }
  let errors = 0;
  let warnings = 0;
  let infos = 0;
  for (const check of report.checks) {
    for (const finding of check.findings) {
      if (finding.severity === "error") {
        errors += 1;
      } else if (finding.severity === "warning") {
        warnings += 1;
      } else {
        infos += 1;
      }
    }
  }
  return { checks: report.checks.length, errors, warnings, infos };
}
