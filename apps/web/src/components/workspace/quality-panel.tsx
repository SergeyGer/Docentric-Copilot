"use client";

import {
  AlertTriangle,
  CheckCircle2,
  Gauge,
  Info,
  Loader2,
  RefreshCw,
  Wand2,
  XCircle,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/workspace/empty-state";
import { ErrorAlert } from "@/components/workspace/error-alert";
import { Panel } from "@/components/workspace/panel";
import type { QualityOptimizationResult } from "@/hooks/use-workspace";
import type { ApiError } from "@/lib/api";
import { PANEL_IDS } from "@/lib/constants";
import { formatNumber } from "@/lib/format";
import { QUALITY_STATUSES, countQualityChecks, qualityStatusLabel } from "@/lib/quality";
import type { QualityReport, QualityStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

const QUALITY_STYLE: Record<
  QualityStatus,
  { variant: "success" | "warning" | "destructive"; icon: typeof CheckCircle2; tile: string }
> = {
  passed: {
    variant: "success",
    icon: CheckCircle2,
    tile: "border-success/25 bg-success/5",
  },
  warning: {
    variant: "warning",
    icon: AlertTriangle,
    tile: "border-warning/30 bg-warning/5",
  },
  failed: {
    variant: "destructive",
    icon: XCircle,
    tile: "border-destructive/30 bg-destructive/5",
  },
};

function QualityStatusBadge({ status }: { status: QualityStatus }) {
  const style = QUALITY_STYLE[status];
  const Icon = style.icon;
  return (
    <Badge variant={style.variant}>
      <Icon aria-hidden="true" className="h-3 w-3" />
      {qualityStatusLabel(status)}
    </Badge>
  );
}

export interface QualityPanelProps {
  quality: QualityReport | null;
  qualityPending: boolean;
  qualityError: ApiError | null;
  qualityOptimization: QualityOptimizationResult | null;
  qualityNotice: string | null;
  optimizing: boolean;
  templateId: string | null;
  activeVersion: number | null;
  canAnalyse: boolean;
  canOptimize: boolean;
  onRefresh: () => void;
  onOptimize: () => void;
  onDismissError: () => void;
}

export function QualityPanel({
  quality,
  qualityPending,
  qualityError,
  qualityOptimization,
  qualityNotice,
  optimizing,
  templateId,
  activeVersion,
  canAnalyse,
  canOptimize,
  onRefresh,
  onOptimize,
  onDismissError,
}: QualityPanelProps) {
  const counts = countQualityChecks(quality);
  const busy = qualityPending || optimizing;

  return (
    <Panel
      id={PANEL_IDS.quality}
      step={5}
      title="Quality dashboard"
      description="Explainable layout checks on the validated Template IR. Every finding names the IR path it belongs to; optimisation writes a new immutable version."
      actions={
        <>
          {templateId && activeVersion !== null ? (
            <Badge variant="outline" className="font-mono">
              v{activeVersion}
            </Badge>
          ) : null}
          {quality ? <QualityStatusBadge status={quality.overall} /> : null}
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={onRefresh}
            disabled={!canAnalyse || busy}
            aria-busy={qualityPending}
            aria-label="Refresh quality analysis"
            title="Re-run the quality analysis for the active version"
          >
            {qualityPending ? (
              <Loader2 aria-hidden="true" className="animate-spin" />
            ) : (
              <RefreshCw aria-hidden="true" />
            )}
            {qualityPending ? "Refreshing…" : "Refresh"}
          </Button>
          <Button
            type="button"
            size="sm"
            onClick={onOptimize}
            disabled={!canOptimize || busy}
            aria-busy={optimizing}
            title={
              canOptimize
                ? "Apply typed layout fixes and create a new version"
                : "Analyse quality before optimising the layout"
            }
          >
            {optimizing ? (
              <Loader2 aria-hidden="true" className="animate-spin" />
            ) : (
              <Wand2 aria-hidden="true" />
            )}
            {optimizing ? "Optimizing…" : "Optimize layout"}
          </Button>
        </>
      }
    >
      <div className="space-y-4" aria-busy={busy}>
        <p role="status" aria-live="polite" className="text-[11px] leading-5 text-muted-foreground">
          {optimizing
            ? "Optimizing the layout and creating a new version…"
            : qualityPending
              ? "Analysing document quality…"
              : quality
                ? `Quality analysis complete: ${quality.overall}.`
                : "No quality analysis has run yet."}
        </p>

        {qualityError ? (
          <ErrorAlert
            error={qualityError}
            title="Quality request failed"
            onDismiss={onDismissError}
            action={
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={onRefresh}
                disabled={!canAnalyse || busy}
              >
                <RefreshCw aria-hidden="true" />
                Retry analysis
              </Button>
            }
          />
        ) : null}

        {qualityNotice ? (
          <div
            role="status"
            aria-live="polite"
            className="flex items-start gap-2 rounded-md border border-info/30 bg-info/5 px-3 py-2 text-[11px] leading-5 text-foreground"
          >
            <Info aria-hidden="true" className="mt-0.5 h-3.5 w-3.5 shrink-0 text-info" />
            <span>{qualityNotice}</span>
          </div>
        ) : null}

        {qualityOptimization ? (
          <section
            aria-labelledby="quality-optimization-title"
            className="rounded-lg border border-success/25 bg-success/5 p-3"
          >
            <h3
              id="quality-optimization-title"
              className="inline-flex items-center gap-1.5 text-xs font-semibold text-success"
            >
              <CheckCircle2 aria-hidden="true" className="h-3.5 w-3.5" />
              Layout optimized · version {qualityOptimization.version}
            </h3>
            <p className="mt-1 text-[11px] leading-5 text-muted-foreground">
              Before: {qualityOptimization.before.checks.length} checks (
              {countQualityChecks(qualityOptimization.before).passed} passed,{" "}
              {countQualityChecks(qualityOptimization.before).warning} warning,{" "}
              {countQualityChecks(qualityOptimization.before).failed} failed) → After:{" "}
              {qualityOptimization.after.checks.length} checks (
              {countQualityChecks(qualityOptimization.after).passed} passed,{" "}
              {countQualityChecks(qualityOptimization.after).warning} warning,{" "}
              {countQualityChecks(qualityOptimization.after).failed} failed).
            </p>
            <ul className="mt-2 space-y-1">
              {qualityOptimization.fixes.map((fix, index) => (
                <li
                  key={`${fix.id}-${index}`}
                  className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-[11px] leading-5"
                >
                  <code className="rounded bg-card px-1 font-mono text-[10px] text-foreground">
                    {fix.id}
                  </code>
                  <span className="text-foreground">{fix.message}</span>
                  {fix.path ? (
                    <code className="break-all font-mono text-[10px] text-muted-foreground">
                      {fix.path}
                    </code>
                  ) : null}
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        {!quality ? (
          qualityPending ? (
            <p className="flex items-center gap-2 text-xs text-muted-foreground">
              <Loader2 aria-hidden="true" className="h-3.5 w-3.5 animate-spin" />
              Reading the IR and running layout checks…
            </p>
          ) : (
            <div className="space-y-3">
              <EmptyState
                icon={Gauge}
                title="No quality analysis yet"
                description="Plan a template, load a version or run the demo. The dashboard analyses the active IR automatically and can be refreshed at any time."
              />
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={onRefresh}
                disabled={!canAnalyse || busy}
              >
                <Gauge aria-hidden="true" />
                Analyse quality
              </Button>
            </div>
          )
        ) : (
          <>
            <dl className="grid gap-2 sm:grid-cols-3">
              {QUALITY_STATUSES.map((status) => {
                const style = QUALITY_STYLE[status];
                return (
                  <div key={status} className={cn("rounded-lg border p-3", style.tile)}>
                    <dt className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                      {qualityStatusLabel(status)}
                    </dt>
                    <dd className="mt-0.5 font-mono text-lg font-semibold leading-6 text-foreground">
                      {formatNumber(counts[status])}
                    </dd>
                  </div>
                );
              })}
            </dl>

            <p className="text-[11px] leading-5 text-muted-foreground">
              Page {quality.metrics.page} · text width{" "}
              {quality.metrics.text_width_mm.toFixed(1)} mm ·{" "}
              {formatNumber(quality.metrics.tables)} tables ·{" "}
              {formatNumber(quality.metrics.images)} images ·{" "}
              {formatNumber(quality.metrics.blocks)} blocks
            </p>

            <ul
              aria-label="Quality checks"
              className="overflow-hidden rounded-lg border border-border"
            >
              {quality.checks.map((check, index) => (
                <li
                  key={`${check.id}-${index}`}
                  className="border-b border-border p-3 last:border-b-0"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <code className="font-mono text-[10px] text-muted-foreground">{check.id}</code>
                    <span className="text-xs font-medium text-foreground">{check.label}</span>
                    <span className="ml-auto">
                      <QualityStatusBadge status={check.status} />
                    </span>
                  </div>
                  <p className="mt-1 text-[11px] leading-5 text-muted-foreground">
                    {check.message}
                  </p>
                  {check.path ? (
                    <code className="mt-1 block break-all font-mono text-[10px] text-muted-foreground">
                      {check.path}
                    </code>
                  ) : null}
                </li>
              ))}
              {quality.checks.length === 0 ? (
                <li className="px-3 py-4 text-xs text-muted-foreground">
                  The quality report contains no checks.
                </li>
              ) : null}
            </ul>
          </>
        )}
      </div>
    </Panel>
  );
}
