"use client";

import { useCallback, useMemo, useState } from "react";
import {
  ArrowLeftRight,
  ArrowRight,
  GitCompare,
  Loader2,
  RefreshCw,
  Trash2,
} from "lucide-react";

import {
  ChangeBadge,
  DimensionBadge,
  DiffItemKindBadge,
  GraphStatusBadge,
} from "@/components/reference/reference-badges";
import { ReferenceDropzone } from "@/components/reference/reference-dropzone";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/workspace/empty-state";
import { ErrorAlert } from "@/components/workspace/error-alert";
import { CopyButton } from "@/components/workspace/copy-button";
import { ApiError, diffReferences, toApiError } from "@/lib/api";
import { formatNumber, truncateMiddle } from "@/lib/format";
import {
  CHANGE_LABELS,
  DIMENSION_LABELS,
  REFERENCE_SCHEMA_EXTENSIONS,
  REFERENCE_TEMPLATE_EXTENSIONS,
  SNAPSHOT_FIELD_LABELS,
  formatRatio,
  formatRatioDelta,
  formatSignedDelta,
  hasReferenceExtension,
  referenceEnumLabel,
} from "@/lib/reference";
import type {
  ReferenceChangeType,
  ReferenceDiff,
  ReferenceDiffCountPair,
  ReferenceDiffItem,
  ReferenceDiffSide,
  ReferenceDiffSnapshot,
} from "@/lib/types";
import { cn } from "@/lib/utils";

const DIFF_ITEMS_INITIAL = 50;

function validateSelection(
  left: File | null,
  right: File | null,
  ddsp: File | null,
): ApiError | null {
  if (!left || !right) {
    return new ApiError("Select both a left and a right reference template to compare.", {
      code: "input_missing",
      details: { left: left?.name ?? null, right: right?.name ?? null },
    });
  }
  if (!hasReferenceExtension(left.name, REFERENCE_TEMPLATE_EXTENSIONS)) {
    return new ApiError(
      `Unsupported left file type "${left.name}". Choose a .docx, .zip or .axpp file.`,
      {
        status: 400,
        code: "input_unsupported",
        details: { field: "left", filename: left.name, allowed: [...REFERENCE_TEMPLATE_EXTENSIONS] },
      },
    );
  }
  if (!hasReferenceExtension(right.name, REFERENCE_TEMPLATE_EXTENSIONS)) {
    return new ApiError(
      `Unsupported right file type "${right.name}". Choose a .docx, .zip or .axpp file.`,
      {
        status: 400,
        code: "input_unsupported",
        details: {
          field: "right",
          filename: right.name,
          allowed: [...REFERENCE_TEMPLATE_EXTENSIONS],
        },
      },
    );
  }
  if (ddsp && !hasReferenceExtension(ddsp.name, REFERENCE_SCHEMA_EXTENSIONS)) {
    return new ApiError(
      `Unsupported DDSP schema type "${ddsp.name}". Choose an .xml or .ddsp file.`,
      {
        status: 400,
        code: "input_unsupported",
        details: { field: "ddsp", filename: ddsp.name, allowed: [...REFERENCE_SCHEMA_EXTENSIONS] },
      },
    );
  }
  return null;
}

function CountPair({
  label,
  pair,
}: {
  label: string;
  pair: ReferenceDiffCountPair;
}) {
  return (
    <div className="rounded-md border border-border bg-muted/15 px-2.5 py-2">
      <dt className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </dt>
      <dd className="mt-0.5 flex flex-wrap items-baseline gap-1.5 text-xs">
        <span className="font-mono text-foreground">
          {formatNumber(pair.left)} → {formatNumber(pair.right)}
        </span>
        <span className="font-mono text-[11px] text-muted-foreground">
          ({formatSignedDelta(pair.delta)})
        </span>
      </dd>
    </div>
  );
}

function SideSummary({ side, label }: { side: ReferenceDiffSide; label: string }) {
  return (
    <div className="rounded-lg border border-border bg-card p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
          {label}
        </p>
        <Badge variant="outline">{side.source_type}</Badge>
      </div>
      <p className="mt-1 break-words text-sm font-medium text-foreground">{side.source_name}</p>
      <p className="mt-0.5 flex flex-wrap items-center gap-1 text-[10px] text-muted-foreground">
        <span className="font-mono">{truncateMiddle(side.source_sha256, 12, 8)}</span>
        <CopyButton value={side.source_sha256} label={`Copy ${label.toLocaleLowerCase()} SHA-256`} />
        <span aria-hidden="true">·</span>
        <span className="font-mono">graph {truncateMiddle(side.graph_digest, 10, 6)}</span>
      </p>
      <div className="mt-1.5 flex flex-wrap gap-1">
        <Badge variant="secondary">
          {formatNumber(side.summary.controls_total)} controls
        </Badge>
        <Badge variant="outline">
          {formatNumber(side.summary.controls_resolved)} resolved
        </Badge>
        <Badge variant="outline">
          {formatNumber(side.summary.controls_ambiguous)} ambiguous
        </Badge>
        <Badge variant="outline">
          {formatNumber(side.summary.controls_unknown)} unknown
        </Badge>
        <Badge variant="outline">{formatNumber(side.summary.edge_count)} edges</Badge>
      </div>
    </div>
  );
}

function SnapshotView({
  label,
  snapshot,
  changedFields,
}: {
  label: string;
  snapshot: ReferenceDiffSnapshot | null;
  changedFields: string[];
}) {
  if (!snapshot) {
    return (
      <div className="rounded-md border border-dashed border-border bg-muted/10 p-2">
        <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
          {label}
        </p>
        <p className="mt-1 text-[11px] text-muted-foreground">— not present on this side —</p>
      </div>
    );
  }

  const rows: Array<[string, string | null]> = [
    ["kind", snapshot.kind],
    ["binding_path", snapshot.binding_path],
    ["part", snapshot.part],
    [
      "paragraph_index",
      snapshot.paragraph_index === null ? null : String(snapshot.paragraph_index),
    ],
    ["source", snapshot.source],
    ["data_type", snapshot.data_type],
    ["collection", snapshot.collection === null ? null : snapshot.collection ? "true" : "false"],
  ];
  const populated = rows.filter(([, value]) => value !== null && value.length > 0);

  return (
    <div className="rounded-md border border-border bg-muted/10 p-2">
      <div
        className={cn(
          "flex flex-wrap items-center justify-between gap-1 rounded px-1",
          changedFields.includes("status") && "bg-warning/15",
        )}
      >
        <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
          {label}
        </p>
        <GraphStatusBadge status={snapshot.status} />
      </div>
      {populated.length > 0 ? (
        <dl className="mt-1 space-y-0.5">
          {populated.map(([field, value]) => (
            <div
              key={field}
              className={cn(
                "grid grid-cols-[88px_minmax(0,1fr)] gap-1 rounded px-1 text-[10px] leading-4",
                changedFields.includes(field) && "bg-warning/15",
              )}
            >
              <dt className="text-muted-foreground">
                {SNAPSHOT_FIELD_LABELS[field] ?? field}
              </dt>
              <dd className="break-all font-mono text-foreground">{value}</dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className="mt-1 text-[10px] text-muted-foreground">No additional snapshot fields.</p>
      )}
    </div>
  );
}

function DiffItemCard({ item }: { item: ReferenceDiffItem }) {
  return (
    <li className="rounded-md border border-border bg-card p-2.5">
      <div className="flex flex-wrap items-center gap-1.5">
        <ChangeBadge change={item.change} />
        <DiffItemKindBadge kind={item.kind} />
        <code className="min-w-0 break-all font-mono text-[10px] text-muted-foreground">
          {item.key}
        </code>
      </div>
      {item.fields.length > 0 ? (
        <p className="mt-1 text-[10px] text-muted-foreground">
          Changed fields:{" "}
          <span className="font-mono text-foreground">
            {item.fields
              .map((field) => SNAPSHOT_FIELD_LABELS[field] ?? field)
              .join(", ")}
          </span>
        </p>
      ) : null}
      <div className="mt-1.5 grid gap-2 sm:grid-cols-2">
        <SnapshotView label="Before" snapshot={item.before} changedFields={item.fields} />
        <SnapshotView label="After" snapshot={item.after} changedFields={item.fields} />
      </div>
      {item.before && item.after && item.before.status !== item.after.status ? (
        <p className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[10px] text-muted-foreground">
          <span className="font-medium">Status transition</span>
          <GraphStatusBadge status={item.before.status} />
          <ArrowRight aria-hidden="true" className="h-3 w-3" />
          <GraphStatusBadge status={item.after.status} />
        </p>
      ) : null}
    </li>
  );
}

function DiffChangeGroup({
  change,
  items,
}: {
  change: ReferenceChangeType;
  items: ReferenceDiffItem[];
}) {
  const [expanded, setExpanded] = useState(false);
  const visible = expanded ? items : items.slice(0, DIFF_ITEMS_INITIAL);

  return (
    <section aria-label={`${referenceEnumLabel(CHANGE_LABELS, change)} items`} className="space-y-1.5">
      <div className="flex items-center gap-1.5">
        <ChangeBadge change={change} />
        <span className="text-xs font-medium tabular-nums text-foreground">
          {formatNumber(items.length)}
        </span>
      </div>
      {items.length === 0 ? (
        <p className="rounded border border-dashed border-border bg-muted/10 px-2 py-1.5 text-[10px] text-muted-foreground">
          No {referenceEnumLabel(CHANGE_LABELS, change).toLocaleLowerCase()} items in this
          dimension.
        </p>
      ) : (
        <>
          <ul className="space-y-1.5">
            {visible.map((item) => (
              <DiffItemCard key={`${item.key}-${item.change}-${item.dimension}`} item={item} />
            ))}
          </ul>
          {items.length > DIFF_ITEMS_INITIAL ? (
            <Button
              type="button"
              size="sm"
              variant="ghost"
              className="h-6 px-1.5 text-[10px]"
              onClick={() => setExpanded((current) => !current)}
              aria-label={
                expanded
                  ? `Show fewer ${change} items`
                  : `Show all ${items.length} ${change} items`
              }
            >
              {expanded
                ? `Show first ${DIFF_ITEMS_INITIAL} items`
                : `Show all ${items.length} items`}
            </Button>
          ) : null}
        </>
      )}
    </section>
  );
}

function DiffDimensionPanel({
  diff,
  dimension,
}: {
  diff: ReferenceDiff;
  dimension: "structural" | "semantic";
}) {
  const summary = dimension === "structural" ? diff.structural : diff.semantic;
  const items = useMemo(
    () => diff.items.filter((item) => item.dimension === dimension),
    [diff.items, dimension],
  );

  return (
    <Card className="h-full">
      <CardHeader className="gap-2 pb-3">
        <div className="flex flex-wrap items-center gap-1.5">
          <DimensionBadge dimension={dimension} />
          <CardTitle className="text-base">
            {referenceEnumLabel(DIMENSION_LABELS, dimension)} changes
          </CardTitle>
          <Badge variant="secondary">{formatNumber(summary.total)}</Badge>
        </div>
        <CardDescription className="text-[12px]">
          {dimension === "structural"
            ? "Presence changes and location-only moves (part or paragraph)."
            : "Binding, resolution status, element kind, source and data-type changes."}
        </CardDescription>
        <div className="flex flex-wrap gap-1.5">
          <Badge variant="success">Added {formatNumber(summary.added)}</Badge>
          <Badge variant="destructive">Removed {formatNumber(summary.removed)}</Badge>
          <Badge variant="warning">Changed {formatNumber(summary.changed)}</Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {(["added", "removed", "changed"] as const).map((change) => (
          <DiffChangeGroup
            key={`${diff.diff_digest}-${dimension}-${change}`}
            change={change}
            items={items.filter((item) => item.change === change)}
          />
        ))}
      </CardContent>
    </Card>
  );
}

function DiffResults({ diff }: { diff: ReferenceDiff }) {
  const summary = diff.summary;
  return (
    <div className="space-y-4" aria-live="off">
      <Card>
        <CardHeader className="gap-2 pb-3">
          <div className="flex flex-wrap items-center gap-1.5">
            <CardTitle className="text-base">Comparison summary</CardTitle>
            <Badge variant="secondary">{formatNumber(summary.total)} changes</Badge>
            <Badge variant="unverified">Runtime not tested</Badge>
          </div>
          <CardDescription className="text-[13px]">
            Read-only ReferenceDiff v{diff.diff_version}; keys are stable across document hashes.
            Structural {formatNumber(summary.structural)} · semantic{" "}
            {formatNumber(summary.semantic)} · ambiguous {formatNumber(summary.ambiguous)}.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid gap-2 lg:grid-cols-2">
            <SideSummary side={diff.left} label="Left" />
            <SideSummary side={diff.right} label="Right" />
          </div>

          <dl className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
            <CountPair label="Controls" pair={diff.counts.controls} />
            <CountPair label="Elements" pair={diff.counts.elements} />
            <CountPair label="Sources" pair={diff.counts.sources} />
            <CountPair label="Schema fields" pair={diff.counts.schema_fields} />
            <CountPair label="Edges" pair={diff.counts.edges} />
            <CountPair label="Parts" pair={diff.counts.parts} />
          </dl>

          <div className="grid gap-2 text-[11px] sm:grid-cols-2">
            <div className="rounded-md border border-border bg-muted/15 px-2.5 py-2">
              <p className="font-medium text-foreground">Coverage</p>
              <p className="mt-0.5 text-muted-foreground">
                Edge {formatRatio(diff.coverage_delta.left_edge_coverage)} →{" "}
                {formatRatio(diff.coverage_delta.right_edge_coverage)}{" "}
                <span className="font-mono">
                  ({formatRatioDelta(diff.coverage_delta.edge_delta)})
                </span>
              </p>
              <p className="text-muted-foreground">
                Control {formatRatio(diff.coverage_delta.left_control_coverage)} →{" "}
                {formatRatio(diff.coverage_delta.right_control_coverage)}{" "}
                <span className="font-mono">
                  ({formatRatioDelta(diff.coverage_delta.control_delta)})
                </span>
              </p>
            </div>
            <div className="rounded-md border border-border bg-muted/15 px-2.5 py-2">
              <p className="font-medium text-foreground">Unresolved</p>
              <p className="mt-0.5 text-muted-foreground">
                {formatNumber(diff.unresolved.left)} → {formatNumber(diff.unresolved.right)}{" "}
                <span className="font-mono">({formatSignedDelta(diff.unresolved_delta)})</span>
                {" · "}+{formatNumber(diff.unresolved.added_keys.length)} newly unresolved ·{" "}
                {formatNumber(diff.unresolved.removed_keys.length)} now resolved
              </p>
              {diff.unresolved.added_keys.length > 0 ? (
                <p className="mt-1 break-all font-mono text-[10px] text-muted-foreground">
                  New: {diff.unresolved.added_keys.slice(0, 3).join(", ")}
                  {diff.unresolved.added_keys.length > 3
                    ? ` +${diff.unresolved.added_keys.length - 3} more`
                    : ""}
                </p>
              ) : null}
            </div>
          </div>

          {Object.keys(summary.status_transitions).length > 0 ? (
            <div>
              <p className="mb-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                Status transitions
              </p>
              <ul className="flex flex-wrap gap-1.5">
                {Object.entries(summary.status_transitions)
                  .sort(([left], [right]) => left.localeCompare(right))
                  .map(([transition, count]) => (
                    <li key={transition}>
                      <Badge variant="outline" className="font-mono">
                        {transition} × {formatNumber(count)}
                      </Badge>
                    </li>
                  ))}
              </ul>
            </div>
          ) : null}

          {diff.counts.parts_added.length > 0 || diff.counts.parts_removed.length > 0 ? (
            <div className="grid gap-2 text-[11px] sm:grid-cols-2">
              <div>
                <p className="font-medium text-foreground">Parts added</p>
                <p className="mt-0.5 break-all font-mono text-muted-foreground">
                  {diff.counts.parts_added.length > 0
                    ? diff.counts.parts_added.slice(0, 10).join(", ")
                    : "None"}
                  {diff.counts.parts_added.length > 10
                    ? ` +${diff.counts.parts_added.length - 10} more`
                    : ""}
                </p>
              </div>
              <div>
                <p className="font-medium text-foreground">Parts removed</p>
                <p className="mt-0.5 break-all font-mono text-muted-foreground">
                  {diff.counts.parts_removed.length > 0
                    ? diff.counts.parts_removed.slice(0, 10).join(", ")
                    : "None"}
                  {diff.counts.parts_removed.length > 10
                    ? ` +${diff.counts.parts_removed.length - 10} more`
                    : ""}
                </p>
              </div>
            </div>
          ) : null}

          <div className="flex flex-wrap items-center gap-1.5 text-[10px] text-muted-foreground">
            <span className="font-mono" title={diff.diff_digest}>
              diff digest {truncateMiddle(diff.diff_digest, 16, 8)}
            </span>
            <CopyButton value={diff.diff_digest} label="Copy diff digest" />
            <span aria-hidden="true">·</span>
            <span>{diff.note}</span>
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <DiffDimensionPanel diff={diff} dimension="structural" />
        <DiffDimensionPanel diff={diff} dimension="semantic" />
      </div>
    </div>
  );
}

/**
 * Independent two-file comparison view. It has its own file pickers because a
 * diff is a separate read-only operation from inspecting one template.
 */
export function ReferenceDiffPanel() {
  const [left, setLeft] = useState<File | null>(null);
  const [right, setRight] = useState<File | null>(null);
  const [ddsp, setDdsp] = useState<File | null>(null);
  const [diff, setDiff] = useState<ReferenceDiff | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [announcement, setAnnouncement] = useState("");

  const updateLeft = useCallback((file: File | null) => {
    setLeft(file);
    setDiff(null);
    setError(null);
  }, []);
  const updateRight = useCallback((file: File | null) => {
    setRight(file);
    setDiff(null);
    setError(null);
  }, []);
  const updateDdsp = useCallback((file: File | null) => {
    setDdsp(file);
    setDiff(null);
    setError(null);
  }, []);

  const handleCompare = useCallback(async () => {
    const validationError = validateSelection(left, right, ddsp);
    if (validationError) {
      setError(validationError);
      setAnnouncement(validationError.message);
      return;
    }
    if (!left || !right) {
      return;
    }
    setPending(true);
    setError(null);
    setDiff(null);
    setAnnouncement("Comparing two reference templates. This is read-only.");
    try {
      const result = await diffReferences(left, right, ddsp);
      setDiff(result);
      setAnnouncement(
        `Comparison complete: ${result.summary.total} changes, ${result.summary.structural} structural and ${result.summary.semantic} semantic. Runtime compatibility not tested.`,
      );
    } catch (caught) {
      const apiError = toApiError(caught);
      setError(apiError);
      setAnnouncement(`Comparison failed: ${apiError.message}`);
    } finally {
      setPending(false);
    }
  }, [ddsp, left, right]);

  const handleReset = () => {
    if (pending) {
      return;
    }
    setLeft(null);
    setRight(null);
    setDdsp(null);
    setDiff(null);
    setError(null);
    setAnnouncement("Comparison cleared.");
  };

  const handleSwap = () => {
    if (pending) {
      return;
    }
    setLeft(right);
    setRight(left);
    setDiff(null);
    setError(null);
  };

  return (
    <div className="space-y-4">
      <p role="status" aria-live="polite" className="sr-only">
        {announcement}
      </p>

      <Card>
        <CardHeader className="gap-2 pb-3">
          <div className="flex flex-wrap items-center gap-1.5">
            <CardTitle className="flex items-center gap-2 text-base">
              <GitCompare aria-hidden="true" className="h-4 w-4 text-muted-foreground" />
              Compare two references
            </CardTitle>
            <Badge variant="outline">Read-only diff</Badge>
            <Badge variant="unverified">Runtime not tested</Badge>
          </div>
          <CardDescription className="text-[13px]">
            Upload a left and a right DOCX, ZIP or AXPP package, optionally with a shared DDSP
            schema. The diff groups controls, elements, bindings, sources and schema fields into
            structural and semantic changes.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] lg:items-start">
            <ReferenceDropzone
              id="reference-diff-left"
              label="Left reference"
              description="The baseline template or package."
              accept={REFERENCE_TEMPLATE_EXTENSIONS.join(",")}
              file={left}
              onFileChange={updateLeft}
              disabled={pending}
            />
            <div className="flex items-center justify-center lg:pt-7">
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={handleSwap}
                disabled={pending || (!left && !right)}
                aria-label="Swap left and right reference files"
                title="Swap left and right"
              >
                <ArrowLeftRight aria-hidden="true" />
                Swap
              </Button>
            </div>
            <ReferenceDropzone
              id="reference-diff-right"
              label="Right reference"
              description="The updated template or package."
              accept={REFERENCE_TEMPLATE_EXTENSIONS.join(",")}
              file={right}
              onFileChange={updateRight}
              disabled={pending}
            />
          </div>

          <ReferenceDropzone
            id="reference-diff-ddsp"
            label="Shared DDSP schema"
            description="Optional schema applied to both uploaded templates."
            accept={REFERENCE_SCHEMA_EXTENSIONS.join(",")}
            file={ddsp}
            onFileChange={updateDdsp}
            disabled={pending}
            optional
          />

          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="button"
              size="sm"
              onClick={() => {
                void handleCompare();
              }}
              disabled={pending || !left || !right}
              aria-busy={pending}
              aria-describedby="reference-diff-note"
            >
              {pending ? (
                <Loader2 aria-hidden="true" className="animate-spin" />
              ) : (
                <GitCompare aria-hidden="true" />
              )}
              {pending ? "Comparing…" : "Compare references"}
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={handleReset}
              disabled={pending || (!left && !right && !ddsp && !diff)}
            >
              <Trash2 aria-hidden="true" />
              Clear
            </Button>
            {diff ? (
              <Button
                type="button"
                size="sm"
                variant="ghost"
                onClick={() => {
                  void handleCompare();
                }}
                disabled={pending}
              >
                <RefreshCw aria-hidden="true" />
                Compare again
              </Button>
            ) : null}
            <span id="reference-diff-note" className="text-[11px] text-muted-foreground">
              Both files are inspected in memory. Nothing is written or executed.
            </span>
          </div>

          {pending ? (
            <div role="status" aria-live="polite" className="space-y-2" aria-busy="true">
              <p className="flex items-center gap-2 text-xs text-muted-foreground">
                <Loader2 aria-hidden="true" className="h-3.5 w-3.5 animate-spin" />
                Comparing references and building the structural/semantic split…
              </p>
              <Skeleton className="h-24 w-full" />
            </div>
          ) : null}

          {error ? (
            <ErrorAlert
              error={error}
              title="Reference comparison failed"
              onDismiss={() => setError(null)}
              action={
                left && right ? (
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={() => {
                      void handleCompare();
                    }}
                    disabled={pending}
                  >
                    <RefreshCw aria-hidden="true" />
                    Retry comparison
                  </Button>
                ) : null
              }
            />
          ) : null}
        </CardContent>
      </Card>

      {!diff && !pending ? (
        <EmptyState
          icon={GitCompare}
          title="Compare two reference templates"
          description="Choose a left and a right .docx, .zip or .axpp file above (and optionally a shared .xml or .ddsp schema), then select Compare references. The result splits added, removed and changed controls, elements, bindings, sources and schema fields into structural and semantic views, with before/after values and status transitions."
        />
      ) : null}

      {diff ? <DiffResults diff={diff} /> : null}
    </div>
  );
}
