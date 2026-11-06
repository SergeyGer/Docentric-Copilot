"use client";

import { FileSearch, Loader2, RotateCcw } from "lucide-react";

import { ReferenceDropzone } from "@/components/reference/reference-dropzone";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ErrorAlert } from "@/components/workspace/error-alert";
import type { ApiError } from "@/lib/api";
import { REFERENCE_SCHEMA_EXTENSIONS, REFERENCE_TEMPLATE_EXTENSIONS } from "@/lib/reference";
import { cn } from "@/lib/utils";

export interface ReferenceUploadPanelProps {
  file: File | null;
  ddsp: File | null;
  onFileChange: (file: File | null) => void;
  onDdspChange: (file: File | null) => void;
  onInspect: () => void;
  onReset: () => void;
  inspecting: boolean;
  graphPending: boolean;
  limitBytes: number | null;
  error: ApiError | null;
  onDismissError: () => void;
  hasResults: boolean;
  className?: string;
}

/**
 * Upload card for one reference template plus an optional DDSP schema. The
 * inspector never writes or executes the source; it only sends the bytes to the
 * read-only reference endpoints.
 */
export function ReferenceUploadPanel({
  file,
  ddsp,
  onFileChange,
  onDdspChange,
  onInspect,
  onReset,
  inspecting,
  graphPending,
  limitBytes,
  error,
  onDismissError,
  hasResults,
  className,
}: ReferenceUploadPanelProps) {
  const busy = inspecting || graphPending;
  const canInspect = file !== null && !busy;

  return (
    <Card className={cn("animate-fade-in", className)}>
      <CardHeader className="gap-3 pb-3">
        <div className="flex flex-col justify-between gap-2 sm:flex-row sm:items-start">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-1.5">
              <CardTitle id="reference-upload-title" className="text-base">
                Reference source
              </CardTitle>
              <Badge variant="outline">Read-only</Badge>
              <Badge variant="unverified">Runtime not tested</Badge>
            </div>
            <CardDescription className="mt-1 text-[13px]">
              Upload a DOCX, ZIP or AXPP package. Add the matching DDSP schema to validate binding
              paths against its sections. Files are inspected statically and never compiled.
            </CardDescription>
          </div>
          <div className="flex shrink-0 flex-wrap items-center gap-2">
            <Button
              type="button"
              size="sm"
              data-testid="reference-inspect-button"
              onClick={onInspect}
              disabled={!canInspect}
              aria-busy={inspecting}
              aria-describedby="reference-upload-note"
            >
              {inspecting ? (
                <Loader2 aria-hidden="true" className="animate-spin" />
              ) : (
                <FileSearch aria-hidden="true" />
              )}
              {inspecting
                ? "Inspecting…"
                : hasResults
                  ? "Inspect again"
                  : "Inspect reference"}
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={onReset}
              disabled={busy || (!file && !hasResults)}
              aria-label="Clear the selected reference and all results"
            >
              <RotateCcw aria-hidden="true" />
              Clear
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid gap-3 lg:grid-cols-2">
          <ReferenceDropzone
            id="reference-template-file"
            label="Template file"
            description="Docentric Word template or package containing DOCX documents."
            accept={REFERENCE_TEMPLATE_EXTENSIONS.join(",")}
            file={file}
            onFileChange={onFileChange}
            disabled={busy}
            limitBytes={limitBytes}
          />
          <ReferenceDropzone
            id="reference-ddsp-file"
            label="DDSP schema"
            description="Optional XML schema used to check binding paths. Ignored when it does not match the document."
            accept={REFERENCE_SCHEMA_EXTENSIONS.join(",")}
            file={ddsp}
            onFileChange={onDdspChange}
            disabled={busy}
            optional
            limitBytes={limitBytes}
          />
        </div>

        <p id="reference-upload-note" className="text-[11px] leading-5 text-muted-foreground">
          Inspect loads the overview, controls and graph from the same source. Path-based corpus
          access is not exposed here; this UI always uploads a local file.
        </p>

        {graphPending && !inspecting ? (
          <p
            role="status"
            aria-live="polite"
            className="flex items-center gap-2 text-[11px] text-muted-foreground"
          >
            <Loader2 aria-hidden="true" className="h-3 w-3 animate-spin" />
            Building the read-only reference graph…
          </p>
        ) : null}

        {error ? (
          <ErrorAlert
            error={error}
            title="Reference inspection failed"
            onDismiss={onDismissError}
            action={
              file ? (
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={onInspect}
                  disabled={busy}
                >
                  {busy ? <Loader2 aria-hidden="true" className="animate-spin" /> : null}
                  Retry inspection
                </Button>
              ) : null
            }
          />
        ) : null}
      </CardContent>
    </Card>
  );
}
