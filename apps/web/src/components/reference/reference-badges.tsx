"use client";

import type { VariantProps } from "class-variance-authority";
import {
  AlertTriangle,
  CheckCircle2,
  CircleDashed,
  Info,
  Minus,
  Pencil,
  Plus,
  ShieldAlert,
  XCircle,
} from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge, badgeVariants } from "@/components/ui/badge";
import {
  CHANGE_LABELS,
  CLASSIFICATION_LABELS,
  DIFF_ITEM_KIND_LABELS,
  DIMENSION_LABELS,
  EDGE_TYPE_LABELS,
  ELEMENT_KIND_LABELS,
  GRAPH_STATUS_LABELS,
  NODE_KIND_LABELS,
  RESOLUTION_LABELS,
  SEVERITY_LABELS,
  formatRatio,
  referenceEnumLabel,
} from "@/lib/reference";
import type {
  ReferenceChangeDimension,
  ReferenceChangeType,
  ReferenceClassification,
  ReferenceDiffItemKind,
  ReferenceElementKind,
  ReferenceGraphEdgeType,
  ReferenceGraphNodeKind,
  ReferenceGraphStatus,
  ReferenceResolutionStatus,
  ReferenceSeverity,
} from "@/lib/types";
import { cn } from "@/lib/utils";

type BadgeVariant = NonNullable<VariantProps<typeof badgeVariants>["variant"]>;

const CLASSIFICATION_STYLE: Record<
  ReferenceClassification,
  { variant: BadgeVariant; icon: typeof CheckCircle2; title: string }
> = {
  recognized: {
    variant: "success",
    icon: CheckCircle2,
    title: "A recognizable Docentric marker was found",
  },
  ambiguous: {
    variant: "warning",
    icon: AlertTriangle,
    title: "Docentric markers conflict; the control is preserved as ambiguous",
  },
  unknown: {
    variant: "unverified",
    icon: CircleDashed,
    title: "No recognizable Docentric marker was found; the control is preserved as unknown",
  },
};

export function ClassificationBadge({
  classification,
  className,
}: {
  classification: ReferenceClassification;
  className?: string;
}) {
  const style = CLASSIFICATION_STYLE[classification];
  const Icon = style.icon;
  return (
    <Badge variant={style.variant} title={style.title} className={className}>
      <Icon aria-hidden="true" className="h-3 w-3" />
      {referenceEnumLabel(CLASSIFICATION_LABELS, classification)}
    </Badge>
  );
}

const RESOLUTION_STYLE: Record<
  ReferenceResolutionStatus,
  { variant: BadgeVariant; icon: typeof CheckCircle2; title: string }
> = {
  resolved: {
    variant: "success",
    icon: CheckCircle2,
    title: "The control resolved against ProjectData",
  },
  missing_part: {
    variant: "destructive",
    icon: XCircle,
    title: "The expected ProjectData part or store item is missing",
  },
  unknown_path: {
    variant: "unverified",
    icon: CircleDashed,
    title: "ProjectData was found but the binding path could not be matched",
  },
  ambiguous: {
    variant: "warning",
    icon: AlertTriangle,
    title: "More than one candidate matched; the row stays visible for review",
  },
};

export function ResolutionBadge({
  status,
  className,
}: {
  status: ReferenceResolutionStatus;
  className?: string;
}) {
  const style = RESOLUTION_STYLE[status];
  const Icon = style.icon;
  return (
    <Badge variant={style.variant} title={style.title} className={className}>
      <Icon aria-hidden="true" className="h-3 w-3" />
      {referenceEnumLabel(RESOLUTION_LABELS, status)}
    </Badge>
  );
}

const GRAPH_STATUS_STYLE: Record<
  ReferenceGraphStatus,
  { variant: BadgeVariant; icon: typeof CheckCircle2 }
> = {
  resolved: { variant: "success", icon: CheckCircle2 },
  ambiguous: { variant: "warning", icon: AlertTriangle },
  unknown: { variant: "unverified", icon: CircleDashed },
};

export function GraphStatusBadge({
  status,
  className,
}: {
  status: ReferenceGraphStatus;
  className?: string;
}) {
  const style = GRAPH_STATUS_STYLE[status];
  const Icon = style.icon;
  return (
    <Badge variant={style.variant} className={className}>
      <Icon aria-hidden="true" className="h-3 w-3" />
      {referenceEnumLabel(GRAPH_STATUS_LABELS, status)}
    </Badge>
  );
}

const NODE_KIND_STYLE: Record<ReferenceGraphNodeKind, BadgeVariant> = {
  control: "info",
  element: "secondary",
  source: "muted",
  schema_field: "outline",
};

export function NodeKindBadge({
  kind,
  className,
}: {
  kind: ReferenceGraphNodeKind;
  className?: string;
}) {
  return (
    <Badge variant={NODE_KIND_STYLE[kind]} className={className}>
      {referenceEnumLabel(NODE_KIND_LABELS, kind)}
    </Badge>
  );
}

export function ElementKindBadge({
  kind,
  className,
}: {
  kind: ReferenceElementKind;
  className?: string;
}) {
  return (
    <Badge variant="outline" className={className}>
      {referenceEnumLabel(ELEMENT_KIND_LABELS, kind)}
    </Badge>
  );
}

export function EdgeTypeBadge({
  type,
  className,
}: {
  type: ReferenceGraphEdgeType;
  className?: string;
}) {
  return (
    <Badge variant="outline" className={className}>
      {referenceEnumLabel(EDGE_TYPE_LABELS, type)}
    </Badge>
  );
}

const CHANGE_STYLE: Record<
  ReferenceChangeType,
  { variant: BadgeVariant; icon: typeof Plus }
> = {
  added: { variant: "success", icon: Plus },
  removed: { variant: "destructive", icon: Minus },
  changed: { variant: "warning", icon: Pencil },
};

export function ChangeBadge({ change }: { change: ReferenceChangeType }) {
  const style = CHANGE_STYLE[change];
  const Icon = style.icon;
  return (
    <Badge variant={style.variant}>
      <Icon aria-hidden="true" className="h-3 w-3" />
      {referenceEnumLabel(CHANGE_LABELS, change)}
    </Badge>
  );
}

export function DimensionBadge({ dimension }: { dimension: ReferenceChangeDimension }) {
  return (
    <Badge variant={dimension === "structural" ? "info" : "secondary"}>
      {referenceEnumLabel(DIMENSION_LABELS, dimension)}
    </Badge>
  );
}

export function DiffItemKindBadge({ kind }: { kind: ReferenceDiffItemKind }) {
  return (
    <Badge variant="outline">{referenceEnumLabel(DIFF_ITEM_KIND_LABELS, kind)}</Badge>
  );
}

const SEVERITY_STYLE: Record<
  ReferenceSeverity,
  { variant: BadgeVariant; icon: typeof Info }
> = {
  info: { variant: "info", icon: Info },
  warning: { variant: "warning", icon: AlertTriangle },
  error: { variant: "destructive", icon: XCircle },
};

export function SeverityBadge({ severity }: { severity: ReferenceSeverity }) {
  const style = SEVERITY_STYLE[severity];
  const Icon = style.icon;
  return (
    <Badge variant={style.variant}>
      <Icon aria-hidden="true" className="h-3 w-3" />
      {referenceEnumLabel(SEVERITY_LABELS, severity)}
    </Badge>
  );
}

/**
 * Persistent, non-dismissible runtime notice. Static inspection can prove what a
 * template contains, never that Docentric AX will execute it.
 */
export function RuntimeCompatibilityNotice({ className }: { className?: string }) {
  return (
    <Alert
      variant="warning"
      role="note"
      aria-label="Docentric AX runtime compatibility"
      className={cn("animate-fade-in", className)}
    >
      <ShieldAlert aria-hidden="true" />
      <div className="min-w-0 flex-1">
        <AlertTitle>Docentric AX runtime compatibility: not tested</AlertTitle>
        <AlertDescription>
          This inspector is read-only and static. It records what the template contains and
          never executes it, so no part of this report is a runtime compatibility claim.
        </AlertDescription>
      </div>
    </Alert>
  );
}

export interface ReferenceCoverageBarProps {
  ratio: number;
  label: string;
  className?: string;
}

export function ReferenceCoverageBar({ ratio, label, className }: ReferenceCoverageBarProps) {
  const bounded = Math.min(Math.max(Number.isFinite(ratio) ? ratio : 0, 0), 1);
  const percent = Math.round(bounded * 1000) / 10;
  const tone =
    percent >= 80 ? "bg-success" : percent >= 50 ? "bg-warning" : "bg-destructive";
  return (
    <div className={cn("space-y-1.5", className)}>
      <div className="flex items-center justify-between gap-2 text-[11px]">
        <span className="font-medium text-foreground">{label}</span>
        <span className="font-mono text-muted-foreground">{formatRatio(ratio)}</span>
      </div>
      <div
        role="progressbar"
        aria-label={`${label}: ${formatRatio(ratio)}`}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
        className="h-1.5 overflow-hidden rounded-full bg-muted"
      >
        <div className={cn("h-full rounded-full", tone)} style={{ width: `${percent}%` }} />
      </div>
    </div>
  );
}
