"use client";

import { useId } from "react";
import { Info, Loader2, Route, ShieldCheck } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { formatUsd, humanizeKey } from "@/lib/format";
import type { Complexity, RouteResponse, RoutingExecutionTrace } from "@/lib/types";

type ComplexityVariant = "success" | "info" | "warning" | "destructive";

const COMPLEXITY_VARIANT: Record<Complexity, ComplexityVariant> = {
  simple: "success",
  standard: "info",
  complex: "warning",
  ambiguous: "destructive",
};

const COMPLEXITY_ORDER: readonly Complexity[] = ["simple", "standard", "complex", "ambiguous"];

export interface RoutingPanelProps {
  routing: RouteResponse | null;
  /** Present after an `auto` plan: what ran versus what was recommended. */
  execution?: RoutingExecutionTrace | null;
  pending: boolean;
  unavailable: boolean;
  /** Routing only runs when a source and a non-empty brief both exist. */
  enabled: boolean;
}

/**
 * Compact, informational routing card. It never blocks the planner: failures
 * collapse to a quiet label and the decision is purely advisory.
 */
export function RoutingPanel({
  routing,
  execution = null,
  pending,
  unavailable,
  enabled,
}: RoutingPanelProps) {
  const tooltipId = useId();

  if (!enabled && !routing && !execution && !pending && !unavailable) {
    return null;
  }

  const decision = routing?.decision ?? execution?.decision ?? null;
  const ariaSummary = pending
    ? "Updating the routing decision."
    : decision
      ? `Routing decision: ${humanizeKey(decision.complexity)} via ${decision.provider}${
          decision.model ? `, ${decision.model}` : ""
        }. Budget ${formatUsd(decision.budget_usd)}.${
          execution
            ? ` Executed with ${execution.actual_provider}${
                execution.actual_model ? `, ${execution.actual_model}` : ""
              }; ${execution.match ? "recommendation matched" : "recommendation did not match"}.`
            : ""
        }`
      : unavailable
        ? "Routing unavailable."
        : "Routing has not run yet.";

  return (
    <section
      aria-labelledby="routing-card-title"
      aria-busy={pending}
      className="rounded-lg border border-border bg-muted/20 px-3 py-2.5"
    >
      <p className="sr-only" role="status" aria-live="polite">
        {ariaSummary}
      </p>

      <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1.5">
        <h3
          id="routing-card-title"
          className="inline-flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground"
        >
          <Route aria-hidden="true" className="h-3.5 w-3.5" />
          Routing
        </h3>

        {decision ? (
          <>
            <Badge
              variant={COMPLEXITY_VARIANT[decision.complexity]}
              title={`Classified as ${decision.complexity}`}
            >
              {humanizeKey(decision.complexity)}
            </Badge>
            <span className="text-[11px] font-medium text-foreground">{decision.provider}</span>
            <span className="text-[11px] text-muted-foreground">
              {decision.model ?? "provider default"}
            </span>
            <span className="text-[11px] text-muted-foreground">
              Budget {formatUsd(decision.budget_usd)}
            </span>
            {decision.requires_review ? (
              <Badge variant="warning" title="A human must review this plan before it is trusted">
                <ShieldCheck aria-hidden="true" className="h-3 w-3" />
                human review
              </Badge>
            ) : null}
            {decision.fallback_used ? (
              <Badge variant="outline" title="The preferred tier had no configured provider">
                fallback
              </Badge>
            ) : null}
            {execution ? (
              <>
                <span className="text-[11px] text-muted-foreground">executed</span>
                <span className="text-[11px] font-medium text-foreground">
                  {execution.actual_provider}
                </span>
                <span className="text-[11px] text-muted-foreground">
                  {execution.actual_model ?? "provider default"}
                </span>
                <Badge
                  variant={execution.match ? "success" : "warning"}
                  title={`Recommended ${decision.provider}; executed ${execution.actual_provider}`}
                >
                  {execution.match ? "match" : "mismatch"}
                </Badge>
                <span className="sr-only" role="status" aria-live="polite">
                  Run {execution.run_id}
                </span>
              </>
            ) : null}
            {routing ? (
              <span className="group relative inline-flex">
                <button
                  type="button"
                  aria-describedby={tooltipId}
                  className="inline-flex items-center gap-1 rounded-full border border-border bg-card px-2 py-0.5 text-[10px] font-medium text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1"
                >
                  <Info aria-hidden="true" className="h-3 w-3" />
                  Policy
                </button>
                <span
                  id={tooltipId}
                  role="tooltip"
                  className="pointer-events-none absolute left-0 top-full z-20 mt-1 w-64 rounded-md border border-border bg-card p-2 text-left opacity-0 shadow-lg transition-opacity group-hover:opacity-100 group-focus-within:opacity-100"
                >
                  <span className="block text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                    Tier budgets
                  </span>
                  <span className="mt-1 block space-y-0.5">
                    {COMPLEXITY_ORDER.map((complexity) => (
                      <span
                        key={complexity}
                        className="flex items-center justify-between gap-2 text-[11px] leading-4"
                      >
                        <span className="text-foreground">{humanizeKey(complexity)}</span>
                        <span className="text-muted-foreground">
                          {routing.policy[complexity].tier} ·{" "}
                          {formatUsd(routing.policy[complexity].budget_usd)}
                        </span>
                      </span>
                    ))}
                  </span>
                </span>
              </span>
            ) : null}
          </>
        ) : null}

        {pending ? (
          <span className="inline-flex items-center gap-1 text-[11px] text-muted-foreground">
            <Loader2 aria-hidden="true" className="h-3 w-3 animate-spin" />
            Classifying…
          </span>
        ) : null}

        {!pending && unavailable && !decision ? (
          <span className="text-[11px] text-muted-foreground" title="The routing call failed">
            Routing unavailable
          </span>
        ) : null}

        {!pending && !unavailable && !decision ? (
          <span className="text-[11px] text-muted-foreground">
            Waiting for the brief to settle…
          </span>
        ) : null}
      </div>

      {decision && decision.reason.length > 0 ? (
        <ul className="mt-1.5 list-disc space-y-0.5 pl-4 text-[11px] leading-4 text-muted-foreground">
          {decision.reason.map((reason, index) => (
            <li key={`${reason}-${index}`}>{reason}</li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
