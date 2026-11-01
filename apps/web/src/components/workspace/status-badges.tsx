import type { ReactNode } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  CircleDashed,
  MinusCircle,
  ShieldAlert,
  XCircle,
} from "lucide-react";
import type { VariantProps } from "class-variance-authority";

import { Badge, badgeVariants } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { overallLabel, statusLabel } from "@/lib/validation";
import type {
  CheckStatus,
  FindingSeverity,
  MappingStatus,
  OverallStatus,
} from "@/lib/types";

type BadgeVariant = NonNullable<VariantProps<typeof badgeVariants>["variant"]>;

const CHECK_STATUS_STYLE: Record<
  CheckStatus,
  { variant: BadgeVariant; icon: typeof CheckCircle2; title: string }
> = {
  passed: {
    variant: "success",
    icon: CheckCircle2,
    title: "This level passed",
  },
  failed: {
    variant: "destructive",
    icon: XCircle,
    title: "This level failed",
  },
  warning: {
    variant: "warning",
    icon: AlertTriangle,
    title: "This level passed with warnings",
  },
  skipped: {
    variant: "muted",
    icon: MinusCircle,
    title: "This level was skipped",
  },
  not_tested: {
    variant: "unverified",
    icon: CircleDashed,
    title: "This level was not tested. Not tested is not a pass.",
  },
};

export interface ValidationStatusBadgeProps {
  status: CheckStatus;
  className?: string;
  showIcon?: boolean;
}

export function ValidationStatusBadge({
  status,
  className,
  showIcon = true,
}: ValidationStatusBadgeProps) {
  const style = CHECK_STATUS_STYLE[status];
  const Icon = style.icon;
  return (
    <Badge
      variant={style.variant}
      title={style.title}
      className={cn(status === "not_tested" && "border-dashed", className)}
    >
      {showIcon ? <Icon aria-hidden="true" className="h-3 w-3" /> : null}
      {statusLabel(status)}
    </Badge>
  );
}

const OVERALL_STYLE: Record<
  OverallStatus,
  { variant: BadgeVariant; icon: typeof CheckCircle2 }
> = {
  passed: { variant: "success", icon: CheckCircle2 },
  passed_unverified_compatibility: { variant: "warning", icon: ShieldAlert },
  failed: { variant: "destructive", icon: XCircle },
};

export interface OverallStatusBadgeProps {
  overall: OverallStatus;
  className?: string;
}

export function OverallStatusBadge({ overall, className }: OverallStatusBadgeProps) {
  const style = OVERALL_STYLE[overall];
  const Icon = style.icon;
  return (
    <Badge variant={style.variant} className={cn("px-2.5 py-1", className)}>
      <Icon aria-hidden="true" className="h-3.5 w-3.5" />
      {overallLabel(overall)}
    </Badge>
  );
}

const MAPPING_STYLE: Record<MappingStatus, { variant: BadgeVariant; label: string }> = {
  resolved: { variant: "success", label: "Resolved" },
  ambiguous: { variant: "warning", label: "Ambiguous" },
  missing: { variant: "destructive", label: "Missing" },
  invalid: { variant: "destructive", label: "Invalid" },
};

export function MappingStatusBadge({ status }: { status: MappingStatus }) {
  const style = MAPPING_STYLE[status];
  return (
    <Badge
      variant={style.variant}
      className={cn(status === "invalid" && "border-dashed")}
      title={
        status === "invalid"
          ? "The proposed field was rejected by schema validation"
          : undefined
      }
    >
      {style.label}
    </Badge>
  );
}

const SEVERITY_STYLE: Record<FindingSeverity, BadgeVariant> = {
  error: "destructive",
  warning: "warning",
  info: "info",
};

export function FindingSeverityBadge({ severity }: { severity: FindingSeverity }) {
  return (
    <Badge variant={SEVERITY_STYLE[severity]} className="uppercase tracking-wide">
      {severity}
    </Badge>
  );
}

export interface StatusDotProps {
  tone: "success" | "warning" | "destructive" | "info" | "muted";
  children?: ReactNode;
}

export function StatusDot({ tone, children }: StatusDotProps) {
  const tones: Record<StatusDotProps["tone"], string> = {
    success: "bg-success",
    warning: "bg-warning",
    destructive: "bg-destructive",
    info: "bg-info",
    muted: "bg-muted-foreground/50",
  };
  return (
    <span className="inline-flex items-center gap-1.5">
      <span aria-hidden="true" className={cn("h-1.5 w-1.5 rounded-full", tones[tone])} />
      {children}
    </span>
  );
}
