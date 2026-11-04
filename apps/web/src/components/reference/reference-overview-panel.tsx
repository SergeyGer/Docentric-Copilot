"use client";

import {
  AlertTriangle,
  Archive,
  Boxes,
  Copy as CopyIcon,
  FileStack,
  Info,
  ScanSearch,
} from "lucide-react";

import {
  ClassificationBadge,
  ReferenceCoverageBar,
  ResolutionBadge,
  SeverityBadge,
} from "@/components/reference/reference-badges";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { CopyButton } from "@/components/workspace/copy-button";
import {
  ELEMENT_KIND_LABELS,
  LINK_STATUS_LABELS,
  PATH_STATUS_LABELS,
  PLATFORM_LABELS,
  RESOLUTION_LABELS,
  SCHEMA_SOURCE_LABELS,
  SOURCE_TYPE_LABELS,
  STORY_LABELS,
  formatRatio,
  referenceEnumLabel,
  sortCountEntries,
} from "@/lib/reference";
import { formatBytes, formatNumber, truncateMiddle } from "@/lib/format";
import type { ReferenceDocumentEvidence, ReferenceReport } from "@/lib/types";
import { cn } from "@/lib/utils";

const MAX_DIAGNOSTICS_SHOWN = 50;
const MAX_DUPLICATE_GROUPS_SHOWN = 25;

function Stat({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="rounded-lg border border-border bg-muted/15 p-3">
      <dt className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </dt>
      <dd className="mt-1 text-xl font-semibold leading-7 tabular-nums text-foreground">
        {value}
      </dd>
      {hint ? <p className="mt-0.5 text-[11px] leading-4 text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

function CountChips({
  counts,
  labels,
  emptyLabel = "None",
}: {
  counts: Record<string, number>;
  labels: Record<string, string>;
  emptyLabel?: string;
}) {
  const entries = sortCountEntries(counts).filter(([, count]) => count > 0);
  if (entries.length === 0) {
    return <p className="text-[11px] text-muted-foreground">{emptyLabel}</p>;
  }
  return (
    <ul className="flex flex-wrap gap-1.5">
      {entries.map(([key, count]) => (
        <li key={key}>
          <Badge variant="outline">
            {referenceEnumLabel(labels, key)} · {formatNumber(count)}
          </Badge>
        </li>
      ))}
    </ul>
  );
}

function DocumentRow({ document }: { document: ReferenceDocumentEvidence }) {
  const flags: Array<[boolean, string]> = [
    [document.has_macros, "Macros"],
    [document.has_active_x, "ActiveX"],
    [document.has_embedded_objects, "Embedded objects"],
    [document.has_external_relationships, "External relationships"],
  ];
  const activeFlags = flags.filter(([active]) => active).map(([, label]) => label);
  return (
    <li className="rounded-lg border border-border bg-card p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-foreground" title={document.filename}>
            {document.filename}
          </p>
          <p className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
            <span>{formatBytes(document.size_bytes)}</span>
            <span aria-hidden="true">·</span>
            <span>{referenceEnumLabel(PLATFORM_LABELS, document.platform)}</span>
            {document.product_version ? (
              <>
                <span aria-hidden="true">·</span>
                <span>Product {document.product_version}</span>
              </>
            ) : null}
            <span aria-hidden="true">·</span>
            <span>{formatNumber(document.control_count)} controls</span>
          </p>
        </div>
        <Badge variant="outline" className="gap-1">
          <CopyIcon aria-hidden="true" className="h-3 w-3" />
          {truncateMiddle(document.sha256, 10, 6)}
        </Badge>
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        <ClassificationBadge classification="recognized" />
        <Badge variant="muted">
          {formatNumber(document.classification_counts.recognized ?? 0)} recognized
        </Badge>
        <ClassificationBadge classification="ambiguous" />
        <Badge variant="muted">
          {formatNumber(document.classification_counts.ambiguous ?? 0)} ambiguous
        </Badge>
        <ClassificationBadge classification="unknown" />
        <Badge variant="muted">
          {formatNumber(document.classification_counts.unknown ?? 0)} unknown
        </Badge>
      </div>

      <div className="mt-2 grid gap-2 sm:grid-cols-2">
        <ReferenceCoverageBar ratio={document.coverage_ratio} label="Control coverage" />
        <ReferenceCoverageBar ratio={document.join_coverage_ratio} label="Joined by SDT id" />
      </div>

      <dl className="mt-2 grid gap-x-4 gap-y-1 text-[11px] sm:grid-cols-2">
        <div className="min-w-0">
          <dt className="text-muted-foreground">Schema</dt>
          <dd className="break-words text-foreground">
            {referenceEnumLabel(SCHEMA_SOURCE_LABELS, document.schema_source)}
            {document.schema_sections.length > 0
              ? ` · ${document.schema_sections.join(", ")}`
              : ""}
            {document.schema_paths > 0 ? ` · ${formatNumber(document.schema_paths)} paths` : ""}
          </dd>
        </div>
        <div className="min-w-0">
          <dt className="text-muted-foreground">Metadata</dt>
          <dd className="break-words text-foreground">
            {formatNumber(document.metadata_elements.length)} elements ·{" "}
            {formatNumber(document.project_data.length)} ProjectData parts
          </dd>
        </div>
        <div className="min-w-0 sm:col-span-2">
          <dt className="text-muted-foreground">Paths</dt>
          <dd className="space-y-0.5">
            {document.paths.slice(0, 4).map((path) => (
              <p key={path} className="break-all font-mono text-foreground">
                {path}
              </p>
            ))}
            {document.paths.length > 4 ? (
              <p className="text-muted-foreground">+{document.paths.length - 4} more</p>
            ) : null}
          </dd>
        </div>
      </dl>

      {document.project_data.length > 0 ? (
        <ul className="mt-2 flex flex-wrap gap-1.5">
          {document.project_data.map((part) => (
            <li key={part.part}>
              <Badge variant="secondary" title={part.part}>
                {part.part.split("/").pop() ?? part.part} · {formatNumber(part.element_count)}{" "}
                elements
              </Badge>
            </li>
          ))}
        </ul>
      ) : null}

      {activeFlags.length > 0 ? (
        <ul className="mt-2 flex flex-wrap gap-1.5">
          {activeFlags.map((flag) => (
            <li key={flag}>
              <Badge variant="warning">
                <AlertTriangle aria-hidden="true" className="h-3 w-3" />
                {flag}
              </Badge>
            </li>
          ))}
        </ul>
      ) : null}

      {document.warnings.length > 0 ? (
        <ul className="mt-2 space-y-1 rounded-md border border-warning/30 bg-warning/5 p-2">
          {document.warnings.slice(0, 5).map((warning) => (
            <li key={warning} className="break-words text-[11px] leading-4 text-foreground">
              {warning}
            </li>
          ))}
          {document.warnings.length > 5 ? (
            <li className="text-[11px] text-muted-foreground">
              +{document.warnings.length - 5} more document warnings
            </li>
          ) : null}
        </ul>
      ) : null}
    </li>
  );
}

export function ReferenceOverviewPanel({ report }: { report: ReferenceReport }) {
  const { counts } = report;
  const diagnosticsShown = report.diagnostics.slice(0, MAX_DIAGNOSTICS_SHOWN);
  const duplicateGroupsShown = report.duplicates.slice(0, MAX_DUPLICATE_GROUPS_SHOWN);
  const warnings = Array.from(new Set([...report.warnings, ...report.inventory.warnings]));

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="gap-3 pb-3">
          <div className="flex flex-col justify-between gap-2 sm:flex-row sm:items-start">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-1.5">
                <CardTitle className="text-base">Overview</CardTitle>
                <Badge variant="secondary">
                  {referenceEnumLabel(SOURCE_TYPE_LABELS, report.source_type)}
                </Badge>
                <Badge variant="outline">
                  {referenceEnumLabel(PLATFORM_LABELS, report.container.platform)}
                </Badge>
                <Badge variant="unverified">Runtime not tested</Badge>
              </div>
              <CardDescription className="mt-1 text-[13px]">
                Static evidence for <span className="font-medium text-foreground">{report.source_name}</span>.
                Counts include every content control; unknown and ambiguous controls are never
                dropped from the report.
              </CardDescription>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <dl className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
            <Stat
              label="Artifacts"
              value={formatNumber(counts.artifacts)}
              hint={`${formatNumber(counts.distinct_artifacts)} distinct · ${formatNumber(counts.docx_artifacts)} DOCX artifacts`}
            />
            <Stat
              label="Duplicates"
              value={formatNumber(counts.duplicate_groups)}
              hint={`${formatNumber(counts.duplicate_occurrences)} repeated occurrences`}
            />
            <Stat
              label="Controls"
              value={formatNumber(counts.controls_total)}
              hint={`${formatNumber(counts.distinct_docx)} distinct DOCX · ${formatNumber(counts.joined_by_id)} joined by SDT id`}
            />
            <Stat
              label="Coverage"
              value={formatRatio(counts.coverage_ratio)}
              hint={`${formatNumber(counts.resolved)} of ${formatNumber(counts.controls_total)} controls resolved`}
            />
          </dl>

          <div className="rounded-lg border border-border bg-muted/15 p-3">
            <dl className="grid gap-x-4 gap-y-2 text-[11px] sm:grid-cols-2 xl:grid-cols-4">
              <div className="min-w-0">
                <dt className="text-muted-foreground">Source SHA-256</dt>
                <dd className="flex min-w-0 items-center gap-1">
                  <code className="break-all font-mono text-foreground">
                    {truncateMiddle(report.source_sha256, 16, 8)}
                  </code>
                  <CopyButton value={report.source_sha256} label="Copy source SHA-256" />
                </dd>
              </div>
              <div className="min-w-0">
                <dt className="text-muted-foreground">Report digest</dt>
                <dd className="flex min-w-0 items-center gap-1">
                  <code className="break-all font-mono text-foreground">
                    {truncateMiddle(report.report_digest, 16, 8)}
                  </code>
                  <CopyButton value={report.report_digest} label="Copy report digest" />
                </dd>
              </div>
              <div className="min-w-0">
                <dt className="text-muted-foreground">Container</dt>
                <dd className="break-words text-foreground">
                  {formatNumber(report.inventory.entries.length)} entries ·{" "}
                  {formatBytes(report.inventory.source_size_bytes)}
                </dd>
              </div>
              <div className="min-w-0">
                <dt className="text-muted-foreground">Versions</dt>
                <dd className="break-words text-foreground">
                  {report.container.product_versions.length > 0
                    ? report.container.product_versions.join(", ")
                    : "No product version hint"}
                </dd>
              </div>
              <div className="min-w-0">
                <dt className="text-muted-foreground">Inspector</dt>
                <dd className="break-words font-mono text-foreground">{report.inspector}</dd>
              </div>
              <div className="min-w-0">
                <dt className="text-muted-foreground">Reference contract</dt>
                <dd className="font-mono text-foreground">v{report.reference_version}</dd>
              </div>
              <div className="min-w-0">
                <dt className="text-muted-foreground">Nested archives</dt>
                <dd className="text-foreground">{formatNumber(counts.nested_archives)}</dd>
              </div>
              <div className="min-w-0">
                <dt className="text-muted-foreground">Documents</dt>
                <dd className="text-foreground">
                  {formatNumber(report.documents.length)} distinct ·{" "}
                  {formatNumber(counts.distinct_docx)} unique DOCX payloads
                </dd>
              </div>
            </dl>
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Classification</CardTitle>
            <CardDescription>
              Controls without a recognizable Docentric marker are preserved as unknown.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex flex-wrap gap-2">
              <span className="inline-flex items-center gap-1.5">
                <ClassificationBadge classification="recognized" />
                <span className="text-sm font-semibold tabular-nums">
                  {formatNumber(counts.classification_recognized)}
                </span>
              </span>
              <span className="inline-flex items-center gap-1.5">
                <ClassificationBadge classification="ambiguous" />
                <span className="text-sm font-semibold tabular-nums">
                  {formatNumber(counts.classification_ambiguous)}
                </span>
              </span>
              <span className="inline-flex items-center gap-1.5">
                <ClassificationBadge classification="unknown" />
                <span className="text-sm font-semibold tabular-nums">
                  {formatNumber(counts.classification_unknown)}
                </span>
              </span>
            </div>
            <div>
              <p className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                By element kind
              </p>
              <CountChips counts={counts.by_element_kind} labels={ELEMENT_KIND_LABELS} />
            </div>
            <div>
              <p className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                By story
              </p>
              <CountChips counts={counts.by_story} labels={STORY_LABELS} />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Resolution</CardTitle>
            <CardDescription>
              Resolution combines the SDT-to-ProjectData join with optional DDSP path checking.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <ul className="grid gap-2 sm:grid-cols-2">
              {(
                [
                  ["resolved", counts.resolved],
                  ["missing_part", counts.missing_part],
                  ["unknown_path", counts.unknown_path],
                  ["ambiguous", counts.ambiguous],
                ] as const
              ).map(([status, count]) => (
                <li
                  key={status}
                  className="flex items-center justify-between gap-2 rounded-md border border-border bg-muted/15 px-2.5 py-2"
                >
                  <ResolutionBadge status={status} />
                  <span className="text-sm font-semibold tabular-nums">{formatNumber(count)}</span>
                </li>
              ))}
            </ul>
            <ReferenceCoverageBar ratio={counts.coverage_ratio} label="Resolved control coverage" />
            <ReferenceCoverageBar ratio={counts.join_coverage_ratio} label="Joined by SDT id" />
            <div className="grid gap-2 sm:grid-cols-2">
              <div>
                <p className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                  Link status
                </p>
                <CountChips counts={counts.by_link_status} labels={LINK_STATUS_LABELS} />
              </div>
              <div>
                <p className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                  Path status
                </p>
                <CountChips counts={counts.by_path_status} labels={PATH_STATUS_LABELS} />
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Documents</CardTitle>
          <CardDescription>
            One entry per distinct DOCX payload, including every path that supplied it.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {report.documents.length === 0 ? (
            <p className="rounded-md border border-dashed border-border bg-muted/20 px-3 py-4 text-xs text-muted-foreground">
              The inspected source contains no DOCX document. No controls can be reported.
            </p>
          ) : (
            <ul className="space-y-2">
              {report.documents.map((document) => (
                <DocumentRow key={document.sha256} document={document} />
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-base">
              <Archive aria-hidden="true" className="h-4 w-4 text-muted-foreground" />
              Duplicates
            </CardTitle>
            <CardDescription>
              Byte-identical artifacts are counted once but keep every path.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {report.duplicates.length === 0 ? (
              <p className="text-xs text-muted-foreground">No byte-identical artifacts were found.</p>
            ) : (
              <div className="overflow-hidden rounded-md border border-border">
                <Table>
                  <TableCaption className="sr-only">Duplicate artifact groups</TableCaption>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Kind</TableHead>
                      <TableHead>Count</TableHead>
                      <TableHead>SHA-256</TableHead>
                      <TableHead>Paths</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {duplicateGroupsShown.map((group) => (
                      <TableRow key={group.sha256}>
                        <TableCell className="py-2 text-xs">
                          <Badge variant="outline">{group.kind}</Badge>
                        </TableCell>
                        <TableCell className="py-2 text-xs tabular-nums">
                          {formatNumber(group.occurrences)}
                        </TableCell>
                        <TableCell className="py-2 text-xs">
                          <code className="break-all font-mono">
                            {truncateMiddle(group.sha256, 10, 6)}
                          </code>
                        </TableCell>
                        <TableCell className="py-2 text-xs">
                          <ul className="space-y-0.5">
                            {group.paths.slice(0, 3).map((path) => (
                              <li key={path} className="break-all font-mono">
                                {path}
                              </li>
                            ))}
                            {group.paths.length > 3 ? (
                              <li className="text-muted-foreground">
                                +{group.paths.length - 3} more
                              </li>
                            ) : null}
                          </ul>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
            {report.duplicates.length > MAX_DUPLICATE_GROUPS_SHOWN ? (
              <p className="mt-2 text-[11px] text-muted-foreground">
                Showing {MAX_DUPLICATE_GROUPS_SHOWN} of {report.duplicates.length} duplicate groups.
              </p>
            ) : null}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-base">
              <Boxes aria-hidden="true" className="h-4 w-4 text-muted-foreground" />
              Nested archives & warnings
            </CardTitle>
            <CardDescription>
              Nested containers are enumerated but not expanded beyond the requested depth.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {report.nested_archives.length > 0 ? (
              <ul className="space-y-1">
                {report.nested_archives.slice(0, 20).map((archive) => (
                  <li key={archive} className="break-all font-mono text-[11px] text-foreground">
                    {archive}
                  </li>
                ))}
                {report.nested_archives.length > 20 ? (
                  <li className="text-[11px] text-muted-foreground">
                    +{report.nested_archives.length - 20} more nested archives
                  </li>
                ) : null}
              </ul>
            ) : (
              <p className="text-xs text-muted-foreground">No nested archives were recorded.</p>
            )}
            {warnings.length > 0 ? (
              <ul className="space-y-1 rounded-md border border-warning/30 bg-warning/5 p-2">
                {warnings.slice(0, 10).map((warning) => (
                  <li key={warning} className="break-words text-[11px] leading-4 text-foreground">
                    {warning}
                  </li>
                ))}
                {warnings.length > 10 ? (
                  <li className="text-[11px] text-muted-foreground">
                    +{warnings.length - 10} more warnings
                  </li>
                ) : null}
              </ul>
            ) : null}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <ScanSearch aria-hidden="true" className="h-4 w-4 text-muted-foreground" />
            Diagnostics
          </CardTitle>
          <CardDescription>
            {formatNumber(report.diagnostics.length)} findings recorded by the read-only inspector.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {report.diagnostics.length === 0 ? (
            <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Info aria-hidden="true" className="h-3.5 w-3.5" />
              No diagnostics were recorded for this source.
            </p>
          ) : (
            <ul className="space-y-2">
              {diagnosticsShown.map((diagnostic, index) => (
                <li
                  key={`${diagnostic.code}-${diagnostic.document_sha256 ?? ""}-${diagnostic.part ?? ""}-${diagnostic.ordinal ?? -1}-${index}`}
                  className={cn(
                    "rounded-md border border-border bg-card p-2.5",
                    diagnostic.severity === "warning" && "border-warning/30 bg-warning/5",
                    diagnostic.severity === "error" && "border-destructive/30 bg-destructive/5",
                  )}
                >
                  <div className="flex flex-wrap items-center gap-1.5">
                    <SeverityBadge severity={diagnostic.severity} />
                    <code className="break-all font-mono text-[11px] text-muted-foreground">
                      {diagnostic.code}
                    </code>
                    {diagnostic.part ? (
                      <span className="break-all text-[11px] text-muted-foreground">
                        {diagnostic.part}
                        {diagnostic.ordinal !== null ? ` · ¶${diagnostic.ordinal}` : ""}
                      </span>
                    ) : null}
                  </div>
                  <p className="mt-1 break-words text-xs leading-5 text-foreground">
                    {diagnostic.message}
                  </p>
                </li>
              ))}
            </ul>
          )}
          {report.diagnostics.length > MAX_DIAGNOSTICS_SHOWN ? (
            <p className="mt-2 text-[11px] text-muted-foreground">
              Showing {MAX_DIAGNOSTICS_SHOWN} of {report.diagnostics.length} diagnostics.
            </p>
          ) : null}
        </CardContent>
      </Card>

      <div className="flex flex-wrap items-center gap-1.5 rounded-lg border border-border bg-muted/15 px-3 py-2 text-[11px] text-muted-foreground">
        <FileStack aria-hidden="true" className="h-3.5 w-3.5" />
        <span>
          Classification: recognized {formatNumber(counts.classification_recognized)} · ambiguous{" "}
          {formatNumber(counts.classification_ambiguous)} · unknown{" "}
          {formatNumber(counts.classification_unknown)}. Resolution:{" "}
          {referenceEnumLabel(RESOLUTION_LABELS, "resolved")} {formatNumber(counts.resolved)} ·{" "}
          {referenceEnumLabel(RESOLUTION_LABELS, "missing_part")}{" "}
          {formatNumber(counts.missing_part)} ·{" "}
          {referenceEnumLabel(RESOLUTION_LABELS, "unknown_path")}{" "}
          {formatNumber(counts.unknown_path)} ·{" "}
          {referenceEnumLabel(RESOLUTION_LABELS, "ambiguous")} {formatNumber(counts.ambiguous)}.
          Runtime compatibility: not tested.
        </span>
      </div>
    </div>
  );
}
