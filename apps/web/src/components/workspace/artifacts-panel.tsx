"use client";

import {
  AlertTriangle,
  Download,
  Eye,
  FileArchive,
  FileDown,
  Loader2,
} from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { CheckboxRow } from "@/components/workspace/checkbox-row";
import { EmptyState } from "@/components/workspace/empty-state";
import { ErrorAlert } from "@/components/workspace/error-alert";
import { OverallStatusBadge } from "@/components/workspace/status-badges";
import { Panel } from "@/components/workspace/panel";
import { apiUrl, type ApiError } from "@/lib/api";
import { PANEL_IDS } from "@/lib/constants";
import {
  artifactKindLabel,
  formatBytes,
  formatDateTime,
  formatNumber,
  humanizeKey,
  pluralize,
  truncateMiddle,
} from "@/lib/format";
import { overallFromStatuses } from "@/lib/validation";
import type {
  ArtifactView,
  CompileResponse,
  RenderMode,
} from "@/lib/types";
import { cn } from "@/lib/utils";

const STAT_ORDER = [
  "paragraphs",
  "tables",
  "images",
  "bindings_rendered",
  "repeats_expanded",
  "placeholders",
];

const RENDER_MODES: ReadonlyArray<{ value: RenderMode; label: string; hint: string }> = [
  { value: "auto", label: "Auto", hint: "Sample data when available, placeholders otherwise" },
  { value: "sample", label: "Sample data", hint: "Bind the packaged sample XML" },
  { value: "placeholder", label: "Placeholders", hint: "Render field names without sample values" },
];

export interface ArtifactsPanelProps {
  artifacts: ArtifactView[];
  compileResult: CompileResponse | null;
  compilePending: boolean;
  compileError: ApiError | null;
  templateId: string | null;
  activeVersion: number | null;
  documentName: string;
  onDocumentNameChange: (value: string) => void;
  renderMode: RenderMode;
  onRenderModeChange: (value: RenderMode) => void;
  includeCompatibilityStamp: boolean;
  onIncludeCompatibilityStampChange: (value: boolean) => void;
  useSampleData: boolean;
  onUseSampleDataChange: (value: boolean) => void;
  onCompile: () => void;
  onDownloadDocx: () => void;
  onDismissCompileError: () => void;
}

export function ArtifactsPanel({
  artifacts,
  compileResult,
  compilePending,
  compileError,
  templateId,
  activeVersion,
  documentName,
  onDocumentNameChange,
  renderMode,
  onRenderModeChange,
  includeCompatibilityStamp,
  onIncludeCompatibilityStampChange,
  useSampleData,
  onUseSampleDataChange,
  onCompile,
  onDownloadDocx,
  onDismissCompileError,
}: ArtifactsPanelProps) {
  const sortedStats = compileResult
    ? Object.entries(compileResult.stats).sort(([left], [right]) => {
        const leftIndex = STAT_ORDER.indexOf(left);
        const rightIndex = STAT_ORDER.indexOf(right);
        const normalizedLeft = leftIndex === -1 ? STAT_ORDER.length : leftIndex;
        const normalizedRight = rightIndex === -1 ? STAT_ORDER.length : rightIndex;
        return normalizedLeft - normalizedRight || left.localeCompare(right);
      })
    : [];
  const compileOverall = compileResult
    ? overallFromStatuses(compileResult.validation)
    : null;

  return (
    <Panel
      id={PANEL_IDS.artifacts}
      step={7}
      title="Artifacts & download"
      description="Compile the active Template IR into a deterministic generic DOCX, then download the artifact bundle published by the API."
      actions={
        <>
          <Badge variant="outline">
            {formatNumber(artifacts.length)} {pluralize(artifacts.length, "artifact")}
          </Badge>
          {compileResult ? (
            <Button type="button" size="sm" variant="outline" onClick={onDownloadDocx}>
              <Download aria-hidden="true" />
              Download DOCX
            </Button>
          ) : null}
        </>
      }
    >
      <div className="space-y-4">
        <div className="rounded-lg border bg-muted/15 p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-xs font-semibold text-foreground">Compile options</h3>
            <div className="flex flex-wrap items-center gap-1.5">
              <Badge variant="outline" className="font-mono">
                target: generic-docx
              </Badge>
              {activeVersion !== null ? (
                <Badge variant="outline" className="font-mono">
                  version: {activeVersion}
                </Badge>
              ) : null}
            </div>
          </div>

          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <label htmlFor="document-name" className="text-xs font-medium text-foreground">
                Document file name
              </label>
              <Input
                id="document-name"
                value={documentName}
                onChange={(event) => onDocumentNameChange(event.target.value)}
                maxLength={120}
                placeholder="document.docx"
                disabled={compilePending}
                aria-describedby="document-name-hint"
              />
              <p id="document-name-hint" className="text-[11px] leading-4 text-muted-foreground">
                The .docx extension is added automatically.
              </p>
            </div>
            <div className="space-y-1.5">
              <label htmlFor="render-mode" className="text-xs font-medium text-foreground">
                Render mode
              </label>
              <Select
                id="render-mode"
                value={renderMode}
                onChange={(event) => onRenderModeChange(event.target.value as RenderMode)}
                disabled={compilePending}
                aria-describedby="render-mode-hint"
              >
                {RENDER_MODES.map((mode) => (
                  <option key={mode.value} value={mode.value}>
                    {mode.label}
                  </option>
                ))}
              </Select>
              <p id="render-mode-hint" className="text-[11px] leading-4 text-muted-foreground">
                {RENDER_MODES.find((mode) => mode.value === renderMode)?.hint}
              </p>
            </div>
          </div>

          <div className="mt-3 grid gap-2 sm:grid-cols-2">
            <CheckboxRow
              id="include-stamp"
              checked={includeCompatibilityStamp}
              onChange={onIncludeCompatibilityStampChange}
              label="Include compatibility stamp"
              description="Adds a clearly marked 'unverified compatibility' stamp. It is not a verification."
              disabled={compilePending}
            />
            <CheckboxRow
              id="use-sample-data"
              checked={useSampleData}
              onChange={onUseSampleDataChange}
              label="Use sample data"
              description="Render packaged sample values during validation and compilation."
              disabled={compilePending}
            />
          </div>

          <div className="mt-3 flex flex-wrap items-center gap-2">
            <Button
              type="button"
              onClick={onCompile}
              disabled={!templateId || compilePending}
              aria-busy={compilePending}
            >
              {compilePending ? (
                <Loader2 aria-hidden="true" className="animate-spin" />
              ) : (
                <FileDown aria-hidden="true" />
              )}
              {compilePending ? "Compiling DOCX…" : "Compile DOCX"}
            </Button>
            {compileResult ? (
              <Button type="button" variant="outline" onClick={onDownloadDocx}>
                <Download aria-hidden="true" />
                Download again
              </Button>
            ) : null}
            <p className="text-[11px] leading-4 text-muted-foreground">
              {templateId && activeVersion !== null
                ? `Compiles version ${activeVersion}; the download starts automatically.`
                : "Plan a template before compiling a DOCX."}
            </p>
          </div>
        </div>

        {compileError ? (
          <ErrorAlert
            error={compileError}
            title="Compilation failed"
            onDismiss={onDismissCompileError}
          />
        ) : null}

        {compileResult ? (
          <div className="overflow-hidden rounded-lg border">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b bg-card px-3 py-2.5">
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="text-xs font-semibold text-foreground">Compile result</h3>
                <Badge variant="success">completed</Badge>
                {compileOverall ? <OverallStatusBadge overall={compileOverall} /> : null}
              </div>
              <p className="font-mono text-[10px] text-muted-foreground">
                job {compileResult.job_id} · IR {truncateMiddle(compileResult.ir_digest)}
              </p>
            </div>
            <dl className="grid grid-cols-2 gap-px bg-border sm:grid-cols-3">
              {sortedStats.map(([key, value]) => (
                <div key={key} className="bg-card px-3 py-2.5">
                  <dt className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
                    {humanizeKey(key)}
                  </dt>
                  <dd className="mt-0.5 font-mono text-lg font-semibold leading-6 text-foreground">
                    {formatNumber(value)}
                  </dd>
                </div>
              ))}
              {sortedStats.length === 0 ? (
                <div className="col-span-full bg-card px-3 py-3 text-xs text-muted-foreground">
                  The API returned no compile statistics.
                </div>
              ) : null}
            </dl>
            {compileResult.warnings.length > 0 ? (
              <div className="border-t p-3">
                <Alert variant="warning">
                  <AlertTriangle aria-hidden="true" />
                  <div>
                    <AlertTitle>
                      {compileResult.warnings.length} compile{" "}
                      {pluralize(compileResult.warnings.length, "warning")}
                    </AlertTitle>
                    <AlertDescription>
                      <ul className="list-disc space-y-1 pl-4">
                        {compileResult.warnings.map((warning, index) => (
                          <li key={`${warning}-${index}`} className="text-[11px] leading-5">
                            {warning}
                          </li>
                        ))}
                      </ul>
                    </AlertDescription>
                  </div>
                </Alert>
              </div>
            ) : (
              <p className="border-t px-3 py-2 text-[11px] text-muted-foreground">
                The compiler reported no warnings for this document.
              </p>
            )}
          </div>
        ) : null}

        <div>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-xs font-semibold text-foreground">Artifacts</h3>
            <p className="text-[10px] text-muted-foreground">
              From the most recent API response · expires automatically
            </p>
          </div>

          {artifacts.length === 0 ? (
            <EmptyState
              icon={FileArchive}
              title="No artifacts yet"
              description="Planning a template publishes IR, mapping, validation and preview artifacts. Compiling adds the DOCX bundle."
              compact
              className="mt-2"
            />
          ) : (
            <ul className="mt-2 divide-y overflow-hidden rounded-lg border">
              {artifacts.map((artifact) => {
                const viewable =
                  artifact.kind === "preview" || artifact.kind === "validation_html";
                return (
                  <li
                    key={artifact.id}
                    className="flex flex-col gap-2 bg-card p-3 sm:flex-row sm:items-center"
                  >
                    <Badge
                      variant="secondary"
                      className="w-fit shrink-0 font-mono text-[10px] uppercase"
                      title={artifactKindLabel(artifact.kind)}
                    >
                      {artifact.kind}
                    </Badge>
                    <div className="min-w-0 flex-1">
                      <p className="break-all text-xs font-medium text-foreground">
                        {artifact.filename}
                      </p>
                      <p className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[10px] text-muted-foreground">
                        <span>{formatBytes(artifact.size_bytes)}</span>
                        <span aria-hidden="true">·</span>
                        <span className="font-mono">
                          sha {truncateMiddle(artifact.digest, 8, 6)}
                        </span>
                        <span aria-hidden="true">·</span>
                        <span>expires {formatDateTime(artifact.expires_at)}</span>
                      </p>
                    </div>
                    <div className="flex shrink-0 flex-wrap items-center gap-1.5">
                      {viewable ? (
                        <a
                          href={apiUrl(`${artifact.url}/view`)}
                          target="_blank"
                          rel="noopener noreferrer"
                          className={cn(buttonVariants({ variant: "ghost", size: "sm" }))}
                        >
                          <Eye aria-hidden="true" />
                          View
                        </a>
                      ) : null}
                      <a
                        href={apiUrl(artifact.url)}
                        target="_blank"
                        rel="noopener noreferrer"
                        title={apiUrl(artifact.url)}
                        className={cn(buttonVariants({ variant: "outline", size: "sm" }))}
                      >
                        <Download aria-hidden="true" />
                        Download
                      </a>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </div>
    </Panel>
  );
}
