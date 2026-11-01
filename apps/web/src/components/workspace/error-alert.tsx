import type { ReactNode } from "react";
import { AlertCircle, CheckCircle2, Info, X } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { ApiError } from "@/lib/api";
import { prettyJson } from "@/lib/format";
import { isRecord } from "@/lib/guards";
import { VALIDATION_LEVELS } from "@/lib/validation";
import { cn } from "@/lib/utils";

interface StructuredValidation {
  structural?: unknown;
  semantic?: unknown;
  logical?: unknown;
  visual?: unknown;
  docentric_compatibility?: unknown;
}

function isStatusValue(value: unknown): value is string {
  return (
    typeof value === "string" &&
    ["passed", "failed", "warning", "skipped", "not_tested"].includes(value)
  );
}

function statusChipClass(status: string): string {
  switch (status) {
    case "passed":
      return "border-success/30 bg-success/10 text-success";
    case "failed":
      return "border-destructive/30 bg-destructive/10 text-destructive";
    case "warning":
      return "border-warning/30 bg-warning/10 text-warning";
    case "not_tested":
      return "border-dashed border-slate-400 bg-slate-50 text-slate-600";
    default:
      return "border-border bg-muted text-muted-foreground";
  }
}

function ValidationDetails({ validation }: { validation: StructuredValidation }) {
  return (
    <div className="mt-2 flex flex-wrap gap-1.5">
      {VALIDATION_LEVELS.map((level) => {
        const status = validation[level.key];
        if (!isStatusValue(status)) {
          return null;
        }
        return (
          <span
            key={level.key}
            className={cn(
              "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium",
              statusChipClass(status),
            )}
          >
            {level.code} {level.label}: {status.replace("_", " ")}
          </span>
        );
      })}
    </div>
  );
}

function ValidationErrors({ errors }: { errors: unknown[] }) {
  const rows = errors.filter(isRecord).slice(0, 8);
  if (rows.length === 0) {
    return null;
  }
  return (
    <ul className="mt-2 space-y-1.5">
      {rows.map((row, index) => (
        <li key={index} className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-xs">
          {typeof row.location === "string" && row.location ? (
            <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-[11px] text-foreground">
              {row.location}
            </code>
          ) : null}
          <span className="text-foreground">
            {typeof row.message === "string" ? row.message : "Invalid value"}
          </span>
          {typeof row.type === "string" ? (
            <span className="text-[10px] text-muted-foreground">({row.type})</span>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

export interface ErrorAlertProps {
  error: ApiError;
  title?: string;
  className?: string;
  onDismiss?: () => void;
  action?: ReactNode;
}

/** Error surface that always shows the API message, code and structured details. */
export function ErrorAlert({
  error,
  title = "Request failed",
  className,
  onDismiss,
  action,
}: ErrorAlertProps) {
  const details = error.details;
  const detailRecord = details ?? null;
  const validation =
    detailRecord && isRecord(detailRecord.validation)
      ? (detailRecord.validation as StructuredValidation)
      : null;
  const errors = detailRecord && Array.isArray(detailRecord.errors) ? detailRecord.errors : null;
  const reportAttached = Boolean(detailRecord && detailRecord.report);

  const remaining: Record<string, unknown> = {};
  if (detailRecord) {
    for (const [key, value] of Object.entries(detailRecord)) {
      if (key === "validation" || key === "errors" || key === "report" || key === "overall") {
        continue;
      }
      remaining[key] = value;
    }
  }
  const hasRemaining = Object.keys(remaining).length > 0;

  return (
    <Alert variant="destructive" className={cn("animate-fade-in", className)}>
      <AlertCircle aria-hidden="true" />
      <div className="min-w-0 flex-1">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <AlertTitle>{title}</AlertTitle>
            <p className="text-sm leading-5 text-foreground">{error.message}</p>
            <p className="mt-1 font-mono text-[11px] text-muted-foreground">
              {error.code}
              {error.status > 0
                ? ` · HTTP ${error.status}`
                : error.code.startsWith("client_")
                  ? " · client validation"
                  : " · network"}
            </p>
          </div>
          {onDismiss ? (
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              className="-mr-1 -mt-1 shrink-0 text-muted-foreground hover:text-foreground"
              onClick={onDismiss}
              aria-label="Dismiss error"
            >
              <X aria-hidden="true" />
            </Button>
          ) : null}
        </div>

        <AlertDescription className="mt-1">
          <dl className="sr-only">
            <dt>Error code</dt>
            <dd>{error.code}</dd>
            <dt>Error details</dt>
            <dd>{details ? prettyJson(details) : "No additional details"}</dd>
          </dl>

          {validation ? <ValidationDetails validation={validation} /> : null}
          {errors ? <ValidationErrors errors={errors} /> : null}
          {reportAttached ? (
            <p className="mt-2 text-xs text-muted-foreground">
              A validation report was included in the error response. Per-level results are shown
              in the validation panel when available.
            </p>
          ) : null}
          {hasRemaining ? (
            <pre className="scroll-area mt-2 max-h-40 overflow-auto rounded-md border border-destructive/15 bg-card/80 p-2 font-mono text-[11px] leading-5 text-foreground">
              {prettyJson(remaining)}
            </pre>
          ) : null}
          {!details ? (
            <p className="mt-1 flex items-center gap-1 text-xs text-muted-foreground">
              <Info aria-hidden="true" className="h-3 w-3" />
              The API did not return additional error details.
            </p>
          ) : null}
          {action ? <div className="mt-2 flex flex-wrap items-center gap-2">{action}</div> : null}
          {reportAttached ? (
            <Badge variant="outline" className="mt-2">
              <CheckCircle2 aria-hidden="true" className="h-3 w-3" />
              Report attached to response
            </Badge>
          ) : null}
        </AlertDescription>
      </div>
    </Alert>
  );
}
