"use client";

import {
  ExternalLink,
  Loader2,
  MonitorPlay,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/workspace/empty-state";
import { ErrorAlert } from "@/components/workspace/error-alert";
import { Panel } from "@/components/workspace/panel";
import { apiUrl, type ApiError } from "@/lib/api";
import { PANEL_IDS } from "@/lib/constants";
import { formatNumber } from "@/lib/format";
import type { ArtifactView } from "@/lib/types";
import { cn } from "@/lib/utils";

export interface PreviewPanelProps {
  previewHtml: string | null;
  previewVersion: number | null;
  activeVersion: number | null;
  previewPending: boolean;
  previewError: ApiError | null;
  templateId: string | null;
  previewArtifact: ArtifactView | null;
  onRefresh: () => void;
  onDismissError: () => void;
}

export function PreviewPanel({
  previewHtml,
  previewVersion,
  activeVersion,
  previewPending,
  previewError,
  templateId,
  previewArtifact,
  onRefresh,
  onDismissError,
}: PreviewPanelProps) {
  const stale =
    previewHtml !== null &&
    previewVersion !== null &&
    activeVersion !== null &&
    previewVersion !== activeVersion;

  return (
    <Panel
      id={PANEL_IDS.preview}
      step={6}
      title="Preview"
      description="Independent HTML rendering from the API, displayed inside a sandboxed frame. Refresh after planning, revising or loading a version."
      actions={
        <>
          {previewArtifact ? (
            <a
              href={apiUrl(`${previewArtifact.url}/view`)}
              target="_blank"
              rel="noopener noreferrer"
              className={cn(buttonVariants({ variant: "ghost", size: "sm" }))}
            >
              <ExternalLink aria-hidden="true" />
              Open artifact
            </a>
          ) : null}
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={onRefresh}
            disabled={!templateId || previewPending}
            aria-busy={previewPending}
          >
            {previewPending ? (
              <Loader2 aria-hidden="true" className="animate-spin" />
            ) : (
              <RefreshCw aria-hidden="true" />
            )}
            {previewPending ? "Rendering…" : "Refresh"}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        {previewError ? (
          <ErrorAlert
            error={previewError}
            title="Preview failed"
            onDismiss={onDismissError}
            action={
              <Button type="button" size="sm" variant="outline" onClick={onRefresh}>
                <RefreshCw aria-hidden="true" />
                Retry preview
              </Button>
            }
          />
        ) : null}

        {stale ? (
          <Alert variant="warning">
            <AlertTitle>Preview is stale</AlertTitle>
            <AlertDescription>
              It shows version {previewVersion}, while version {activeVersion} is active. Refresh to
              render the current version.
            </AlertDescription>
          </Alert>
        ) : null}

        {!previewHtml && previewPending ? (
          <div
            role="status"
            aria-live="polite"
            className="relative h-[560px] overflow-hidden rounded-lg border bg-muted/20"
          >
            <Skeleton className="h-full w-full rounded-none" />
            <span className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-card/60 text-xs text-muted-foreground backdrop-blur-[1px]">
              <Loader2 aria-hidden="true" className="h-5 w-5 animate-spin text-primary" />
              Rendering the HTML preview…
            </span>
          </div>
        ) : previewHtml ? (
          <div className="relative overflow-hidden rounded-lg border bg-white shadow-inner">
            {previewPending ? (
              <div
                role="status"
                aria-live="polite"
                className="absolute inset-x-0 top-0 z-10 flex items-center justify-center gap-2 border-b bg-card/95 py-1.5 text-[11px] text-muted-foreground backdrop-blur"
              >
                <Loader2 aria-hidden="true" className="h-3 w-3 animate-spin" />
                Refreshing preview…
              </div>
            ) : null}
            <iframe
              key={previewVersion ?? "preview"}
              title="Sandboxed HTML preview of the planned template"
              srcDoc={previewHtml}
              sandbox=""
              className="h-[560px] w-full border-0 bg-white"
            />
          </div>
        ) : (
          <EmptyState
            icon={MonitorPlay}
            title="No preview rendered"
            description="Plan a template or press Refresh to render the HTML preview. The preview is generated by the API from the active Template IR."
            className="min-h-[260px]"
          />
        )}

        <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] text-muted-foreground">
          <p className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <span className="inline-flex items-center gap-1">
              <ShieldCheck aria-hidden="true" className="h-3.5 w-3.5 text-success" />
              Sandboxed iframe · scripts disabled
            </span>
            {previewVersion !== null ? (
              <Badge variant="outline" className="font-mono text-[10px]">
                rendered v{previewVersion}
              </Badge>
            ) : null}
            {previewHtml ? (
              <span className="font-mono">
                {formatNumber(previewHtml.length)} chars
              </span>
            ) : null}
          </p>
          <p>HTML is never injected into this page directly.</p>
        </div>
      </div>
    </Panel>
  );
}
