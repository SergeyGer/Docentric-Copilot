"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Download, FileSearch, GitBranch, ListChecks, Loader2 } from "lucide-react";

import { ReferenceControlsPanel } from "@/components/reference/reference-controls-panel";
import { ReferenceDiffPanel } from "@/components/reference/reference-diff-panel";
import { ReferenceGraphPanel } from "@/components/reference/reference-graph-panel";
import { ReferenceOverviewPanel } from "@/components/reference/reference-overview-panel";
import { ReferenceUploadPanel } from "@/components/reference/reference-upload-panel";
import { RuntimeCompatibilityNotice } from "@/components/reference/reference-badges";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { EmptyState } from "@/components/workspace/empty-state";
import { ErrorAlert } from "@/components/workspace/error-alert";
import {
  ApiError,
  apiRequest,
  buildReferenceGraph,
  getStoredReferenceReport,
  persistReferenceInspection,
  referenceReportExportPath,
  toApiError,
  triggerDownload,
} from "@/lib/api";
import { formatBytes, formatNumber } from "@/lib/format";
import {
  REFERENCE_SCHEMA_EXTENSIONS,
  REFERENCE_TEMPLATE_EXTENSIONS,
  hasReferenceExtension,
} from "@/lib/reference";
import type {
  CapabilitiesView,
  ReferenceGraph,
  ReferenceReport,
  ReferenceReportExportFormat,
  StoredReferenceReport,
} from "@/lib/types";

type ReferenceTab = "overview" | "controls" | "graph" | "diff";

function readReportIdFromUrl(): string | null {
  if (typeof window === "undefined") {
    return null;
  }
  const value = new URLSearchParams(window.location.search).get("id");
  return value && value.trim().length > 0 ? value.trim() : null;
}

function writeReportIdToUrl(reportId: string | null): void {
  if (typeof window === "undefined") {
    return;
  }
  const url = new URL(window.location.href);
  if (reportId) {
    url.searchParams.set("id", reportId);
  } else {
    url.searchParams.delete("id");
  }
  window.history.replaceState({}, "", url);
}

function validateInspectionInput(
  file: File,
  ddsp: File | null,
  limitBytes: number | null,
): ApiError | null {
  if (!hasReferenceExtension(file.name, REFERENCE_TEMPLATE_EXTENSIONS)) {
    return new ApiError(
      `Unsupported template file type "${file.name}". Choose a .docx, .zip or .axpp file.`,
      {
        status: 400,
        code: "input_unsupported",
        details: {
          field: "file",
          filename: file.name,
          allowed: [...REFERENCE_TEMPLATE_EXTENSIONS],
        },
      },
    );
  }
  if (ddsp && !hasReferenceExtension(ddsp.name, REFERENCE_SCHEMA_EXTENSIONS)) {
    return new ApiError(
      `Unsupported DDSP schema type "${ddsp.name}". Choose an .xml or .ddsp file.`,
      {
        status: 400,
        code: "input_unsupported",
        details: {
          field: "ddsp",
          filename: ddsp.name,
          allowed: [...REFERENCE_SCHEMA_EXTENSIONS],
        },
      },
    );
  }
  if (limitBytes !== null && file.size > limitBytes) {
    return new ApiError(
      `"${file.name}" is ${formatBytes(file.size)}, larger than the API upload limit of ${formatBytes(limitBytes)}.`,
      {
        status: 413,
        code: "reference_input_too_large",
        details: { filename: file.name, size_bytes: file.size, max_bytes: limitBytes },
      },
    );
  }
  if (ddsp && limitBytes !== null && ddsp.size > limitBytes) {
    return new ApiError(
      `The DDSP schema "${ddsp.name}" is ${formatBytes(ddsp.size)}, larger than the API upload limit of ${formatBytes(limitBytes)}.`,
      {
        status: 413,
        code: "reference_input_too_large",
        details: { filename: ddsp.name, size_bytes: ddsp.size, max_bytes: limitBytes },
      },
    );
  }
  return null;
}

function ResultsLoading({ title }: { title: string }) {
  return (
    <Card aria-busy="true">
      <CardContent className="space-y-3 pt-5">
        <p className="flex items-center gap-2 text-xs font-medium text-foreground">
          <Loader2 aria-hidden="true" className="h-3.5 w-3.5 animate-spin text-primary" />
          {title}
        </p>
        <Skeleton className="h-5 w-2/3" />
        <Skeleton className="h-24 w-full" />
        <p className="text-[11px] text-muted-foreground">
          Large ZIP or AXPP containers may take a little longer. Nothing is executed or written.
        </p>
      </CardContent>
    </Card>
  );
}

/**
 * Top-level reference inspector. One upload drives the Overview, Controls and
 * Graph tabs; Diff is an independent two-file comparison inside its own tab.
 */
export function ReferenceInspector() {
  const [tab, setTab] = useState<ReferenceTab>("overview");
  const [file, setFile] = useState<File | null>(null);
  const [ddsp, setDdsp] = useState<File | null>(null);
  const [report, setReport] = useState<ReferenceReport | null>(null);
  const [graph, setGraph] = useState<ReferenceGraph | null>(null);
  const [inspectPending, setInspectPending] = useState(false);
  const [graphPending, setGraphPending] = useState(false);
  const [uploadError, setUploadError] = useState<ApiError | null>(null);
  const [graphError, setGraphError] = useState<ApiError | null>(null);
  const [limitBytes, setLimitBytes] = useState<number | null>(null);
  const [announcement, setAnnouncement] = useState("");
  const [reportId, setReportId] = useState<string | null>(null);
  const [exportFormat, setExportFormat] =
    useState<ReferenceReportExportFormat>("json");
  const requestRef = useRef(0);
  const busy = inspectPending || graphPending;

  useEffect(() => {
    let cancelled = false;
    apiRequest<CapabilitiesView>("/api/v1/capabilities", {}, { timeoutMs: 10_000 })
      .then((data) => {
        if (cancelled) {
          return;
        }
        const limit = data.limits.max_ddsp_bytes;
        if (typeof limit === "number" && Number.isFinite(limit) && limit > 0) {
          setLimitBytes(limit);
        }
      })
      .catch(() => {
        // The limit is optional display metadata; the API still enforces it.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Reopen the last persisted report from `?id=`. An absent or invalid id must
  // never crash the page: the error is shown and the query string is cleared.
  useEffect(() => {
    const storedId = readReportIdFromUrl();
    if (!storedId) {
      return;
    }
    let cancelled = false;
    const requestId = requestRef.current + 1;
    requestRef.current = requestId;
    setInspectPending(true);
    setGraphPending(true);
    setUploadError(null);
    setGraphError(null);
    setAnnouncement(`Reopening saved reference report ${storedId}.`);
    getStoredReferenceReport(storedId)
      .then((record: StoredReferenceReport) => {
        if (cancelled || requestRef.current !== requestId) {
          return;
        }
        setReportId(record.id);
        setReport(record.report);
        setGraph(record.graph);
        setTab(record.report ? "overview" : "graph");
        setAnnouncement(
          `Saved report ${record.id} reopened: ${record.source_name}. Docentric AX runtime compatibility: not tested.`,
        );
      })
      .catch((caught: unknown) => {
        if (cancelled || requestRef.current !== requestId) {
          return;
        }
        const apiError = toApiError(caught);
        setReportId(null);
        setReport(null);
        setGraph(null);
        setUploadError(apiError);
        setAnnouncement(`Saved report could not be reopened: ${apiError.message}`);
        writeReportIdToUrl(null);
      })
      .finally(() => {
        if (!cancelled && requestRef.current === requestId) {
          setInspectPending(false);
          setGraphPending(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const clearResults = useCallback(() => {
    setReport(null);
    setGraph(null);
    setUploadError(null);
    setGraphError(null);
  }, []);

  const clearStoredReport = useCallback(() => {
    setReportId(null);
    writeReportIdToUrl(null);
  }, []);

  const handleFileChange = useCallback(
    (next: File | null) => {
      requestRef.current += 1;
      setFile(next);
      setInspectPending(false);
      setGraphPending(false);
      clearResults();
      clearStoredReport();
      setAnnouncement(
        next
          ? `Selected ${next.name} (${formatBytes(next.size)}). Select Inspect reference to analyse it.`
          : "Template selection cleared.",
      );
    },
    [clearResults, clearStoredReport],
  );

  const handleDdspChange = useCallback(
    (next: File | null) => {
      requestRef.current += 1;
      setDdsp(next);
      setInspectPending(false);
      setGraphPending(false);
      clearResults();
      clearStoredReport();
      setAnnouncement(
        next
          ? `Selected DDSP schema ${next.name} (${formatBytes(next.size)}).`
          : "DDSP schema cleared.",
      );
    },
    [clearResults, clearStoredReport],
  );

  const handleReset = useCallback(() => {
    requestRef.current += 1;
    setFile(null);
    setDdsp(null);
    setInspectPending(false);
    setGraphPending(false);
    clearResults();
    clearStoredReport();
    setAnnouncement("Reference inspector cleared.");
  }, [clearResults, clearStoredReport]);

  const handleInspect = useCallback(async () => {
    if (!file || busy) {
      return;
    }
    const validationError = validateInspectionInput(file, ddsp, limitBytes);
    if (validationError) {
      setUploadError(validationError);
      setAnnouncement(validationError.message);
      return;
    }

    const requestId = requestRef.current + 1;
    requestRef.current = requestId;
    setInspectPending(true);
    setGraphPending(true);
    setReport(null);
    setGraph(null);
    setUploadError(null);
    setGraphError(null);
    setAnnouncement(`Inspecting and saving ${file.name} together with its reference graph.`);

    try {
      const stored = await persistReferenceInspection(file, ddsp);
      if (requestRef.current !== requestId) {
        return;
      }
      setReport(stored.report);
      setGraph(stored.graph);
      setReportId(stored.id);
      writeReportIdToUrl(stored.id);
      setTab(stored.report ? "overview" : "graph");
      const counts = stored.report?.counts;
      setAnnouncement(
        counts
          ? `Inspection complete for ${stored.source_name}: ${formatNumber(counts.controls_total)} controls, ${formatNumber(counts.classification_recognized)} recognized, ${formatNumber(counts.classification_ambiguous)} ambiguous and ${formatNumber(counts.classification_unknown)} unknown. Saved as ${stored.id}. Docentric AX runtime compatibility: not tested.`
          : `Reference graph saved as ${stored.id} for ${stored.source_name}. Docentric AX runtime compatibility: not tested.`,
      );
    } catch (caught) {
      if (requestRef.current !== requestId) {
        return;
      }
      const apiError = toApiError(caught);
      setUploadError(apiError);
      setAnnouncement(`Inspection failed: ${apiError.message}`);
    } finally {
      if (requestRef.current === requestId) {
        setInspectPending(false);
        setGraphPending(false);
      }
    }
  }, [busy, ddsp, file, limitBytes]);

  const retryGraph = useCallback(async () => {
    if (graphPending) {
      return;
    }
    if (!file && !reportId) {
      return;
    }
    const requestId = requestRef.current;
    setGraphPending(true);
    setGraphError(null);
    setAnnouncement("Retrying the reference graph.");
    try {
      const result = reportId
        ? (await getStoredReferenceReport(reportId)).graph
        : await buildReferenceGraph(file as File, ddsp);
      if (requestRef.current !== requestId) {
        return;
      }
      if (result) {
        setGraph(result);
        setAnnouncement(
          `Reference graph complete: ${formatNumber(result.summary.node_count)} nodes and ${formatNumber(result.summary.edge_count)} edges.`,
        );
      }
    } catch (caught) {
      if (requestRef.current !== requestId) {
        return;
      }
      const apiError = toApiError(caught);
      setGraphError(apiError);
      setAnnouncement(`Reference graph failed: ${apiError.message}`);
    } finally {
      if (requestRef.current === requestId) {
        setGraphPending(false);
      }
    }
  }, [ddsp, file, graphPending, reportId]);

  const controlsCount = report?.counts.controls_total ?? 0;
  const graphNodeCount = graph?.summary.node_count ?? 0;

  return (
    <div className="mx-auto w-full max-w-[1440px] px-4 py-6 sm:px-6 lg:px-8">
      <div className="flex flex-col gap-4 border-b border-border pb-6 lg:flex-row lg:items-end lg:justify-between">
        <div className="max-w-3xl">
          <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-primary">
            Read-only reference inspection
          </p>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight text-foreground sm:text-[28px]">
            Reference template inspector
          </h1>
          <p className="mt-1.5 text-sm leading-6 text-muted-foreground">
            Inspect content controls, ProjectData evidence, DDSP binding resolution and the
            reference graph behind an existing Docentric template. Compare two templates
            structurally and semantically. Nothing is compiled or executed; inspection
            evidence is saved locally so a report can be reopened and exported by id.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="outline">ReferenceReport v1.0</Badge>
          <Badge variant="outline">ReferenceGraph v1.0</Badge>
          <Badge variant="outline">ReferenceDiff v1.0</Badge>
          <Badge variant="unverified">AX compatibility not tested</Badge>
        </div>
      </div>

      <RuntimeCompatibilityNotice className="mt-4" />

      {reportId ? (
        <div
          data-testid="reference-saved-report"
          className="mt-3 flex flex-wrap items-center gap-2 rounded-lg border border-border bg-muted/15 px-3 py-2"
        >
          <span className="text-xs text-muted-foreground">
            Saved report <code className="break-all font-mono text-foreground">{reportId}</code>
          </span>
          <Select
            aria-label="Export format"
            data-testid="reference-export-format"
            className="h-8 w-24"
            value={exportFormat}
            onChange={(event) => {
              const value = event.target.value;
              if (value === "json" || value === "html") {
                setExportFormat(value);
              }
            }}
          >
            <option value="json">JSON</option>
            <option value="html">HTML</option>
          </Select>
          <Button
            type="button"
            size="sm"
            variant="outline"
            data-testid="reference-export-button"
            onClick={() =>
              triggerDownload(
                referenceReportExportPath(reportId, exportFormat),
                `reference-report-${reportId}.${exportFormat}`,
              )
            }
          >
            <Download aria-hidden="true" />
            Export report
          </Button>
        </div>
      ) : null}

      <p role="status" aria-live="polite" className="sr-only">
        {announcement}
      </p>

      <ReferenceUploadPanel
        className="mt-4"
        file={file}
        ddsp={ddsp}
        onFileChange={handleFileChange}
        onDdspChange={handleDdspChange}
        onInspect={() => {
          void handleInspect();
        }}
        onReset={handleReset}
        inspecting={inspectPending}
        graphPending={graphPending}
        limitBytes={limitBytes}
        error={uploadError}
        onDismissError={() => setUploadError(null)}
        hasResults={report !== null || graph !== null}
      />

      <Tabs
        defaultValue="overview"
        value={tab}
        onValueChange={(value) => setTab(value as ReferenceTab)}
        className="mt-6"
      >
        <TabsList
          aria-label="Reference inspector results"
          className="h-auto w-full justify-start gap-1 overflow-x-auto p-1"
        >
          <TabsTrigger value="overview" data-testid="reference-tab-overview">
            Overview
          </TabsTrigger>
          <TabsTrigger value="controls" data-testid="reference-tab-controls">
            Controls
            {report ? (
              <Badge variant="muted" className="ml-0.5">
                {formatNumber(controlsCount)}
              </Badge>
            ) : null}
          </TabsTrigger>
          <TabsTrigger value="graph" data-testid="reference-tab-graph">
            Graph
            {graph ? (
              <Badge variant="muted" className="ml-0.5">
                {formatNumber(graphNodeCount)}
              </Badge>
            ) : null}
          </TabsTrigger>
          <TabsTrigger value="diff" data-testid="reference-tab-diff">
            Diff
          </TabsTrigger>
        </TabsList>

        <TabsContent value="overview">
          {report ? (
            <ReferenceOverviewPanel report={report} />
          ) : inspectPending ? (
            <ResultsLoading title="Inspecting the reference and building the report…" />
          ) : (
            <EmptyState
              icon={FileSearch}
              title="No inspection yet"
              description="Upload a .docx, .zip or .axpp reference template above, optionally add the matching DDSP schema, then select Inspect reference. The Overview will show containers, duplicates, control classifications, resolution counts and coverage."
            />
          )}
        </TabsContent>

        <TabsContent value="controls">
          {report ? (
            <ReferenceControlsPanel report={report} />
          ) : inspectPending ? (
            <ResultsLoading title="Scanning content controls…" />
          ) : (
            <EmptyState
              icon={ListChecks}
              title="No control inventory yet"
              description="Inspect a reference template to list every content control with its tag or alias, kind, part, paragraph, binding, resolution status and classification. Unknown and ambiguous controls are always shown."
            />
          )}
        </TabsContent>

        <TabsContent value="graph">
          {graph ? (
            <ReferenceGraphPanel graph={graph} />
          ) : graphError ? (
            <ErrorAlert
              error={graphError}
              title="Reference graph failed"
              action={
                file ? (
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={() => {
                      void retryGraph();
                    }}
                    disabled={graphPending}
                  >
                    {graphPending ? <Loader2 aria-hidden="true" className="animate-spin" /> : null}
                    Retry graph
                  </Button>
                ) : null
              }
            />
          ) : graphPending ? (
            <ResultsLoading title="Building the reference graph…" />
          ) : (
            <EmptyState
              icon={GitBranch}
              title="No reference graph yet"
              description="Inspect a reference template to build its read-only graph: controls bound to ProjectData elements, elements resolving to DDSP schema fields, sources, iterates/condition edges and an explicit unresolved list."
            />
          )}
        </TabsContent>

        <TabsContent value="diff">
          <ReferenceDiffPanel />
        </TabsContent>
      </Tabs>
    </div>
  );
}
