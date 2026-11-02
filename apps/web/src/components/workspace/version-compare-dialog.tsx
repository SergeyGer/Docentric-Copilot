"use client";

import { useMemo } from "react";
import { History, Loader2, RotateCcw } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorAlert } from "@/components/workspace/error-alert";
import type { ComparePreviewState, CompareVersions } from "@/hooks/use-workspace";
import { formatNumber, pluralize } from "@/lib/format";
import type { RevisionChange, RevisionResponse } from "@/lib/types";
import { cn } from "@/lib/utils";

const CHANGE_GROUPS: ReadonlyArray<{
  kind: RevisionChange["kind"];
  label: string;
  variant: "success" | "destructive" | "warning";
}> = [
  { kind: "added", label: "Added", variant: "success" },
  { kind: "removed", label: "Removed", variant: "destructive" },
  { kind: "changed", label: "Changed", variant: "warning" },
];

export interface VersionCompareDialogProps {
  open: boolean;
  versions: CompareVersions;
  revision: RevisionResponse | null;
  activeVersion: number | null;
  loadingVersion: number | null;
  previews: Record<number, ComparePreviewState>;
  onClose: () => void;
  onRetry: () => void;
  onRestore: (version: number) => void;
}

function ComparePane({
  version,
  label,
  preview,
  isActive,
  loadingVersion,
  onRestore,
  onRetry,
}: {
  version: number;
  label: string;
  preview: ComparePreviewState | undefined;
  isActive: boolean;
  loadingVersion: number | null;
  onRestore: (version: number) => void;
  onRetry: () => void;
}) {
  const pending = preview?.pending ?? true;
  const html = preview?.html ?? null;
  const error = preview?.error ?? null;
  const restoring = loadingVersion === version;

  return (
    <section
      aria-label={`Preview of version ${version} (${label})`}
      className={cn(
        "flex min-w-0 flex-col overflow-hidden rounded-lg border",
        isActive ? "border-primary/40 ring-1 ring-inset ring-primary/20" : "border-border",
      )}
    >
      <header className="flex flex-wrap items-center justify-between gap-2 border-b bg-muted/25 px-3 py-2">
        <div className="flex min-w-0 items-center gap-1.5">
          <Badge variant={isActive ? "default" : "outline"} className="font-mono">
            v{version}
          </Badge>
          <span className="text-[11px] text-muted-foreground">{label}</span>
          {isActive ? <Badge variant="success">Active</Badge> : null}
        </div>
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={() => onRestore(version)}
          disabled={isActive || loadingVersion !== null}
          aria-busy={restoring}
          aria-label={`Restore version ${version} into the workspace`}
        >
          {restoring ? (
            <Loader2 aria-hidden="true" className="animate-spin" />
          ) : (
            <RotateCcw aria-hidden="true" />
          )}
          {restoring ? "Restoring…" : "Restore version"}
        </Button>
      </header>

      <div className="relative min-h-[320px] bg-white">
        {error ? (
          <div className="p-3">
            <ErrorAlert
              error={error}
              title={`Version ${version} preview failed`}
              action={
                <Button type="button" size="sm" variant="outline" onClick={onRetry}>
                  <RotateCcw aria-hidden="true" />
                  Retry preview
                </Button>
              }
            />
          </div>
        ) : html ? (
          <>
            <iframe
              title={`Sandboxed HTML preview of version ${version}`}
              srcDoc={html}
              sandbox="allow-same-origin"
              className="h-[360px] w-full border-0 bg-white"
            />
            {pending ? (
              <div
                role="status"
                aria-live="polite"
                className="absolute inset-x-0 top-0 flex items-center justify-center gap-2 border-b bg-card/95 py-1.5 text-[11px] text-muted-foreground backdrop-blur"
              >
                <Loader2 aria-hidden="true" className="h-3 w-3 animate-spin" />
                Refreshing preview…
              </div>
            ) : null}
          </>
        ) : (
          <div className="space-y-2 p-3" role="status" aria-live="polite">
            <span className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
              <Loader2 aria-hidden="true" className="h-3.5 w-3.5 animate-spin" />
              Rendering version {version}…
            </span>
            <Skeleton className="h-[320px] w-full" />
          </div>
        )}
      </div>
    </section>
  );
}

export function VersionCompareDialog({
  open,
  versions,
  revision,
  activeVersion,
  loadingVersion,
  previews,
  onClose,
  onRetry,
  onRestore,
}: VersionCompareDialogProps) {
  const groups = useMemo(() => {
    const result: Record<RevisionChange["kind"], RevisionChange[]> = {
      added: [],
      removed: [],
      changed: [],
    };
    for (const change of revision?.changes ?? []) {
      result[change.kind].push(change);
    }
    return result;
  }, [revision]);

  const summary = revision?.change_summary ?? null;
  const total = summary?.total ?? revision?.changes.length ?? 0;
  const panes = [
    { version: versions.left, label: "Previous version" },
    { version: versions.right, label: "New version" },
  ];

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`Compare versions · v${versions.left} → v${versions.right}`}
      description="Left is the previous version and right is the new version. Both previews come from immutable IR versions; restoring either one loads it into the workspace."
      className="max-w-6xl"
      bodyClassName="space-y-4"
    >
      <div className="grid gap-2 sm:grid-cols-4">
        {[
          { label: "Total changes", value: total, tone: "text-foreground" },
          { label: "Added", value: summary?.counts.added ?? groups.added.length, tone: "text-success" },
          {
            label: "Removed",
            value: summary?.counts.removed ?? groups.removed.length,
            tone: "text-destructive",
          },
          {
            label: "Changed",
            value: summary?.counts.changed ?? groups.changed.length,
            tone: "text-warning",
          },
        ].map((item) => (
          <div key={item.label} className="rounded-md border bg-muted/20 px-3 py-2">
            <p className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
              {item.label}
            </p>
            <p className={cn("mt-0.5 font-mono text-lg font-semibold leading-6", item.tone)}>
              {formatNumber(item.value)}
            </p>
          </div>
        ))}
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        {panes.map((pane) => (
          <ComparePane
            key={`${pane.label}-${pane.version}`}
            version={pane.version}
            label={pane.label}
            preview={previews[pane.version]}
            isActive={activeVersion === pane.version}
            loadingVersion={loadingVersion}
            onRestore={onRestore}
            onRetry={onRetry}
          />
        ))}
      </div>

      <section aria-labelledby="compare-diff-heading">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3
            id="compare-diff-heading"
            className="flex items-center gap-1.5 text-xs font-semibold text-foreground"
          >
            <History aria-hidden="true" className="h-3.5 w-3.5" />
            Structural change summary
          </h3>
          <p className="text-[10px] text-muted-foreground">
            {formatNumber(revision?.changes.length ?? 0)}{" "}
            {pluralize(revision?.changes.length ?? 0, "change")} reported
          </p>
        </div>
        <div className="mt-2 grid gap-2 sm:grid-cols-3">
          {CHANGE_GROUPS.map((group) => {
            const changes = groups[group.kind];
            return (
              <div key={group.kind} className="rounded-md border bg-card">
                <div className="flex items-center justify-between gap-2 border-b px-2.5 py-1.5">
                  <Badge variant={group.variant} className="text-[10px]">
                    {group.label}
                  </Badge>
                  <span className="font-mono text-[10px] text-muted-foreground">
                    {formatNumber(changes.length)}
                  </span>
                </div>
                {changes.length === 0 ? (
                  <p className="px-2.5 py-2 text-[11px] text-muted-foreground">
                    No {group.label.toLowerCase()} paths.
                  </p>
                ) : (
                  <ul className="scroll-area max-h-44 space-y-1 overflow-y-auto p-2">
                    {changes.map((change, index) => (
                      <li key={`${group.kind}-${change.path}-${index}`}>
                        <code className="break-all font-mono text-[10px] leading-4 text-foreground">
                          {change.path || "(document root)"}
                        </code>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            );
          })}
        </div>
      </section>

      <p className="text-[11px] leading-5 text-muted-foreground">
        Restoring a version replaces the IR, mapping, validation and preview panes. The compare
        panes stay pinned to v{versions.left} and v{versions.right}; the active version is marked.
      </p>
    </Modal>
  );
}
