"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  Check,
  CheckCheck,
  CheckCircle2,
  Copy,
  CornerDownLeft,
  ListChecks,
  Loader2,
  X,
} from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { EmptyState } from "@/components/workspace/empty-state";
import { ErrorAlert } from "@/components/workspace/error-alert";
import { MappingStatusBadge } from "@/components/workspace/status-badges";
import { NodeTypeBadge } from "@/components/workspace/node-type-badge";
import { Panel } from "@/components/workspace/panel";
import type { ApiError } from "@/lib/api";
import { prefersReducedMotion } from "@/lib/clipboard";
import { PANEL_IDS, REVIEW_NOTE_MAX_LENGTH } from "@/lib/constants";
import {
  confidenceTone,
  formatConfidence,
  formatNumber,
  pluralize,
} from "@/lib/format";
import { indexSchemaNodes, nodeKind } from "@/lib/schema";
import type {
  FieldMapping,
  MappingReport,
  MappingStatus,
  NormalizedSchema,
  RemovedBinding,
  SchemaNode,
} from "@/lib/types";
import { cn } from "@/lib/utils";

const STATUS_ORDER: ReadonlyArray<{ status: MappingStatus; label: string; tone: string }> = [
  { status: "confirmed", label: "Confirmed", tone: "bg-success" },
  { status: "schema_valid", label: "Schema valid", tone: "bg-info" },
  { status: "needs_review", label: "Needs review", tone: "bg-warning" },
  { status: "conflict", label: "Conflict", tone: "bg-destructive" },
  { status: "missing", label: "Missing", tone: "bg-slate-400" },
  { status: "invalid", label: "Invalid", tone: "bg-destructive" },
];

function emptyCounts(): Record<MappingStatus, number> {
  return {
    confirmed: 0,
    schema_valid: 0,
    needs_review: 0,
    conflict: 0,
    missing: 0,
    invalid: 0,
  };
}

function countMappings(report: MappingReport | null): Record<MappingStatus, number> {
  const counts = emptyCounts();
  if (report) {
    for (const mapping of report.mappings) {
      counts[mapping.status] += 1;
    }
  }
  return counts;
}

/** Both needs-review and conflict rows require a human decision. */
function needsHumanReview(status: MappingStatus): boolean {
  return status === "needs_review" || status === "conflict";
}

interface ConfidenceCellProps {
  mapping: FieldMapping;
}

function ConfidenceCell({ mapping }: ConfidenceCellProps) {
  const tone = confidenceTone(mapping.confidence_score);
  const percent =
    mapping.confidence_score === null
      ? null
      : Math.round(Math.min(Math.max(mapping.confidence_score, 0), 1) * 100);
  const barClass =
    tone === "strong"
      ? "bg-success"
      : tone === "medium"
        ? "bg-warning"
        : tone === "weak"
          ? "bg-destructive"
          : "bg-muted-foreground/30";
  const textClass =
    tone === "strong"
      ? "text-success"
      : tone === "medium"
        ? "text-warning"
        : tone === "weak"
          ? "text-destructive"
          : "text-muted-foreground";

  return (
    <div
      className="w-24"
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={percent ?? 0}
      aria-valuetext={percent === null ? "Confidence not reported" : `${percent} percent`}
      aria-label={`Confidence for requirement: ${mapping.requirement}`}
    >
      <span className={cn("font-mono text-xs font-medium", textClass)}>
        {formatConfidence(mapping.confidence_score)}
      </span>
      {percent !== null ? (
        <div className="mt-1 h-1 w-full overflow-hidden rounded-full bg-muted">
          <div className={cn("h-full rounded-full", barClass)} style={{ width: `${percent}%` }} />
        </div>
      ) : null}
      {mapping.evidence_score !== null ? (
        <span className="mt-1 block text-[9px] leading-3 text-muted-foreground">
          evidence {formatConfidence(mapping.evidence_score)}
        </span>
      ) : null}
    </div>
  );
}

interface CandidateListProps {
  mapping: FieldMapping;
  nodes: Map<string, SchemaNode>;
  activePath: string | null;
  selectedCandidatePath: string | null;
  choice: string | null;
  onSelectCandidate: (path: string) => void;
  onChooseCandidate: (requirementId: string, path: string) => void;
}

function CandidateButton({
  path,
  active,
  node,
  onSelect,
}: {
  path: string;
  active: boolean;
  node: SchemaNode | null;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={active}
      title={`Use candidate ${path}`}
      className={cn(
        "flex w-full items-start gap-1.5 rounded border px-1.5 py-1 text-left font-mono text-[10px] leading-4 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        active
          ? "border-primary bg-accent text-accent-foreground"
          : "border-border bg-card text-muted-foreground hover:border-primary/40 hover:bg-accent/50",
      )}
    >
      <span aria-hidden="true" className="mt-0.5 flex h-3 w-3 shrink-0 items-center justify-center">
        {active ? <Check className="h-3 w-3" /> : null}
      </span>
      <span className="min-w-0 flex-1 break-all">
        {path}
        <span className="ml-1 opacity-70">
          · {node ? nodeKind(node) : "not in schema"}
        </span>
      </span>
    </button>
  );
}

function CandidateList({
  mapping,
  nodes,
  activePath,
  selectedCandidatePath,
  choice,
  onSelectCandidate,
  onChooseCandidate,
}: CandidateListProps) {
  const needsReview = needsHumanReview(mapping.status);
  const selectionInRow =
    selectedCandidatePath !== null &&
    (mapping.selected_field_path === selectedCandidatePath ||
      mapping.candidate_field_paths.includes(selectedCandidatePath) ||
      mapping.supporting_field_paths.includes(selectedCandidatePath) ||
      activePath === selectedCandidatePath);
  const [open, setOpen] = useState(
    mapping.status !== "confirmed" || mapping.selected_field_path === null,
  );

  useEffect(() => {
    if (selectionInRow) {
      setOpen(true);
    }
  }, [selectionInRow]);

  const buttons = mapping.candidate_field_paths.map((path) => (
    <CandidateButton
      key={path}
      path={path}
      active={needsReview ? choice === path : selectedCandidatePath === path}
      node={nodes.get(path) ?? null}
      onSelect={() => {
        onSelectCandidate(path);
        if (needsReview) {
          onChooseCandidate(mapping.requirement_id, path);
        }
      }}
    />
  ));

  if (needsReview) {
    return (
      <div className="mt-2">
        <p
          id={`candidate-label-${mapping.requirement_id}`}
          className="text-[10px] font-semibold uppercase tracking-wide text-warning"
        >
          Candidate fields · choose one
        </p>
        <div
          role="group"
          aria-labelledby={`candidate-label-${mapping.requirement_id}`}
          className="mt-1 flex flex-col items-stretch gap-1"
        >
          {buttons}
        </div>
      </div>
    );
  }

  if (mapping.candidate_field_paths.length === 0) {
    return <p className="mt-1 text-[10px] text-muted-foreground">No candidate fields proposed.</p>;
  }

  return (
    <Collapsible className="mt-1.5" open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger className="text-[11px] font-normal text-muted-foreground hover:text-foreground">
        {formatNumber(mapping.candidate_field_paths.length)}{" "}
        {pluralize(mapping.candidate_field_paths.length, "candidate")}
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="flex flex-col items-stretch gap-1">{buttons}</div>
      </CollapsibleContent>
    </Collapsible>
  );
}

export interface ReviewActionState {
  requirementId: string;
  mode: "selected" | "confirm";
}

export interface MappingFocusState {
  path: string;
  token: number;
}

interface MappingRowProps {
  mapping: FieldMapping;
  nodes: Map<string, SchemaNode>;
  activePath: string | null;
  selectedCandidatePath: string | null;
  choice: string | null;
  note: string;
  confirming: ReviewActionState | null;
  registerRow: (requirementId: string, element: HTMLTableRowElement | null) => void;
  onSelectCandidate: (path: string) => void;
  onChooseCandidate: (requirementId: string, path: string) => void;
  onNoteChange: (requirementId: string, value: string) => void;
  onConfirm: (
    requirementId: string,
    selectedFieldPath: string | null,
    note: string | null,
  ) => void;
}

function MappingRow({
  mapping,
  nodes,
  activePath,
  selectedCandidatePath,
  choice,
  note,
  confirming,
  registerRow,
  onSelectCandidate,
  onChooseCandidate,
  onNoteChange,
  onConfirm,
}: MappingRowProps) {
  const selectedNode = mapping.selected_field_path
    ? (nodes.get(mapping.selected_field_path) ?? null)
    : null;
  const needsReview = needsHumanReview(mapping.status);
  const pathMatches =
    activePath !== null &&
    (mapping.selected_field_path === activePath ||
      mapping.candidate_field_paths.includes(activePath) ||
      mapping.supporting_field_paths.includes(activePath));
  const selectionMatches =
    selectedCandidatePath !== null &&
    (mapping.selected_field_path === selectedCandidatePath ||
      mapping.candidate_field_paths.includes(selectedCandidatePath) ||
      mapping.supporting_field_paths.includes(selectedCandidatePath));
  const busy = confirming !== null;
  const busySelected =
    confirming?.requirementId === mapping.requirement_id && confirming.mode === "selected";
  const busyConfirm =
    confirming?.requirementId === mapping.requirement_id && confirming.mode === "confirm";
  const trimmedNote = note.trim();
  const noteValue = trimmedNote.length > 0 ? trimmedNote : null;
  const setRowRef = useCallback(
    (element: HTMLTableRowElement | null) => {
      registerRow(mapping.requirement_id, element);
    },
    [mapping.requirement_id, registerRow],
  );

  return (
    <TableRow
      ref={setRowRef}
      data-mapping-row={mapping.requirement_id}
      data-active-path={pathMatches ? "true" : undefined}
      className={cn(
        "align-top",
        pathMatches
          ? "bg-info/10 ring-1 ring-inset ring-info/40"
          : selectionMatches
            ? "bg-info/5"
            : undefined,
      )}
    >
      <TableCell className="max-w-[280px]">
        <p className="text-xs font-medium leading-5 text-foreground">{mapping.requirement}</p>
        <div className="mt-1 flex flex-wrap items-center gap-1">
          <span className="font-mono text-[10px] text-muted-foreground">
            {mapping.requirement_id}
          </span>
          {mapping.concept ? (
            <Badge variant="outline" className="font-mono text-[10px]">
              concept: {mapping.concept}
            </Badge>
          ) : null}
          {mapping.placement ? (
            <Badge variant="muted" className="text-[10px]">
              {mapping.placement}
            </Badge>
          ) : null}
        </div>
        {mapping.conflict || mapping.conflicts_with.length > 0 ? (
          <div className="mt-1 flex flex-wrap gap-1">
            {mapping.conflicts_with.length > 0 ? (
              mapping.conflicts_with.map((requirementId) => (
                <Badge
                  key={requirementId}
                  variant="destructive"
                  className="text-[10px]"
                  title={`This requirement conflicts with ${requirementId}`}
                >
                  Conflicts with {requirementId}
                </Badge>
              ))
            ) : (
              <Badge variant="destructive" className="text-[10px]">
                Conflict flagged
              </Badge>
            )}
          </div>
        ) : null}
      </TableCell>
      <TableCell>
        <MappingStatusBadge status={mapping.status} />
      </TableCell>
      <TableCell className="max-w-[340px]">
        {mapping.selected_field_path ? (
          <div className="flex flex-wrap items-center gap-1.5">
            <button
              type="button"
              onClick={() => onSelectCandidate(mapping.selected_field_path ?? "")}
              className="max-w-full break-all rounded bg-muted px-1.5 py-0.5 text-left font-mono text-[11px] text-foreground transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              title="Show this field"
            >
              {mapping.selected_field_path}
            </button>
            {selectedNode ? (
              <NodeTypeBadge node={selectedNode} />
            ) : (
              <Badge variant="destructive">not in schema</Badge>
            )}
          </div>
        ) : (
          <p className="text-xs italic leading-5 text-muted-foreground">No field selected</p>
        )}
        {mapping.schema_evidence ? (
          <p className="mt-1 break-all font-mono text-[10px] text-muted-foreground">
            evidence: {mapping.schema_evidence}
          </p>
        ) : null}
        {mapping.supporting_field_paths.length > 0 ? (
          <p
            className="mt-0.5 text-[10px] text-muted-foreground"
            title={mapping.supporting_field_paths.join(", ")}
          >
            supported by {formatNumber(mapping.supporting_field_paths.length)}{" "}
            {pluralize(mapping.supporting_field_paths.length, "field")}
          </p>
        ) : null}
        <CandidateList
          mapping={mapping}
          nodes={nodes}
          activePath={activePath}
          selectedCandidatePath={selectedCandidatePath}
          choice={choice}
          onSelectCandidate={onSelectCandidate}
          onChooseCandidate={onChooseCandidate}
        />

        {needsReview ? (
          <div className="mt-2 rounded-md border border-warning/30 bg-warning/5 p-2">
            <div className="flex flex-wrap items-center justify-between gap-1">
              <label
                htmlFor={`review-note-${mapping.requirement_id}`}
                className="text-[10px] font-semibold uppercase tracking-wide text-foreground"
              >
                Reviewer note
              </label>
              <span className="font-mono text-[9px] text-muted-foreground">
                {note.length}/{REVIEW_NOTE_MAX_LENGTH}
              </span>
            </div>
            <Input
              id={`review-note-${mapping.requirement_id}`}
              value={note}
              onChange={(event) => onNoteChange(mapping.requirement_id, event.target.value)}
              maxLength={REVIEW_NOTE_MAX_LENGTH}
              placeholder="Optional note for the audit trail"
              disabled={busy}
              className="mt-1 h-7 text-[11px]"
            />
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              <Button
                type="button"
                size="sm"
                onClick={() => onConfirm(mapping.requirement_id, choice, noteValue)}
                disabled={busy || !choice}
                aria-busy={busySelected}
                title={
                  choice
                    ? `Confirm ${choice} and create a new version`
                    : "Choose a candidate field first"
                }
              >
                {busySelected ? (
                  <Loader2 aria-hidden="true" className="animate-spin" />
                ) : (
                  <Check aria-hidden="true" />
                )}
                Use this field
              </Button>
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => onConfirm(mapping.requirement_id, null, noteValue)}
                disabled={busy}
                aria-busy={busyConfirm}
                title="Keep the proposed binding and record a reviewer confirmation"
              >
                {busyConfirm ? (
                  <Loader2 aria-hidden="true" className="animate-spin" />
                ) : (
                  <CheckCheck aria-hidden="true" />
                )}
                Confirm as is
              </Button>
            </div>
            <p className="mt-1 text-[10px] leading-4 text-muted-foreground">
              Use this field rebinds the document to the chosen path; Confirm as is keeps the
              proposed binding. Both actions create a new immutable version.
            </p>
          </div>
        ) : null}
      </TableCell>
      <TableCell>
        <ConfidenceCell mapping={mapping} />
      </TableCell>
      <TableCell className="max-w-[280px]">
        <p className="text-xs leading-5 text-muted-foreground">{mapping.explanation || "—"}</p>
        {mapping.data_type ? (
          <p className="mt-1 text-[10px] text-muted-foreground">
            expected type: <span className="font-mono">{mapping.data_type}</span>
          </p>
        ) : null}
      </TableCell>
    </TableRow>
  );
}

export interface MappingPanelProps {
  schema: NormalizedSchema | null;
  mapping: MappingReport | null;
  removedBindings: RemovedBinding[];
  selectedCandidatePath: string | null;
  activePath: string | null;
  mappingFocus: MappingFocusState | null;
  confirming: ReviewActionState | null;
  reviewError: ApiError | null;
  onSelectCandidate: (path: string) => void;
  onClearCandidate: () => void;
  onCopyPath: (path: string) => void;
  onInsertPath: (path: string) => void;
  onConfirmMapping: (
    requirementId: string,
    selectedFieldPath: string | null,
    note: string | null,
  ) => void;
  onDismissReviewError: () => void;
}

export function MappingPanel({
  schema,
  mapping,
  removedBindings,
  selectedCandidatePath,
  activePath,
  mappingFocus,
  confirming,
  reviewError,
  onSelectCandidate,
  onClearCandidate,
  onCopyPath,
  onInsertPath,
  onConfirmMapping,
  onDismissReviewError,
}: MappingPanelProps) {
  const counts = useMemo(() => countMappings(mapping), [mapping]);
  const nodes = useMemo(() => indexSchemaNodes(schema), [schema]);
  const rowRefs = useRef<Map<string, HTMLTableRowElement>>(new Map());
  const [choices, setChoices] = useState<Record<string, string>>({});
  const [notes, setNotes] = useState<Record<string, string>>({});

  useEffect(() => {
    setChoices({});
    setNotes({});
  }, [mapping]);

  const registerRow = useCallback(
    (requirementId: string, element: HTMLTableRowElement | null) => {
      if (element) {
        rowRefs.current.set(requirementId, element);
      } else {
        rowRefs.current.delete(requirementId);
      }
    },
    [],
  );

  useEffect(() => {
    if (!mappingFocus || !mapping) {
      return;
    }
    const row = mapping.mappings.find(
      (item) =>
        item.selected_field_path === mappingFocus.path ||
        item.candidate_field_paths.includes(mappingFocus.path) ||
        item.supporting_field_paths.includes(mappingFocus.path),
    );
    if (!row) {
      return;
    }
    const element = rowRefs.current.get(row.requirement_id);
    if (!element) {
      return;
    }
    element.scrollIntoView({
      behavior: prefersReducedMotion() ? "auto" : "smooth",
      block: "center",
    });
  }, [mapping, mappingFocus]);

  const selectedCandidateNode = selectedCandidatePath
    ? (nodes.get(selectedCandidatePath) ?? null)
    : null;
  const reviewPending = counts.needs_review + counts.conflict;
  const blocking = reviewPending + counts.missing + counts.invalid;
  const mappingCount = mapping?.mappings.length ?? 0;

  return (
    <Panel
      id={PANEL_IDS.mapping}
      step={4}
      title="Mapping review"
      description="Each requirement is matched to the schema. Confidence is the planner's own estimate; schema evidence is the authority, and needs-review or conflict rows require a human decision."
      actions={
        mapping ? (
          <>
            <Badge variant={blocking > 0 ? "destructive" : "success"}>
              {blocking > 0
                ? `${blocking} blocking ${pluralize(blocking, "mapping")}`
                : "No blocking mappings"}
            </Badge>
            {reviewPending > 0 ? (
              <Badge variant="warning">
                {reviewPending} need{reviewPending === 1 ? "s" : ""} review
              </Badge>
            ) : null}
            <Badge variant="outline">
              {formatNumber(mappingCount)} {pluralize(mappingCount, "requirement")}
            </Badge>
          </>
        ) : null
      }
    >
      {!mapping ? (
        <EmptyState
          icon={ListChecks}
          title="No mapping to review"
          description="Plan a template or run the demo to see how each requirement was matched to a schema field, with candidates and confidence."
        />
      ) : (
        <div>
          <dl className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
            {STATUS_ORDER.map((item) => (
              <div key={item.status} className="rounded-md border bg-muted/20 px-2.5 py-2">
                <dt className="flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
                  <span aria-hidden="true" className={cn("h-1.5 w-1.5 rounded-full", item.tone)} />
                  {item.label}
                </dt>
                <dd className="mt-0.5 font-mono text-lg font-semibold leading-6 text-foreground">
                  {counts[item.status]}
                </dd>
              </div>
            ))}
          </dl>

          {reviewError ? (
            <ErrorAlert
              error={reviewError}
              title="Review action failed"
              className="mt-3"
              onDismiss={onDismissReviewError}
            />
          ) : null}

          {removedBindings.length > 0 ? (
            <Alert variant="warning" className="mt-3">
              <AlertTriangle aria-hidden="true" />
              <div>
                <AlertTitle>
                  {removedBindings.length} binding
                  {removedBindings.length === 1 ? " was" : "s were"} removed during planning
                </AlertTitle>
                <AlertDescription>
                  <ul className="space-y-1">
                    {removedBindings.slice(0, 8).map((binding) => (
                      <li key={`${binding.path}-${binding.reason}`} className="text-[11px]">
                        <code className="break-all font-mono text-foreground">{binding.path}</code>
                        <span className="text-muted-foreground">
                          {" "}
                          — {binding.reason} ({binding.block_kind})
                        </span>
                      </li>
                    ))}
                  </ul>
                </AlertDescription>
              </div>
            </Alert>
          ) : null}

          {selectedCandidatePath ? (
            <div className="mt-4 flex flex-col gap-2 rounded-lg border border-info/30 bg-info/5 p-3 sm:flex-row sm:items-start sm:justify-between">
              <div className="min-w-0">
                <p className="text-[10px] font-semibold uppercase tracking-wide text-info">
                  Candidate selected
                </p>
                <p className="mt-0.5 break-all font-mono text-xs text-foreground">
                  {selectedCandidatePath}
                </p>
                <div className="mt-1 flex flex-wrap items-center gap-1.5">
                  {selectedCandidateNode ? (
                    <>
                      <NodeTypeBadge node={selectedCandidateNode} />
                      {selectedCandidateNode.required ? (
                        <Badge variant="destructive">required</Badge>
                      ) : null}
                      <span className="font-mono text-[10px] text-muted-foreground">
                        {selectedCandidateNode.path}
                      </span>
                    </>
                  ) : (
                    <Badge variant="warning">Not found in the current schema</Badge>
                  )}
                </div>
              </div>
              <div className="flex shrink-0 flex-wrap items-center gap-1.5">
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => onCopyPath(selectedCandidatePath)}
                >
                  <Copy aria-hidden="true" />
                  Copy
                </Button>
                <Button
                  type="button"
                  size="sm"
                  onClick={() => onInsertPath(selectedCandidatePath)}
                  disabled={!selectedCandidateNode}
                  title={
                    selectedCandidateNode
                      ? "Insert this path into the prompt"
                      : "Only paths present in the schema can be inserted"
                  }
                >
                  <CornerDownLeft aria-hidden="true" />
                  Insert
                </Button>
                <Button
                  type="button"
                  size="icon-sm"
                  variant="ghost"
                  onClick={() => {
                    setChoices({});
                    onClearCandidate();
                  }}
                  aria-label="Clear selected candidate"
                >
                  <X aria-hidden="true" />
                </Button>
              </div>
            </div>
          ) : null}

          <div className="mt-4 overflow-hidden rounded-lg border">
            <Table className="min-w-[1040px]">
              <TableCaption>
                Mapping proposals from the planner. Confirmed and schema-valid bindings carry
                schema evidence; confidence alone is never treated as validation.
              </TableCaption>
              <TableHeader>
                <TableRow className="bg-muted/30">
                  <TableHead className="w-[22%]">Requirement</TableHead>
                  <TableHead className="w-[10%]">Status</TableHead>
                  <TableHead className="w-[34%]">Schema binding</TableHead>
                  <TableHead className="w-[12%]">Confidence</TableHead>
                  <TableHead>Explanation</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {mapping.mappings.map((item) => {
                  const proposed =
                    item.selected_field_path &&
                    item.candidate_field_paths.includes(item.selected_field_path)
                      ? item.selected_field_path
                      : null;
                  const clickedCandidate =
                    selectedCandidatePath &&
                    needsHumanReview(item.status) &&
                    item.candidate_field_paths.includes(selectedCandidatePath)
                      ? selectedCandidatePath
                      : null;
                  const choice =
                    choices[item.requirement_id] ??
                    clickedCandidate ??
                    proposed ??
                    item.candidate_field_paths[0] ??
                    null;
                  return (
                    <MappingRow
                      key={item.requirement_id}
                      mapping={item}
                      nodes={nodes}
                      activePath={activePath}
                      selectedCandidatePath={selectedCandidatePath}
                      choice={choice}
                      note={notes[item.requirement_id] ?? ""}
                      confirming={confirming}
                      registerRow={registerRow}
                      onSelectCandidate={onSelectCandidate}
                      onChooseCandidate={(requirementId, path) =>
                        setChoices((previous) => ({ ...previous, [requirementId]: path }))
                      }
                      onNoteChange={(requirementId, value) =>
                        setNotes((previous) => ({ ...previous, [requirementId]: value }))
                      }
                      onConfirm={onConfirmMapping}
                    />
                  );
                })}
              </TableBody>
            </Table>
            {mapping.mappings.length === 0 ? (
              <div className="flex items-center gap-2 border-t px-3 py-4 text-xs text-muted-foreground">
                <CheckCircle2 aria-hidden="true" className="h-3.5 w-3.5" />
                The planner returned no requirement mappings.
              </div>
            ) : null}
          </div>
        </div>
      )}
    </Panel>
  );
}
