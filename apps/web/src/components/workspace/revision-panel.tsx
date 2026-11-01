"use client";

import {
  ArrowRight,
  CheckCircle2,
  GitCommitHorizontal,
  GitPullRequest,
  History,
  Loader2,
  RefreshCw,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { EmptyState } from "@/components/workspace/empty-state";
import { ErrorAlert } from "@/components/workspace/error-alert";
import { Panel } from "@/components/workspace/panel";
import type { ApiError } from "@/lib/api";
import { INSTRUCTION_MAX_LENGTH, PANEL_IDS } from "@/lib/constants";
import {
  formatDateTime,
  formatJsonValue,
  formatNumber,
  pluralize,
} from "@/lib/format";
import type {
  RevisionChange,
  RevisionResponse,
  VersionSummary,
} from "@/lib/types";
import { cn } from "@/lib/utils";

const EXAMPLE_INSTRUCTION = "Move the bank details into the footer.";

const CHANGE_STYLE: Record<
  RevisionChange["kind"],
  { variant: "success" | "destructive" | "warning"; label: string }
> = {
  added: { variant: "success", label: "added" },
  removed: { variant: "destructive", label: "removed" },
  changed: { variant: "warning", label: "changed" },
};

interface VersionListProps {
  versions: VersionSummary[];
  versionsPending: boolean;
  versionsError: ApiError | null;
  loadVersionError: ApiError | null;
  loadingVersion: number | null;
  activeVersion: number | null;
  templateId: string | null;
  onLoadVersion: (version: number) => void;
  onRefresh: () => void;
  onDismissVersionsError: () => void;
  onDismissLoadVersionError: () => void;
}

function VersionList({
  versions,
  versionsPending,
  versionsError,
  loadVersionError,
  loadingVersion,
  activeVersion,
  templateId,
  onLoadVersion,
  onRefresh,
  onDismissVersionsError,
  onDismissLoadVersionError,
}: VersionListProps) {
  return (
    <div className="min-w-0">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <h3 className="text-xs font-semibold text-foreground">Version history</h3>
          {versions.length > 0 ? (
            <Badge variant="outline">
              {formatNumber(versions.length)} {pluralize(versions.length, "version")}
            </Badge>
          ) : null}
        </div>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={onRefresh}
          disabled={!templateId || versionsPending}
          aria-busy={versionsPending}
        >
          {versionsPending ? (
            <Loader2 aria-hidden="true" className="animate-spin" />
          ) : (
            <RefreshCw aria-hidden="true" />
          )}
          Refresh
        </Button>
      </div>

      {versionsError ? (
        <ErrorAlert
          error={versionsError}
          title="Version history unavailable"
          className="mt-2"
          onDismiss={onDismissVersionsError}
          action={
            <Button type="button" size="sm" variant="outline" onClick={onRefresh}>
              <RefreshCw aria-hidden="true" />
              Retry
            </Button>
          }
        />
      ) : null}
      {loadVersionError ? (
        <ErrorAlert
          error={loadVersionError}
          title="Could not load version"
          className="mt-2"
          onDismiss={onDismissLoadVersionError}
        />
      ) : null}

      {versionsPending && versions.length === 0 ? (
        <div className="mt-3 space-y-2" role="status" aria-live="polite">
          <span className="text-[11px] text-muted-foreground">Loading versions…</span>
          {Array.from({ length: 2 }).map((_, index) => (
            <Skeleton key={index} className="h-16 w-full" />
          ))}
        </div>
      ) : versions.length === 0 ? (
        <EmptyState
          icon={History}
          title="No versions yet"
          description="Version 1 appears after a successful plan. Each revision appends an immutable version."
          compact
          className="mt-2"
        />
      ) : (
        <ScrollArea className="mt-2 max-h-[380px] pr-1">
          <ul className="space-y-2">
            {versions.map((version) => {
              const active = version.version === activeVersion;
              const isLoading = loadingVersion === version.version;
              return (
                <li
                  key={version.version}
                  aria-current={active ? "true" : undefined}
                  className={cn(
                    "rounded-lg border p-3 transition-colors",
                    active
                      ? "border-primary/40 bg-primary/5 ring-1 ring-inset ring-primary/20"
                      : "border-border bg-card hover:border-primary/25",
                  )}
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <Badge variant={active ? "default" : "outline"} className="font-mono">
                        v{version.version}
                      </Badge>
                      {active ? <Badge variant="success">Active</Badge> : null}
                    </div>
                    {active ? (
                      <CheckCircle2 aria-hidden="true" className="h-4 w-4 text-primary" />
                    ) : (
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        onClick={() => onLoadVersion(version.version)}
                        disabled={loadingVersion !== null}
                        aria-busy={isLoading}
                      >
                        {isLoading ? (
                          <Loader2 aria-hidden="true" className="animate-spin" />
                        ) : (
                          <History aria-hidden="true" />
                        )}
                        {isLoading ? "Loading…" : "Load"}
                      </Button>
                    )}
                  </div>
                  <p className="mt-1.5 text-[11px] text-muted-foreground">
                    {formatDateTime(version.created_at)}
                  </p>
                  <p className="mt-0.5 break-all font-mono text-[10px] text-muted-foreground">
                    {version.provider ?? "mock"}
                    {version.model ? ` · ${version.model}` : ""}
                  </p>
                </li>
              );
            })}
          </ul>
        </ScrollArea>
      )}

      <p className="mt-2 text-[10px] leading-4 text-muted-foreground">
        Loading a version replaces the IR, mapping and validation panes. Compile again to download
        that version.
      </p>
    </div>
  );
}

export interface RevisionPanelProps {
  templateId: string | null;
  activeVersion: number | null;
  provider: string;
  model: string;
  instruction: string;
  onInstructionChange: (value: string) => void;
  revisionPending: boolean;
  revisionError: ApiError | null;
  revision: RevisionResponse | null;
  versions: VersionSummary[];
  versionsPending: boolean;
  versionsError: ApiError | null;
  loadingVersion: number | null;
  loadVersionError: ApiError | null;
  onApplyRevision: () => void;
  onRefreshVersions: () => void;
  onLoadVersion: (version: number) => void;
  onDismissRevisionError: () => void;
  onDismissVersionsError: () => void;
  onDismissLoadVersionError: () => void;
}

export function RevisionPanel({
  templateId,
  activeVersion,
  provider,
  model,
  instruction,
  onInstructionChange,
  revisionPending,
  revisionError,
  revision,
  versions,
  versionsPending,
  versionsError,
  loadingVersion,
  loadVersionError,
  onApplyRevision,
  onRefreshVersions,
  onLoadVersion,
  onDismissRevisionError,
  onDismissVersionsError,
  onDismissLoadVersionError,
}: RevisionPanelProps) {
  const summary = revision?.change_summary ?? null;
  const canApply =
    Boolean(templateId) && !revisionPending && instruction.trim().length >= 3;

  return (
    <Panel
      id={PANEL_IDS.revision}
      step={8}
      title="Revision"
      description="Request a natural-language change. Revisions produce a new immutable IR version; the change summary is a structural diff, not a model claim."
      actions={
        activeVersion !== null ? (
          <Badge variant="outline" className="font-mono">
            active v{activeVersion}
          </Badge>
        ) : null
      }
    >
      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
        <div className="min-w-0 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <label htmlFor="revision-instruction" className="text-xs font-medium text-foreground">
              Requested change
            </label>
            <div className="flex items-center gap-2">
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => onInstructionChange(EXAMPLE_INSTRUCTION)}
                disabled={revisionPending}
              >
                Use example
              </Button>
              <span className="font-mono text-[11px] text-muted-foreground">
                {instruction.length}/{INSTRUCTION_MAX_LENGTH}
              </span>
            </div>
          </div>
          <Textarea
            id="revision-instruction"
            value={instruction}
            onChange={(event) => onInstructionChange(event.target.value)}
            rows={3}
            maxLength={INSTRUCTION_MAX_LENGTH}
            disabled={revisionPending}
            placeholder="Move the bank details into the footer"
            aria-describedby="revision-hint"
          />
          <p id="revision-hint" className="text-xs leading-5 text-muted-foreground">
            For example: &ldquo;move bank details to the footer&rdquo; or &ldquo;add a
            currency column to the line-item table&rdquo;. Uses {provider}
            {model ? ` / ${model}` : ""}.
          </p>

          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="button"
              onClick={onApplyRevision}
              disabled={!canApply}
              aria-busy={revisionPending}
            >
              {revisionPending ? (
                <Loader2 aria-hidden="true" className="animate-spin" />
              ) : (
                <GitPullRequest aria-hidden="true" />
              )}
              {revisionPending ? "Applying revision…" : "Apply revision"}
            </Button>
            {!templateId ? (
              <p className="text-[11px] text-muted-foreground">
                Plan a template before requesting a revision.
              </p>
            ) : revisionPending ? (
              <p
                role="status"
                aria-live="polite"
                className="flex items-center gap-1.5 text-[11px] text-muted-foreground"
              >
                <Loader2 aria-hidden="true" className="h-3.5 w-3.5 animate-spin" />
                Creating and validating a new version…
              </p>
            ) : null}
          </div>

          {revisionError ? (
            <ErrorAlert
              error={revisionError}
              title="Revision failed"
              onDismiss={onDismissRevisionError}
            />
          ) : null}

          {revision && summary ? (
            <div className="rounded-lg border">
              <div className="flex flex-wrap items-center justify-between gap-2 border-b px-3 py-2.5">
                <div className="flex items-center gap-2">
                  <h3 className="text-xs font-semibold text-foreground">Revision applied</h3>
                  <Badge variant="default" className="font-mono">
                    v{revision.version}
                  </Badge>
                </div>
                <p className="font-mono text-[10px] text-muted-foreground">
                  job {revision.job_id}
                </p>
              </div>
              <dl className="grid grid-cols-2 gap-px bg-border sm:grid-cols-4">
                {[
                  { key: "total", label: "Total changes", value: summary.total, tone: "" },
                  {
                    key: "added",
                    label: "Added",
                    value: summary.counts.added,
                    tone: "text-success",
                  },
                  {
                    key: "removed",
                    label: "Removed",
                    value: summary.counts.removed,
                    tone: "text-destructive",
                  },
                  {
                    key: "changed",
                    label: "Changed",
                    value: summary.counts.changed,
                    tone: "text-warning",
                  },
                ].map((item) => (
                  <div key={item.key} className="bg-card px-3 py-2.5">
                    <dt className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
                      {item.label}
                    </dt>
                    <dd
                      className={cn(
                        "mt-0.5 font-mono text-lg font-semibold leading-6",
                        item.tone || "text-foreground",
                      )}
                    >
                      {formatNumber(item.value)}
                    </dd>
                  </div>
                ))}
              </dl>

              <Collapsible
                defaultOpen
                className="border-t px-3 py-2.5"
              >
                <CollapsibleTrigger className="text-[11px] text-muted-foreground hover:text-foreground">
                  <span className="inline-flex items-center gap-1.5">
                    <GitCommitHorizontal aria-hidden="true" className="h-3.5 w-3.5" />
                    Structural changes ({revision.changes.length})
                  </span>
                </CollapsibleTrigger>
                <CollapsibleContent>
                  {revision.changes.length === 0 ? (
                    <p className="text-[11px] text-muted-foreground">
                      The revision produced no structural changes.
                    </p>
                  ) : (
                    <ScrollArea className="max-h-64 pr-1">
                      <ul className="space-y-1.5">
                        {revision.changes.map((change, index) => {
                          const style = CHANGE_STYLE[change.kind];
                          return (
                            <li
                              key={`${change.path}-${index}`}
                              className="rounded-md border bg-muted/15 px-2 py-1.5"
                            >
                              <div className="flex flex-wrap items-center gap-1.5">
                                <Badge variant={style.variant} className="text-[10px]">
                                  {style.label}
                                </Badge>
                                <code className="break-all font-mono text-[10px] text-foreground">
                                  {change.path || "(document root)"}
                                </code>
                              </div>
                              <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[10px] leading-4">
                                <span className="break-all text-muted-foreground">
                                  {formatJsonValue(change.before, 180)}
                                </span>
                                <ArrowRight
                                  aria-hidden="true"
                                  className="h-3 w-3 shrink-0 text-muted-foreground"
                                />
                                <span className="break-all text-foreground">
                                  {formatJsonValue(change.after, 180)}
                                </span>
                              </div>
                            </li>
                          );
                        })}
                      </ul>
                    </ScrollArea>
                  )}
                </CollapsibleContent>
              </Collapsible>
            </div>
          ) : !revision ? (
            <EmptyState
              icon={GitPullRequest}
              title="No revision yet"
              description="Apply a change to create a new version. The request and the resulting structural diff are both reviewable."
              compact
            />
          ) : null}
        </div>

        <VersionList
          versions={versions}
          versionsPending={versionsPending}
          versionsError={versionsError}
          loadVersionError={loadVersionError}
          loadingVersion={loadingVersion}
          activeVersion={activeVersion}
          templateId={templateId}
          onLoadVersion={onLoadVersion}
          onRefresh={onRefreshVersions}
          onDismissVersionsError={onDismissVersionsError}
          onDismissLoadVersionError={onDismissLoadVersionError}
        />
      </div>
    </Panel>
  );
}
