"use client";

import { useMemo } from "react";
import { AlertTriangle, CheckCircle2, FileText, ShieldAlert } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ScrollArea } from "@/components/ui/scroll-area";
import { EmptyState } from "@/components/workspace/empty-state";
import {
  FindingSeverityBadge,
  OverallStatusBadge,
  ValidationStatusBadge,
} from "@/components/workspace/status-badges";
import { Panel } from "@/components/workspace/panel";
import { PANEL_IDS } from "@/lib/constants";
import { formatNumber, pluralize } from "@/lib/format";
import {
  VALIDATION_LEVELS,
  countFindings,
  statusLabel,
} from "@/lib/validation";
import type {
  OverallStatus,
  ValidationReport,
  ValidationStatuses,
} from "@/lib/types";
import { cn } from "@/lib/utils";

function levelTone(status: string): string {
  switch (status) {
    case "passed":
      return "border-success/25";
    case "failed":
      return "border-destructive/35";
    case "warning":
      return "border-warning/35";
    case "not_tested":
      return "border-slate-300";
    default:
      return "border-border";
  }
}

export interface ValidationPanelProps {
  validation: ValidationStatuses | null;
  overall: OverallStatus | null;
  report: ValidationReport | null;
  warnings: string[];
  templateId: string | null;
  activeVersion: number | null;
}

export function ValidationPanel({
  validation,
  overall,
  report,
  warnings,
  templateId,
  activeVersion,
}: ValidationPanelProps) {
  const counts = useMemo(() => countFindings(report), [report]);
  const findings = useMemo(
    () =>
      report
        ? report.checks.flatMap((check) =>
            check.findings.map((finding) => ({
              ...finding,
              checkId: check.id,
              checkName: check.name,
            })),
          )
        : [],
    [report],
  );

  const tabCount = report ? report.checks.length : 0;

  return (
    <Panel
      id={PANEL_IDS.validation}
      step={5}
      title="Validation"
      description="Structural, semantic, logical, visual and compatibility checks are reported independently. Not tested is a first-class result, never a pass."
      actions={
        <>
          {templateId && activeVersion !== null ? (
            <Badge variant="outline" className="font-mono">
              v{activeVersion}
            </Badge>
          ) : null}
          {overall ? <OverallStatusBadge overall={overall} /> : null}
        </>
      }
    >
      {!validation ? (
        <EmptyState
          icon={FileText}
          title="No validation results yet"
          description="Plan a template or load a version to see the five validation levels, individual checks and findings."
        />
      ) : (
        <div className="space-y-4">
          <dl className="grid gap-2 sm:grid-cols-2 xl:grid-cols-5">
            {VALIDATION_LEVELS.map((level) => {
              const status = validation[level.key];
              const checks = report
                ? report.checks.filter((check) => check.level === level.level)
                : [];
              return (
                <div
                  key={level.key}
                  className={cn("rounded-lg border bg-card p-3", levelTone(status))}
                  title={
                    status === "not_tested"
                      ? "Not tested: this level did not run. Not tested is not a pass."
                      : undefined
                  }
                >
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                      {level.code}
                    </p>
                    <ValidationStatusBadge status={status} />
                  </div>
                  <dt className="mt-1.5 text-xs font-semibold text-foreground">{level.label}</dt>
                  <dd className="mt-0.5 text-[11px] leading-4 text-muted-foreground">
                    {level.description}
                  </dd>
                  {report ? (
                    <p className="mt-2 text-[10px] text-muted-foreground">
                      {formatNumber(checks.length)} {pluralize(checks.length, "check")}
                      {checks.some((check) => check.status === "not_tested")
                        ? " · includes not tested"
                        : ""}
                    </p>
                  ) : null}
                </div>
              );
            })}
          </dl>

          <div className="rounded-md border border-dashed border-slate-300 bg-slate-50 px-3 py-2 text-[11px] leading-5 text-slate-600">
            <span className="inline-flex items-center gap-1.5 font-medium text-slate-700">
              <ShieldAlert aria-hidden="true" className="h-3.5 w-3.5" />
              Docentric AX compatibility is not verified.
            </span>{" "}
            V5 is not executed in this environment, so its result is reported as{" "}
            <span className="font-semibold">not tested</span> and is never styled as passed. Output
            is a generic DOCX.
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={counts.errors > 0 ? "destructive" : "outline"}>
              {formatNumber(counts.errors)} {pluralize(counts.errors, "error")}
            </Badge>
            <Badge variant={counts.warnings > 0 ? "warning" : "outline"}>
              {formatNumber(counts.warnings)} {pluralize(counts.warnings, "warning")}
            </Badge>
            <Badge variant="outline">
              {formatNumber(counts.checks)} {pluralize(counts.checks, "check")}
            </Badge>
            {validation.docentric_compatibility === "not_tested" ? (
              <Badge variant="unverified">
                {statusLabel(validation.docentric_compatibility)}: Docentric AX compatibility
              </Badge>
            ) : null}
          </div>

          {report ? (
            <Tabs defaultValue="checks">
              <TabsList>
                <TabsTrigger value="checks">Checks ({tabCount})</TabsTrigger>
                <TabsTrigger value="findings">Findings ({findings.length})</TabsTrigger>
              </TabsList>
              <TabsContent value="checks">
                <ScrollArea
                  role="region"
                  aria-label="Validation checks"
                  tabIndex={0}
                  className="max-h-[460px] rounded-lg border"
                >
                  <ul>
                    {report.checks.map((check) => (
                      <li key={check.id} className="border-b border-border p-3 last:border-b-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <code className="font-mono text-[10px] text-muted-foreground">
                            {check.id}
                          </code>
                          <span className="text-xs font-medium text-foreground">{check.name}</span>
                          <span className="ml-auto">
                            <ValidationStatusBadge status={check.status} />
                          </span>
                        </div>
                        {check.summary ? (
                          <p className="mt-1 text-[11px] leading-5 text-muted-foreground">
                            {check.summary}
                          </p>
                        ) : null}
                        {check.findings.length > 0 ? (
                          <ul className="mt-2 space-y-1.5">
                            {check.findings.map((finding, index) => (
                              <li
                                key={`${finding.code}-${index}`}
                                className="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-[11px]"
                              >
                                <FindingSeverityBadge severity={finding.severity} />
                                <code className="font-mono text-[10px] text-muted-foreground">
                                  {finding.code}
                                </code>
                                <span className="text-foreground">{finding.message}</span>
                                {finding.location ? (
                                  <code className="break-all font-mono text-[10px] text-muted-foreground">
                                    {finding.location}
                                  </code>
                                ) : null}
                              </li>
                            ))}
                          </ul>
                        ) : null}
                      </li>
                    ))}
                    {report.checks.length === 0 ? (
                      <li className="px-3 py-4 text-xs text-muted-foreground">
                        The validation report contains no checks.
                      </li>
                    ) : null}
                  </ul>
                </ScrollArea>
              </TabsContent>
              <TabsContent value="findings">
                {findings.length === 0 ? (
                  <EmptyState
                    icon={CheckCircle2}
                    title="No findings reported"
                    description="No errors, warnings or informational findings were attached to the validation checks."
                    compact
                  />
                ) : (
                  <ScrollArea
                    role="region"
                    aria-label="Validation findings"
                    tabIndex={0}
                    className="max-h-[460px] rounded-lg border"
                  >
                    <ul>
                      {findings.map((finding, index) => (
                        <li
                          key={`${finding.checkId}-${finding.code}-${index}`}
                          className="border-b border-border p-3 last:border-b-0"
                        >
                          <div className="flex flex-wrap items-center gap-2">
                            <FindingSeverityBadge severity={finding.severity} />
                            <code className="font-mono text-[10px] text-muted-foreground">
                              {finding.code}
                            </code>
                            <span className="text-[10px] text-muted-foreground">
                              {finding.checkId} · {finding.checkName}
                            </span>
                          </div>
                          <p className="mt-1 text-xs leading-5 text-foreground">
                            {finding.message}
                          </p>
                          {finding.location ? (
                            <p className="mt-0.5 break-all font-mono text-[10px] text-muted-foreground">
                              {finding.location}
                            </p>
                          ) : null}
                        </li>
                      ))}
                    </ul>
                  </ScrollArea>
                )}
              </TabsContent>
            </Tabs>
          ) : (
            <Alert variant="info">
              <AlertTriangle aria-hidden="true" />
              <div>
                <AlertTitle>Detailed report unavailable</AlertTitle>
                <AlertDescription>
                  Per-level statuses were returned, but the response did not include the full
                  validation report. Re-run planning or compile to obtain check-level detail.
                </AlertDescription>
              </div>
            </Alert>
          )}

          {warnings.length > 0 ? (
            <Alert variant="warning">
              <AlertTriangle aria-hidden="true" />
              <div>
                <AlertTitle>
                  {warnings.length} planner {pluralize(warnings.length, "warning")}
                </AlertTitle>
                <AlertDescription>
                  <ul className="list-disc space-y-1 pl-4">
                    {warnings.map((warning, index) => (
                      <li key={`${warning}-${index}`} className="text-[11px] leading-5">
                        {warning}
                      </li>
                    ))}
                  </ul>
                </AlertDescription>
              </div>
            </Alert>
          ) : null}
        </div>
      )}
    </Panel>
  );
}
