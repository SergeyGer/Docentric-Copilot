/**
 * Quality report helpers.
 *
 * `POST /api/v1/templates/quality` reports three equally explicit statuses.
 * These helpers keep the summary and labels in one place so the dashboard and
 * the optimisation note count the same way.
 */

import type { QualityCheck, QualityReport, QualityStatus } from "@/lib/types";

export const QUALITY_STATUSES: readonly QualityStatus[] = ["passed", "warning", "failed"];

export function qualityStatusLabel(status: QualityStatus): string {
  switch (status) {
    case "passed":
      return "Passed";
    case "warning":
      return "Warning";
    case "failed":
      return "Failed";
    default:
      return status;
  }
}

export function countQualityChecks(report: QualityReport | null): Record<QualityStatus, number> {
  const counts: Record<QualityStatus, number> = { passed: 0, warning: 0, failed: 0 };
  for (const check of report?.checks ?? []) {
    counts[check.status] += 1;
  }
  return counts;
}

/** The dashboard renders checks in report order; this keeps the id stable in lists. */
export function qualityCheckKey(check: QualityCheck, index: number): string {
  return `${check.id}-${index}`;
}
