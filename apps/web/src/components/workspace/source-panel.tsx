import type { ChangeEvent, DragEvent, RefObject } from "react";
import { useRef, useState } from "react";
import {
  Database,
  DatabaseZap,
  FileCode2,
  FolderOpen,
  Loader2,
  RefreshCw,
  UploadCloud,
} from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { Skeleton } from "@/components/ui/skeleton";
import { CopyButton } from "@/components/workspace/copy-button";
import { EmptyState } from "@/components/workspace/empty-state";
import { ErrorAlert } from "@/components/workspace/error-alert";
import { Panel } from "@/components/workspace/panel";
import type { ApiError } from "@/lib/api";
import { ACCEPTED_SOURCE_EXTENSIONS, PANEL_IDS } from "@/lib/constants";
import { formatBytes, formatNumber } from "@/lib/format";
import type { Diagnostic, SourceView } from "@/lib/types";
import { cn } from "@/lib/utils";

const SEVERITY_STYLE = {
  error: "border-destructive/25 bg-destructive/5 text-destructive",
  warning: "border-warning/25 bg-warning/5 text-warning",
  info: "border-info/20 bg-info/5 text-info",
} as const;

const SEVERITY_LABEL = {
  error: "Error",
  warning: "Warning",
  info: "Info",
} as const;

interface DiagnosticListProps {
  diagnostics: Diagnostic[];
}

function DiagnosticList({ diagnostics }: DiagnosticListProps) {
  if (diagnostics.length === 0) {
    return (
      <p className="flex items-center gap-2 rounded-md border border-success/20 bg-success/5 px-3 py-2 text-xs text-success">
        <DatabaseZap aria-hidden="true" className="h-3.5 w-3.5" />
        No diagnostics reported for this source.
      </p>
    );
  }
  return (
    <ul className="scroll-area max-h-48 space-y-1.5 overflow-y-auto pr-1">
      {diagnostics.map((diagnostic, index) => (
        <li
          key={`${diagnostic.code}-${index}`}
          className={cn(
            "rounded-md border px-2.5 py-1.5 text-[11px] leading-5",
            SEVERITY_STYLE[diagnostic.severity],
          )}
        >
          <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
            <span className="font-semibold uppercase tracking-wide">
              {SEVERITY_LABEL[diagnostic.severity]}
            </span>
            <code className="rounded bg-card/60 px-1 font-mono text-[10px]">
              {diagnostic.code}
            </code>
            {diagnostic.location ? (
              <span className="truncate font-mono text-[10px] opacity-80">
                {diagnostic.location}
              </span>
            ) : null}
          </div>
          <p className="text-foreground">{diagnostic.message}</p>
        </li>
      ))}
    </ul>
  );
}

interface StatTileProps {
  label: string;
  value: string;
}

function StatTile({ label, value }: StatTileProps) {
  return (
    <div className="rounded-md border bg-muted/25 px-2.5 py-2">
      <dt className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </dt>
      <dd className="mt-0.5 font-mono text-sm font-semibold text-foreground">{value}</dd>
    </div>
  );
}

export interface SourcePanelProps {
  source: SourceView | null;
  diagnostics: Diagnostic[];
  uploadPending: boolean;
  schemaPending: boolean;
  uploadError: ApiError | null;
  schemaError: ApiError | null;
  maxUploadBytes: number;
  onUpload: (file: File) => void;
  onReloadSchema: () => void;
  onDismissUploadError: () => void;
  onDismissSchemaError: () => void;
}

export function SourcePanel({
  source,
  diagnostics,
  uploadPending,
  schemaPending,
  uploadError,
  schemaError,
  maxUploadBytes,
  onUpload,
  onReloadSchema,
  onDismissUploadError,
  onDismissSchemaError,
}: SourcePanelProps) {
  const inputRef = useRef<HTMLInputElement>(null) as RefObject<HTMLInputElement>;
  const [dragging, setDragging] = useState(false);

  const acceptFiles = (files: FileList | null) => {
    const file = files?.[0];
    if (file) {
      onUpload(file);
    }
  };

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    acceptFiles(event.dataTransfer.files);
  };

  const openPicker = () => {
    inputRef.current?.click();
  };

  const handleInputChange = (event: ChangeEvent<HTMLInputElement>) => {
    acceptFiles(event.target.files);
    event.target.value = "";
  };

  return (
    <Panel
      id={PANEL_IDS.source}
      step={1}
      title="Data source"
      description="Upload the DDSP package the document will bind to. The API parses it server-side and discovers the normalized schema."
      actions={
        source ? (
          <Badge variant="outline" className="font-mono">
            {source.source_id}
          </Badge>
        ) : null
      }
    >
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
        <div className="space-y-3">
          <div
            className={cn(
              "rounded-lg border-2 border-dashed px-5 py-6 text-center transition-colors",
              dragging
                ? "border-primary bg-primary/5"
                : "border-border bg-muted/20 hover:border-primary/40 hover:bg-muted/30",
            )}
            onDragOver={(event) => {
              event.preventDefault();
              setDragging(true);
            }}
            onDragLeave={(event) => {
              event.preventDefault();
              setDragging(false);
            }}
            onDrop={handleDrop}
          >
            <span className="mx-auto flex h-10 w-10 items-center justify-center rounded-full bg-primary/10 text-primary">
              <UploadCloud aria-hidden="true" className="h-5 w-5" />
            </span>
            <p className="mt-2 text-sm font-medium text-foreground">
              Drop a DDSP or XML file here
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              or choose a file from your computer
            </p>
            <div className="mt-3 flex flex-wrap items-center justify-center gap-2">
              <Button
                type="button"
                size="sm"
                onClick={openPicker}
                disabled={uploadPending}
                aria-busy={uploadPending}
              >
                {uploadPending ? (
                  <Loader2 aria-hidden="true" className="animate-spin" />
                ) : (
                  <FolderOpen aria-hidden="true" />
                )}
                {uploadPending ? "Uploading…" : source ? "Replace file" : "Choose file"}
              </Button>
              {uploadPending ? (
                <span
                  role="status"
                  aria-live="polite"
                  className="inline-flex items-center gap-1.5 text-xs text-muted-foreground"
                >
                  <Loader2 aria-hidden="true" className="h-3.5 w-3.5 animate-spin" />
                  Parsing the package…
                </span>
              ) : null}
            </div>
            <input
              ref={inputRef}
              id="source-file"
              type="file"
              accept={ACCEPTED_SOURCE_EXTENSIONS.join(",")}
              onChange={handleInputChange}
              disabled={uploadPending}
              aria-label="Upload a DDSP or XML data source"
              className="sr-only"
            />
            <p className="mt-3 text-[11px] text-muted-foreground">
              Accepted: {ACCEPTED_SOURCE_EXTENSIONS.join(", ")} · Max{" "}
              {formatBytes(maxUploadBytes)}
            </p>
          </div>

          {uploadError ? (
            <ErrorAlert
              error={uploadError}
              title="Upload failed"
              onDismiss={onDismissUploadError}
            />
          ) : null}
          {schemaError ? (
            <ErrorAlert
              error={schemaError}
              title="Schema discovery failed"
              onDismiss={onDismissSchemaError}
              action={
                <Button type="button" size="sm" variant="outline" onClick={onReloadSchema}>
                  <RefreshCw aria-hidden="true" />
                  Retry schema
                </Button>
              }
            />
          ) : null}

          {source ? (
            <div className="rounded-lg border bg-card p-3">
              <div className="flex items-start gap-2.5">
                <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
                  <FileCode2 aria-hidden="true" className="h-4 w-4" />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-foreground" title={source.filename}>
                    {source.filename}
                  </p>
                  <p className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
                    Source ID
                    <code className="truncate font-mono text-[10px]">{source.source_id}</code>
                    <CopyButton value={source.source_id} label="Copy source ID" />
                  </p>
                </div>
                <Badge variant={source.sample_data_available ? "success" : "muted"}>
                  <Database aria-hidden="true" className="h-3 w-3" />
                  {source.sample_data_available ? "Sample data" : "No sample data"}
                </Badge>
              </div>

              <dl className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
                <StatTile label="Fields" value={formatNumber(source.stats.node_count)} />
                <StatTile label="Scalars" value={formatNumber(source.stats.scalar_count)} />
                <StatTile
                  label="Collections"
                  value={formatNumber(source.stats.collection_count)}
                />
                <StatTile label="Max depth" value={formatNumber(source.stats.max_depth)} />
              </dl>

              <div className="mt-3 space-y-2">
                <div>
                  <p className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
                    Schema ID
                  </p>
                  <p className="flex items-center gap-1">
                    <code className="font-mono text-xs text-foreground">{source.schema_id}</code>
                    <CopyButton value={source.schema_id} label="Copy schema ID" />
                  </p>
                </div>
                <div>
                  <p className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
                    Sections ({source.sections.length})
                  </p>
                  <div className="mt-1 flex flex-wrap gap-1.5">
                    {source.sections.length > 0 ? (
                      source.sections.map((section) => (
                        <Badge key={section} variant="secondary" className="font-mono">
                          {section}
                        </Badge>
                      ))
                    ) : (
                      <span className="text-xs text-muted-foreground">No sections detected</span>
                    )}
                  </div>
                </div>
                {source.entry_names.length > 0 ? (
                  <Collapsible className="rounded-md border bg-muted/20 px-2.5 py-2">
                    <CollapsibleTrigger className="text-xs text-muted-foreground hover:text-foreground">
                      Package entries ({source.entry_names.length})
                    </CollapsibleTrigger>
                    <CollapsibleContent>
                      <ul className="space-y-0.5">
                        {source.entry_names.map((entry) => (
                          <li key={entry} className="break-all font-mono text-[11px] text-muted-foreground">
                            {entry}
                          </li>
                        ))}
                      </ul>
                    </CollapsibleContent>
                  </Collapsible>
                ) : null}
                {schemaPending ? (
                  <div className="space-y-1.5" role="status" aria-live="polite">
                    <span className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                      <Loader2 aria-hidden="true" className="h-3 w-3 animate-spin" />
                      Loading the normalized schema…
                    </span>
                    <Skeleton className="h-2.5 w-3/4" />
                  </div>
                ) : null}
              </div>
            </div>
          ) : (
            <EmptyState
              icon={Database}
              title="No data source loaded"
              description="Upload a .ddsp or .xml package to inspect its schema, sample data availability and diagnostics."
              compact
            />
          )}
        </div>

        <div className="space-y-2">
          <div className="flex items-center justify-between gap-2">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Diagnostics
            </h3>
            {diagnostics.length > 0 ? (
              <div className="flex flex-wrap gap-1">
                {(["error", "warning", "info"] as const).map((severity) => {
                  const count = diagnostics.filter((item) => item.severity === severity).length;
                  if (count === 0) {
                    return null;
                  }
                  return (
                    <Badge key={severity} variant="outline" className="text-[10px]">
                      {SEVERITY_LABEL[severity]} · {count}
                    </Badge>
                  );
                })}
              </div>
            ) : null}
          </div>
          {source ? (
            <DiagnosticList diagnostics={diagnostics} />
          ) : (
            <div className="rounded-lg border border-dashed border-border bg-muted/10 p-4 text-xs leading-5 text-muted-foreground">
              <Alert variant="info" className="border-none bg-transparent p-0 [&>svg]:mt-0.5">
                <Database aria-hidden="true" />
                <AlertTitle className="text-xs">Parser diagnostics appear here</AlertTitle>
                <AlertDescription className="text-xs">
                  Errors, warnings and informational findings are coloured by severity. Upload a
                  source to see the parser evidence.
                </AlertDescription>
              </Alert>
            </div>
          )}
          {source && !schemaPending ? (
            <p className="text-[11px] leading-5 text-muted-foreground">
              {diagnostics.some((item) => item.severity === "error")
                ? "Errors above mean the parsed schema is incomplete. Review them before planning."
                : "A clean parse is the first step; validation later checks every field binding."}
            </p>
          ) : null}
        </div>
      </div>
    </Panel>
  );
}
