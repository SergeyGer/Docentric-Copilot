"use client";

import { useMemo } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  CornerDownLeft,
  Copy,
  ListChecks,
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
import { MappingStatusBadge } from "@/components/workspace/status-badges";
import { NodeTypeBadge } from "@/components/workspace/node-type-badge";
import { Panel } from "@/components/workspace/panel";
import { PANEL_IDS } from "@/lib/constants";
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
  { status: "resolved", label: "Resolved", tone: "bg-success" },
  { status: "ambiguous", label: "Ambiguous", tone: "bg-warning" },
  { status: "missing", label: "Missing", tone: "bg-destructive" },
  { status: "invalid", label: "Invalid", tone: "bg-destructive/70" },
];

function countMappings(report: MappingReport | null): Record<MappingStatus, number> {
  const counts: Record<MappingStatus, number> = {
    resolved: 0,
    ambiguous: 0,
    missing: 0,
    invalid: 0,
  };
  if (report) {
    for (const mapping of report.mappings) {
      counts[mapping.status] += 1;
    }
  }
  return counts;
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
      className="w-20"
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
    </div>
  );
}

interface MappingRowProps {
  mapping: FieldMapping;
  nodes: Map<string, SchemaNode>;
  selectedCandidatePath: string | null;
  onSelectCandidate: (path: string) => void;
}

function MappingRow({
  mapping,
  nodes,
  selectedCandidatePath,
  onSelectCandidate,
}: MappingRowProps) {
  const selectedNode = mapping.selected_field_path
    ? (nodes.get(mapping.selected_field_path) ?? null)
    : null;
  const hasCandidates = mapping.candidate_field_paths.length > 0;

  return (
    <TableRow>
      <TableCell className="max-w-[260px]">
        <p className="text-xs font-medium leading-5 text-foreground">{mapping.requirement}</p>
        <p className="mt-0.5 font-mono text-[10px] text-muted-foreground">
          {mapping.requirement_id}
        </p>
      </TableCell>
      <TableCell>
        <MappingStatusBadge status={mapping.status} />
      </TableCell>
      <TableCell className="max-w-[320px]">
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
          <p className="text-xs italic leading-5 text-muted-foreground">
            {mapping.status === "resolved"
              ? "Satisfied by the document itself"
              : "No field selected"}
          </p>
        )}
        {mapping.schema_evidence ? (
          <p className="mt-1 break-all font-mono text-[10px] text-muted-foreground">
            evidence: {mapping.schema_evidence}
          </p>
        ) : null}
        {hasCandidates ? (
          <Collapsible
            className="mt-1.5"
            defaultOpen={mapping.status !== "resolved" || !mapping.selected_field_path}
          >
            <CollapsibleTrigger className="text-[11px] font-normal text-muted-foreground hover:text-foreground">
              {formatNumber(mapping.candidate_field_paths.length)}{" "}
              {pluralize(mapping.candidate_field_paths.length, "candidate")}
            </CollapsibleTrigger>
            <CollapsibleContent>
              <div className="flex flex-col items-stretch gap-1">
                {mapping.candidate_field_paths.map((path) => {
                  const candidateNode = nodes.get(path) ?? null;
                  const active = selectedCandidatePath === path;
                  return (
                    <button
                      key={path}
                      type="button"
                      onClick={() => onSelectCandidate(path)}
                      aria-pressed={active}
                      title={`Show candidate ${path}`}
                      className={cn(
                        "w-full break-all rounded border px-1.5 py-1 text-left font-mono text-[10px] leading-4 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                        active
                          ? "border-primary bg-accent text-accent-foreground"
                          : "border-border bg-card text-muted-foreground hover:border-primary/40 hover:bg-accent/50",
                      )}
                    >
                      {path}
                      <span className="ml-1 opacity-70">
                        · {candidateNode ? nodeKind(candidateNode) : "not in schema"}
                      </span>
                    </button>
                  );
                })}
              </div>
            </CollapsibleContent>
          </Collapsible>
        ) : (
          <p className="mt-1 text-[10px] text-muted-foreground">No candidate fields proposed.</p>
        )}
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
  onSelectCandidate: (path: string) => void;
  onClearCandidate: () => void;
  onCopyPath: (path: string) => void;
  onInsertPath: (path: string) => void;
}

export function MappingPanel({
  schema,
  mapping,
  removedBindings,
  selectedCandidatePath,
  onSelectCandidate,
  onClearCandidate,
  onCopyPath,
  onInsertPath,
}: MappingPanelProps) {
  const counts = useMemo(() => countMappings(mapping), [mapping]);
  const nodes = useMemo(() => indexSchemaNodes(schema), [schema]);
  const selectedCandidateNode = selectedCandidatePath
    ? (nodes.get(selectedCandidatePath) ?? null)
    : null;
  const blocking = counts.missing + counts.invalid;
  const mappingCount = mapping?.mappings.length ?? 0;

  return (
    <Panel
      id={PANEL_IDS.mapping}
      step={4}
      title="Mapping review"
      description="Each clause of the brief is resolved against the schema. Confidence is the planner's own estimate; schema evidence is the authority."
      actions={
        mapping ? (
          <>
            <Badge variant={blocking > 0 ? "destructive" : "success"}>
              {blocking > 0
                ? `${blocking} blocking ${pluralize(blocking, "mapping")}`
                : "No blocking mappings"}
            </Badge>
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
          description="Plan a template to see how each requirement was matched to a schema field, with candidates and confidence."
        />
      ) : (
        <div>
          <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
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
                  onClick={onClearCandidate}
                  aria-label="Clear selected candidate"
                >
                  <X aria-hidden="true" />
                </Button>
              </div>
            </div>
          ) : null}

          <div className="mt-4 overflow-hidden rounded-lg border">
            <Table className="min-w-[880px]">
              <TableCaption>
                Mapping proposals from the planner. Resolved requires schema evidence; confidence
                alone is never treated as validation.
              </TableCaption>
              <TableHeader>
                <TableRow className="bg-muted/30">
                  <TableHead className="w-[22%]">Requirement</TableHead>
                  <TableHead className="w-[11%]">Status</TableHead>
                  <TableHead className="w-[32%]">Schema binding</TableHead>
                  <TableHead className="w-[12%]">Confidence</TableHead>
                  <TableHead>Explanation</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {mapping.mappings.map((item) => (
                  <MappingRow
                    key={item.requirement_id}
                    mapping={item}
                    nodes={nodes}
                    selectedCandidatePath={selectedCandidatePath}
                    onSelectCandidate={onSelectCandidate}
                  />
                ))}
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
