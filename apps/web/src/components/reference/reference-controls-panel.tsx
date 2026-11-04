"use client";

import { useCallback, useDeferredValue, useEffect, useMemo, useState } from "react";
import { FilterX, Search } from "lucide-react";

import {
  ClassificationBadge,
  ElementKindBadge,
  ResolutionBadge,
} from "@/components/reference/reference-badges";
import { ReferenceControlDrawer } from "@/components/reference/reference-control-drawer";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { EmptyState } from "@/components/workspace/empty-state";
import { formatNumber } from "@/lib/format";
import {
  ELEMENT_KIND_LABELS,
  LINK_STATUS_LABELS,
  REFERENCE_CONTROLS_PAGE_SIZE,
  REFERENCE_CONTROLS_PAGINATION_THRESHOLD,
  STORY_LABELS,
  controlMatchesQuery,
  flattenReferenceControls,
  formatRatio,
  referenceControlBinding,
  referenceControlLabel,
  referenceControlSecondary,
  referenceEnumLabel,
} from "@/lib/reference";
import type { ReferenceControlRow } from "@/lib/reference";
import type { ReferenceReport } from "@/lib/types";

export interface ReferenceControlsPanelProps {
  report: ReferenceReport;
}

/**
 * Searchable, filterable control inventory. Filters start at "all", so unknown
 * and ambiguous controls are always present until a reviewer deliberately
 * narrows the classification.
 */
export function ReferenceControlsPanel({ report }: ReferenceControlsPanelProps) {
  const rows = useMemo(() => flattenReferenceControls(report), [report]);
  const [query, setQuery] = useState("");
  const deferredQuery = useDeferredValue(query);
  const [kind, setKind] = useState("all");
  const [part, setPart] = useState("all");
  const [classification, setClassification] = useState("all");
  const [resolution, setResolution] = useState("all");
  const [documentSha, setDocumentSha] = useState("all");
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<ReferenceControlRow | null>(null);

  const kinds = useMemo(
    () => Array.from(new Set(rows.map((row) => row.control.element_kind))).sort(),
    [rows],
  );
  const parts = useMemo(
    () => Array.from(new Set(rows.map((row) => row.control.part))).sort(),
    [rows],
  );

  const filtered = useMemo(
    () =>
      rows.filter((row) => {
        if (kind !== "all" && row.control.element_kind !== kind) {
          return false;
        }
        if (part !== "all" && row.control.part !== part) {
          return false;
        }
        if (classification !== "all" && row.control.classification !== classification) {
          return false;
        }
        if (resolution !== "all" && row.control.resolution.status !== resolution) {
          return false;
        }
        if (documentSha !== "all" && row.document.sha256 !== documentSha) {
          return false;
        }
        return controlMatchesQuery(row, deferredQuery);
      }),
    [rows, kind, part, classification, resolution, documentSha, deferredQuery],
  );

  const paginate = filtered.length > REFERENCE_CONTROLS_PAGINATION_THRESHOLD;
  const totalPages = Math.max(1, Math.ceil(filtered.length / REFERENCE_CONTROLS_PAGE_SIZE));
  const safePage = Math.min(page, totalPages);
  const pageStart = paginate ? (safePage - 1) * REFERENCE_CONTROLS_PAGE_SIZE : 0;
  const visible = paginate
    ? filtered.slice(pageStart, pageStart + REFERENCE_CONTROLS_PAGE_SIZE)
    : filtered;

  useEffect(() => {
    setPage(1);
  }, [deferredQuery, kind, part, classification, resolution, documentSha]);

  useEffect(() => {
    if (page > totalPages) {
      setPage(totalPages);
    }
  }, [page, totalPages]);

  const closeDrawer = useCallback(() => setSelected(null), []);
  const hasActiveFilters =
    query.length > 0 ||
    kind !== "all" ||
    part !== "all" ||
    classification !== "all" ||
    resolution !== "all" ||
    documentSha !== "all";

  const resetFilters = () => {
    setQuery("");
    setKind("all");
    setPart("all");
    setClassification("all");
    setResolution("all");
    setDocumentSha("all");
  };

  const showDocumentColumn = report.documents.length > 1;

  return (
    <>
      <Card>
        <CardHeader className="gap-3 pb-3">
          <div className="flex flex-col justify-between gap-2 sm:flex-row sm:items-start">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-1.5">
                <CardTitle className="text-base">Controls</CardTitle>
                <Badge variant="secondary">{formatNumber(rows.length)} total</Badge>
                <Badge variant="unverified">Runtime not tested</Badge>
              </div>
              <CardDescription className="mt-1 text-[13px]">
                Every content control found in the inspected DOCX stories. Select a control to see
                its raw <code className="font-mono text-[11px]">w:dataBinding</code> and exact source
                location.
              </CardDescription>
            </div>
            <div className="flex flex-wrap gap-1.5">
              <span className="inline-flex items-center gap-1">
                <ClassificationBadge classification="recognized" />
                <span className="text-xs font-semibold tabular-nums">
                  {formatNumber(report.counts.classification_recognized)}
                </span>
              </span>
              <span className="inline-flex items-center gap-1">
                <ClassificationBadge classification="ambiguous" />
                <span className="text-xs font-semibold tabular-nums">
                  {formatNumber(report.counts.classification_ambiguous)}
                </span>
              </span>
              <span className="inline-flex items-center gap-1">
                <ClassificationBadge classification="unknown" />
                <span className="text-xs font-semibold tabular-nums">
                  {formatNumber(report.counts.classification_unknown)}
                </span>
              </span>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
            <div className="sm:col-span-2 lg:col-span-1 xl:col-span-2">
              <label
                htmlFor="reference-control-search"
                className="mb-1 block text-[11px] font-medium text-muted-foreground"
              >
                Search controls
              </label>
              <div className="relative">
                <Search
                  aria-hidden="true"
                  className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground"
                />
                <Input
                  id="reference-control-search"
                  type="search"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="tag, alias, binding, part, diagnostic code…"
                  className="h-8 pl-8 text-xs"
                />
              </div>
            </div>

            <div>
              <label
                htmlFor="reference-control-kind"
                className="mb-1 block text-[11px] font-medium text-muted-foreground"
              >
                Element kind
              </label>
              <Select
                id="reference-control-kind"
                value={kind}
                onChange={(event) => setKind(event.target.value)}
                className="h-8 text-xs"
              >
                <option value="all">All kinds</option>
                {kinds.map((value) => (
                  <option key={value} value={value}>
                    {referenceEnumLabel(ELEMENT_KIND_LABELS, value)}
                  </option>
                ))}
              </Select>
            </div>

            <div>
              <label
                htmlFor="reference-control-part"
                className="mb-1 block text-[11px] font-medium text-muted-foreground"
              >
                Part
              </label>
              <Select
                id="reference-control-part"
                value={part}
                onChange={(event) => setPart(event.target.value)}
                className="h-8 text-xs"
              >
                <option value="all">All parts</option>
                {parts.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </Select>
            </div>

            <div>
              <label
                htmlFor="reference-control-classification"
                className="mb-1 block text-[11px] font-medium text-muted-foreground"
              >
                Classification
              </label>
              <Select
                id="reference-control-classification"
                value={classification}
                onChange={(event) => setClassification(event.target.value)}
                className="h-8 text-xs"
              >
                <option value="all">All classifications</option>
                <option value="recognized">Recognized</option>
                <option value="ambiguous">Ambiguous</option>
                <option value="unknown">Unknown</option>
              </Select>
            </div>

            <div>
              <label
                htmlFor="reference-control-resolution"
                className="mb-1 block text-[11px] font-medium text-muted-foreground"
              >
                Resolution
              </label>
              <Select
                id="reference-control-resolution"
                value={resolution}
                onChange={(event) => setResolution(event.target.value)}
                className="h-8 text-xs"
              >
                <option value="all">All resolutions</option>
                <option value="resolved">Resolved</option>
                <option value="missing_part">Missing part</option>
                <option value="unknown_path">Unknown path</option>
                <option value="ambiguous">Ambiguous</option>
              </Select>
            </div>

            {showDocumentColumn ? (
              <div>
                <label
                  htmlFor="reference-control-document"
                  className="mb-1 block text-[11px] font-medium text-muted-foreground"
                >
                  Document
                </label>
                <Select
                  id="reference-control-document"
                  value={documentSha}
                  onChange={(event) => setDocumentSha(event.target.value)}
                  className="h-8 text-xs"
                >
                  <option value="all">All documents</option>
                  {report.documents.map((document) => (
                    <option key={document.sha256} value={document.sha256}>
                      {document.filename}
                    </option>
                  ))}
                </Select>
              </div>
            ) : null}
          </div>

          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-[11px] leading-5 text-muted-foreground" role="status" aria-live="polite">
              Showing {formatNumber(visible.length)} of {formatNumber(filtered.length)} filtered
              controls
              {filtered.length !== rows.length
                ? ` (from ${formatNumber(rows.length)} total)`
                : ""}
              . Unknown and ambiguous rows are included unless you explicitly filter
              classification.
            </p>
            <div className="flex items-center gap-2">
              {paginate ? (
                <span className="text-[11px] text-muted-foreground">
                  Large report: paginated at {REFERENCE_CONTROLS_PAGE_SIZE} rows.
                </span>
              ) : null}
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={resetFilters}
                disabled={!hasActiveFilters}
              >
                <FilterX aria-hidden="true" />
                Reset filters
              </Button>
            </div>
          </div>

          {rows.length === 0 ? (
            <EmptyState
              icon={Search}
              title="No content controls found"
              description="The inspected source contains no w:sdt content controls in the supported Word story parts. Upload another reference or inspect the package contents."
            />
          ) : filtered.length === 0 ? (
            <div className="rounded-lg border border-dashed border-border bg-muted/20 px-4 py-6 text-center">
              <p className="text-sm font-medium text-foreground">No controls match these filters.</p>
              <p className="mt-1 text-xs text-muted-foreground">
                Reset the filters to return to the full control list; unknown and ambiguous rows
                are not hidden by default.
              </p>
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={resetFilters}
                className="mt-2"
              >
                <FilterX aria-hidden="true" />
                Reset filters
              </Button>
            </div>
          ) : (
            <div className="overflow-hidden rounded-lg border border-border">
              <Table>
                <TableCaption className="sr-only">
                  Reference content controls. Select a control to open its complete evidence.
                </TableCaption>
                <TableHeader>
                  <TableRow>
                    <TableHead scope="col">Control</TableHead>
                    {showDocumentColumn ? <TableHead scope="col">Document</TableHead> : null}
                    <TableHead scope="col">Kind</TableHead>
                    <TableHead scope="col">Part / story</TableHead>
                    <TableHead scope="col">Paragraph</TableHead>
                    <TableHead scope="col">Binding</TableHead>
                    <TableHead scope="col">Resolution</TableHead>
                    <TableHead scope="col">Classification</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {visible.map((row) => {
                    const { control, document } = row;
                    const label = referenceControlLabel(control);
                    const secondary = referenceControlSecondary(control);
                    const binding = referenceControlBinding(control);
                    return (
                      <TableRow key={row.key}>
                        <TableCell className="max-w-[220px] py-2">
                          <button
                            type="button"
                            onClick={() => setSelected(row)}
                            className="block max-w-full rounded text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1"
                            aria-label={`Open details for ${label}, control ${control.ordinal} in ${control.part}`}
                            title="Open control details"
                          >
                            <span className="block truncate text-xs font-medium text-foreground">
                              {label}
                            </span>
                            {secondary ? (
                              <span className="block truncate text-[10px] text-muted-foreground">
                                {secondary}
                              </span>
                            ) : null}
                            <span className="block truncate font-mono text-[10px] text-muted-foreground">
                              sdt {control.sdt_id_unsigned ?? control.sdt_id_signed ?? "—"}
                            </span>
                          </button>
                        </TableCell>
                        {showDocumentColumn ? (
                          <TableCell className="max-w-[140px] py-2">
                            <span
                              className="block truncate text-[11px] text-foreground"
                              title={document.filename}
                            >
                              {document.filename}
                            </span>
                          </TableCell>
                        ) : null}
                        <TableCell className="py-2">
                          <ElementKindBadge kind={control.element_kind} />
                        </TableCell>
                        <TableCell className="max-w-[180px] py-2">
                          <code
                            className="block truncate font-mono text-[11px] text-foreground"
                            title={control.part}
                          >
                            {control.part}
                          </code>
                          <span className="text-[10px] text-muted-foreground">
                            {referenceEnumLabel(STORY_LABELS, control.story)}
                          </span>
                        </TableCell>
                        <TableCell className="py-2 text-xs tabular-nums">
                          {control.paragraph_index >= 0 ? control.paragraph_index : "—"}
                        </TableCell>
                        <TableCell className="max-w-[260px] py-2">
                          {binding ? (
                            <code
                              className="block truncate font-mono text-[11px] text-foreground"
                              title={binding}
                            >
                              {binding}
                            </code>
                          ) : (
                            <span className="text-[11px] text-muted-foreground">—</span>
                          )}
                          {control.data_binding.xpath && binding !== control.data_binding.xpath ? (
                            <span
                              className="mt-0.5 block truncate font-mono text-[10px] text-muted-foreground"
                              title={control.data_binding.xpath}
                            >
                              raw: {control.data_binding.xpath}
                            </span>
                          ) : null}
                        </TableCell>
                        <TableCell className="py-2">
                          <ResolutionBadge status={control.resolution.status} />
                          <span className="mt-0.5 block max-w-[160px] truncate text-[10px] text-muted-foreground">
                            {referenceEnumLabel(
                              LINK_STATUS_LABELS,
                              control.resolution.link_status,
                            )}
                          </span>
                        </TableCell>
                        <TableCell className="max-w-[180px] py-2">
                          <ClassificationBadge classification={control.classification} />
                          <span
                            className="mt-0.5 block truncate text-[10px] text-muted-foreground"
                            title={control.classification_reason}
                          >
                            {control.classification_reason}
                          </span>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          )}

          {paginate ? (
            <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-muted/15 px-3 py-2">
              <p className="text-[11px] text-muted-foreground">
                Showing {formatNumber(pageStart + 1)}–
                {formatNumber(pageStart + visible.length)} of {formatNumber(filtered.length)}
              </p>
              <div className="flex items-center gap-2">
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => setPage((current) => Math.max(1, current - 1))}
                  disabled={safePage <= 1}
                  aria-label="Previous controls page"
                >
                  Previous
                </Button>
                <span className="text-[11px] text-muted-foreground" aria-live="polite">
                  Page {safePage} of {totalPages}
                </span>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => setPage((current) => Math.min(totalPages, current + 1))}
                  disabled={safePage >= totalPages}
                  aria-label="Next controls page"
                >
                  Next
                </Button>
              </div>
            </div>
          ) : null}

          <p className="text-[11px] leading-5 text-muted-foreground">
            Counts: {formatNumber(report.counts.controls_total)} controls ·{" "}
            {formatNumber(report.counts.resolved)} resolved ·{" "}
            {formatNumber(report.counts.missing_part)} missing part ·{" "}
            {formatNumber(report.counts.unknown_path)} unknown path ·{" "}
            {formatNumber(report.counts.ambiguous)} ambiguous · {formatRatio(report.counts.coverage_ratio)}{" "}
            coverage. Runtime compatibility is not tested.
          </p>
        </CardContent>
      </Card>

      <ReferenceControlDrawer row={selected} onClose={closeDrawer} />
    </>
  );
}
