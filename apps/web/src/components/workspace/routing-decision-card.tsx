"use client";

import { CheckCircle2, Route, ShieldCheck } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { CopyButton } from "@/components/workspace/copy-button";
import { formatTraceTimestamp, formatUsd, humanizeKey } from "@/lib/format";
import type { Complexity, RoutingExecutionTrace } from "@/lib/types";
import { cn } from "@/lib/utils";

type ComplexityVariant = "success" | "info" | "warning" | "destructive";

const COMPLEXITY_VARIANT: Record<Complexity, ComplexityVariant> = {
  simple: "success",
  standard: "info",
  complex: "warning",
  ambiguous: "destructive",
};

export interface RoutingDecisionCardProps {
  trace: RoutingExecutionTrace;
  className?: string;
}

/**
 * The authoritative result of an auto-routed plan: what the router
 * recommended, what actually ran, and the identifiers needed to find the
 * sanitized server-side trace.
 */
export function RoutingDecisionCard({ trace, className }: RoutingDecisionCardProps) {
  const { decision } = trace;
  const reason =
    decision.reason.length > 0
      ? decision.reason.join(" ")
      : "No reason was recorded by the router.";

  return (
    <section
      aria-labelledby="routing-decision-title"
      className={cn(
        "animate-fade-in rounded-lg border border-border bg-card p-3 shadow-sm",
        className,
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        <h3
          id="routing-decision-title"
          className="inline-flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground"
        >
          <Route aria-hidden="true" className="h-3.5 w-3.5" />
          Routing decision
        </h3>
        <Badge
          variant={COMPLEXITY_VARIANT[decision.complexity]}
          title={`Brief classified as ${decision.complexity}`}
        >
          {humanizeKey(decision.complexity)}
        </Badge>
        {decision.requires_review ? (
          <Badge variant="warning" title="A human must review this plan before it is trusted">
            <ShieldCheck aria-hidden="true" className="h-3 w-3" />
            requires review
          </Badge>
        ) : null}
        {decision.fallback_used ? (
          <Badge variant="outline" title="The preferred tier had no configured provider">
            router fallback
          </Badge>
        ) : null}
      </div>

      <p
        role="status"
        aria-live="polite"
        aria-atomic="true"
        className="mt-1.5 text-xs font-medium text-foreground"
      >
        Auto selected {trace.actual_provider}
        {" · "}
        <span className="font-mono">{trace.actual_model ?? "provider default"}</span>
      </p>

      <dl className="mt-2 grid gap-x-4 gap-y-1 text-[11px] sm:grid-cols-2">
        <div className="flex min-w-0 items-baseline gap-1.5">
          <dt className="shrink-0 text-muted-foreground">Recommended</dt>
          <dd className="min-w-0 truncate font-medium text-foreground">
            {decision.provider} · {decision.model ?? "provider default"}
          </dd>
        </div>
        <div className="flex min-w-0 items-baseline gap-1.5">
          <dt className="shrink-0 text-muted-foreground">Budget</dt>
          <dd className="font-medium text-foreground">{formatUsd(decision.budget_usd)}</dd>
        </div>
        <div className="flex min-w-0 items-baseline gap-1.5">
          <dt className="shrink-0 text-muted-foreground">Executed</dt>
          <dd className="min-w-0 truncate font-medium text-foreground">
            {trace.actual_provider} · {trace.actual_model ?? "provider default"}
          </dd>
        </div>
        <div className="flex min-w-0 items-center gap-1.5">
          <dt className="shrink-0 text-muted-foreground">Result</dt>
          <dd>
            <Badge variant={trace.match ? "success" : "warning"}>
              {trace.match ? (
                <CheckCircle2 aria-hidden="true" className="h-3 w-3" />
              ) : null}
              {trace.match ? "Router match" : "Fallback / override"}
            </Badge>
          </dd>
        </div>
      </dl>

      {!trace.match ? (
        <p className="mt-1.5 text-[11px] leading-4 text-muted-foreground">
          Fallback: {trace.fallback ? "yes" : "no"} · Reason: {reason}
        </p>
      ) : null}

      {decision.reason.length > 0 ? (
        <ul
          aria-label="Routing reasons"
          className="mt-1.5 list-disc space-y-0.5 pl-4 text-[11px] leading-4 text-muted-foreground"
        >
          {decision.reason.map((item, index) => (
            <li key={`${item}-${index}`}>{item}</li>
          ))}
        </ul>
      ) : null}

      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-border pt-2 text-[11px] text-muted-foreground">
        <span className="inline-flex min-w-0 items-center gap-1">
          Run
          <code className="truncate font-mono text-foreground">{trace.run_id}</code>
          <CopyButton value={trace.run_id} label="Copy run ID" />
        </span>
        <span className="inline-flex items-center gap-1">
          Started{" "}
          <time dateTime={trace.started_at} className="font-mono">
            {formatTraceTimestamp(trace.started_at)}
          </time>
        </span>
        <span className="inline-flex items-center gap-1">
          Finished{" "}
          <time dateTime={trace.finished_at} className="font-mono">
            {formatTraceTimestamp(trace.finished_at)}
          </time>
        </span>
      </div>
    </section>
  );
}
