"use client";

import { useCallback, useEffect, useRef } from "react";
import type { SyntheticEvent } from "react";
import {
  ExternalLink,
  Loader2,
  MonitorPlay,
  MousePointerClick,
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
  /** Absolute schema path hovered inside the preview. */
  activePath: string | null;
  onActivePathChange: (path: string | null) => void;
  /** A preview value was clicked: reveal its mapping row. */
  onPathClick: (path: string) => void;
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
  activePath,
  onActivePathChange,
  onPathClick,
  onRefresh,
  onDismissError,
}: PreviewPanelProps) {
  const cleanupRef = useRef<(() => void) | null>(null);

  const cleanupReveal = useCallback(() => {
    cleanupRef.current?.();
    cleanupRef.current = null;
  }, []);

  useEffect(() => cleanupReveal, [cleanupReveal]);

  /**
   * The preview document is sandboxed with `allow-same-origin` only, so it
   * cannot run scripts, but the parent can still attach plain DOM listeners.
   * Every rendered value carries `data-path` with its absolute schema path.
   */
  const attachBindingReveal = (event: SyntheticEvent<HTMLIFrameElement>) => {
    cleanupReveal();
    onActivePathChange(null);
    let documentRef: Document | null = null;
    try {
      documentRef = event.currentTarget.contentDocument;
    } catch {
      documentRef = null;
    }
    if (!documentRef) {
      return;
    }
    const previewDocument = documentRef;
    const elements = Array.from(previewDocument.querySelectorAll<HTMLElement>("[data-path]"));
    const cleanups: Array<() => void> = [];

    for (const element of elements) {
      const path = element.getAttribute("data-path");
      if (!path) {
        continue;
      }
      element.tabIndex = 0;
      element.setAttribute("role", "button");
      element.setAttribute(
        "aria-label",
        `Schema field ${path}. Press Enter to reveal it in the mapping review.`,
      );

      const activate = () => {
        element.classList.add("is-active");
        onActivePathChange(path);
      };
      const deactivate = () => {
        element.classList.remove("is-active");
        onActivePathChange(null);
      };
      const handleClick = (clickEvent: MouseEvent) => {
        clickEvent.preventDefault();
        onPathClick(path);
      };
      const handleKeyDown = (keyEvent: KeyboardEvent) => {
        if (keyEvent.key === "Enter" || keyEvent.key === " ") {
          keyEvent.preventDefault();
          onPathClick(path);
          activate();
        }
      };

      element.addEventListener("mouseenter", activate);
      element.addEventListener("mouseleave", deactivate);
      element.addEventListener("focus", activate);
      element.addEventListener("blur", deactivate);
      element.addEventListener("click", handleClick);
      element.addEventListener("keydown", handleKeyDown);
      cleanups.push(() => {
        element.classList.remove("is-active");
        element.removeEventListener("mouseenter", activate);
        element.removeEventListener("mouseleave", deactivate);
        element.removeEventListener("focus", activate);
        element.removeEventListener("blur", deactivate);
        element.removeEventListener("click", handleClick);
        element.removeEventListener("keydown", handleKeyDown);
      });
    }

    // Leaving the iframe entirely may not fire an element-level mouseleave.
    const clearAll = () => {
      for (const element of elements) {
        element.classList.remove("is-active");
      }
      onActivePathChange(null);
    };
    previewDocument.addEventListener("mouseleave", clearAll);
    cleanupRef.current = () => {
      previewDocument.removeEventListener("mouseleave", clearAll);
      for (const cleanup of cleanups) {
        cleanup();
      }
    };
  };

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
      description="Independent HTML rendering from the API inside a script-free, same-origin sandbox. Hover a value to reveal its schema field; click it to jump to the mapping row."
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
              title={`Sandboxed HTML preview of version ${previewVersion ?? "—"}`}
              srcDoc={previewHtml}
              sandbox="allow-same-origin"
              onLoad={attachBindingReveal}
              className="h-[560px] w-full border-0 bg-white"
            />
          </div>
        ) : (
          <EmptyState
            icon={MonitorPlay}
            title="No preview rendered"
            description="Plan a template, run the demo or press Refresh to render the HTML preview. The preview is generated by the API from the active Template IR."
            className="min-h-[260px]"
          />
        )}

        {activePath ? (
          <p
            className="flex min-w-0 items-center gap-1.5 rounded-md border border-info/30 bg-info/5 px-2 py-1 text-[11px] text-info"
            aria-live="polite"
          >
            <MousePointerClick aria-hidden="true" className="h-3.5 w-3.5 shrink-0" />
            <span className="shrink-0">Preview field:</span>
            <span className="truncate font-mono" title={activePath}>
              {activePath}
            </span>
          </p>
        ) : (
          <p className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
            <MousePointerClick aria-hidden="true" className="h-3.5 w-3.5" />
            Hover or focus a value in the preview to inspect its schema binding.
          </p>
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
              <span className="font-mono">{formatNumber(previewHtml.length)} chars</span>
            ) : null}
          </p>
          <p>HTML is never injected into this page directly.</p>
        </div>
      </div>
    </Panel>
  );
}
