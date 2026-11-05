"use client";

import { useMemo, useState } from "react";
import { ArrowRight, GitBranch, ListTree } from "lucide-react";

import {
  EdgeTypeBadge,
  ElementKindBadge,
  GraphStatusBadge,
  NodeKindBadge,
  ReferenceCoverageBar,
} from "@/components/reference/reference-badges";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/workspace/empty-state";
import { formatNumber, truncateMiddle } from "@/lib/format";
import {
  BINDING_STATUS_LABELS,
  EDGE_TYPE_LABELS,
  NODE_KIND_LABELS,
  PLATFORM_LABELS,
  SCHEMA_SOURCE_LABELS,
  formatRatio,
  referenceEnumLabel,
  sortCountEntries,
} from "@/lib/reference";
import type {
  ReferenceGraph,
  ReferenceGraphEdge,
  ReferenceGraphNode,
} from "@/lib/types";

const GRAPH_NODES_PER_GROUP = 100;
const GRAPH_EDGES_PER_NODE = 20;
const GRAPH_UNRESOLVED_INITIAL = 100;

interface GraphGroup {
  key: string;
  part: string;
  documentName: string | null;
  nodes: ReferenceGraphNode[];
}

function CountChips({
  counts,
  labels,
}: {
  counts: Record<string, number>;
  labels: Record<string, string>;
}) {
  const entries = sortCountEntries(counts).filter(([, count]) => count > 0);
  if (entries.length === 0) {
    return <p className="text-[11px] text-muted-foreground">None</p>;
  }
  return (
    <ul className="flex flex-wrap gap-1.5">
      {entries.map(([key, count]) => (
        <li key={key}>
          <Badge variant="outline">
            {referenceEnumLabel(labels, key)} · {formatNumber(count)}
          </Badge>
        </li>
      ))}
    </ul>
  );
}

function nodeMeta(node: ReferenceGraphNode): string[] {
  const meta: string[] = [];
  if (node.paragraph_index !== null) {
    meta.push(`¶${node.paragraph_index}`);
  }
  if (node.ordinal !== null) {
    meta.push(`ordinal ${node.ordinal}`);
  }
  if (node.element_id) {
    meta.push(`element ${node.element_id}`);
  }
  if (node.data_type) {
    meta.push(node.collection ? `${node.data_type}[]` : node.data_type);
  }
  if (node.source_name) {
    meta.push(`source ${node.source_name}`);
  }
  if (node.origin) {
    meta.push(node.origin);
  }
  if (node.schema_source) {
    meta.push(referenceEnumLabel(SCHEMA_SOURCE_LABELS, node.schema_source));
  }
  if (node.source_id) {
    meta.push(`source id ${node.source_id}`);
  }
  return meta;
}

function GraphNodeRow({
  node,
  edges,
  nodesById,
}: {
  node: ReferenceGraphNode;
  edges: ReferenceGraphEdge[];
  nodesById: Map<string, ReferenceGraphNode>;
}) {
  const [showAllEdges, setShowAllEdges] = useState(false);
  const visibleEdges = showAllEdges ? edges : edges.slice(0, GRAPH_EDGES_PER_NODE);
  const meta = nodeMeta(node);

  return (
    <li className="border-t border-border px-3 py-2 first:border-t-0">
      <div className="flex flex-wrap items-center gap-1.5">
        <NodeKindBadge kind={node.kind} />
        <span className="min-w-0 break-words text-xs font-medium text-foreground">
          {node.label}
        </span>
        <GraphStatusBadge status={node.status} />
        {node.element_kind ? <ElementKindBadge kind={node.element_kind} /> : null}
        {meta.length > 0 ? (
          <span className="break-words text-[10px] text-muted-foreground">{meta.join(" · ")}</span>
        ) : null}
      </div>

      {node.binding_path ? (
        <code
          className="mt-1 block break-all rounded bg-muted/25 px-1.5 py-0.5 font-mono text-[11px] text-foreground"
          title={node.binding_path}
        >
          {node.binding_path}
        </code>
      ) : null}

      {node.evidence_location ? (
        <p className="mt-1 break-all font-mono text-[10px] text-muted-foreground">
          evidence: {node.evidence_location}
        </p>
      ) : null}

      {node.reason ? (
        <p className="mt-1 break-words text-[10px] text-warning">Reason: {node.reason}</p>
      ) : null}

      {edges.length > 0 ? (
        <ul className="mt-1.5 space-y-1 border-l border-border pl-3">
          {visibleEdges.map((edge) => {
            const target = nodesById.get(edge.target);
            return (
              <li key={edge.id} className="flex flex-wrap items-center gap-1.5 text-[11px]">
                <EdgeTypeBadge type={edge.type} />
                <ArrowRight aria-hidden="true" className="h-3 w-3 text-muted-foreground" />
                {target ? (
                  <>
                    <NodeKindBadge kind={target.kind} />
                    <span className="min-w-0 break-words text-foreground">{target.label}</span>
                  </>
                ) : (
                  <code className="break-all font-mono text-[10px] text-muted-foreground">
                    {edge.target}
                  </code>
                )}
                <GraphStatusBadge status={edge.status} />
                {edge.resolution_status && edge.resolution_status !== edge.status ? (
                  <Badge variant="outline" className="text-[10px]">
                    {referenceEnumLabel(BINDING_STATUS_LABELS, edge.resolution_status)}
                  </Badge>
                ) : null}
                {edge.evidence.evidence ? (
                  <span
                    className="max-w-[22rem] truncate font-mono text-[10px] text-muted-foreground"
                    title={edge.evidence.evidence}
                  >
                    {edge.evidence.evidence}
                  </span>
                ) : null}
                {edge.reason ? (
                  <span className="break-words text-[10px] text-muted-foreground">
                    ({edge.reason})
                  </span>
                ) : null}
              </li>
            );
          })}
          {edges.length > GRAPH_EDGES_PER_NODE ? (
            <li>
              <Button
                type="button"
                size="sm"
                variant="ghost"
                onClick={() => setShowAllEdges((current) => !current)}
                className="h-6 px-1.5 text-[10px]"
                aria-label={
                  showAllEdges
                    ? `Show fewer edges for ${node.label}`
                    : `Show all ${edges.length} edges for ${node.label}`
                }
              >
                {showAllEdges
                  ? `Show first ${GRAPH_EDGES_PER_NODE} edges`
                  : `Show all ${edges.length} edges`}
              </Button>
            </li>
          ) : null}
        </ul>
      ) : null}
    </li>
  );
}

function GraphGroupSection({
  group,
  edgesBySource,
  nodesById,
}: {
  group: GraphGroup;
  edgesBySource: Map<string, ReferenceGraphEdge[]>;
  nodesById: Map<string, ReferenceGraphNode>;
}) {
  const [expanded, setExpanded] = useState(false);
  const visible = expanded ? group.nodes : group.nodes.slice(0, GRAPH_NODES_PER_GROUP);
  const counts = group.nodes.reduce<Record<string, number>>((accumulator, node) => {
    accumulator[node.kind] = (accumulator[node.kind] ?? 0) + 1;
    return accumulator;
  }, {});

  return (
    <section
      aria-labelledby={`reference-graph-${group.key.replace(/[^a-z0-9]/gi, "-")}`}
      className="overflow-hidden rounded-lg border border-border bg-card"
    >
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border bg-muted/20 px-3 py-2">
        <div className="min-w-0">
          <h3
            id={`reference-graph-${group.key.replace(/[^a-z0-9]/gi, "-")}`}
            className="break-all font-mono text-xs font-semibold text-foreground"
          >
            {group.part}
          </h3>
          {group.documentName ? (
            <p className="truncate text-[10px] text-muted-foreground" title={group.documentName}>
              {group.documentName}
            </p>
          ) : null}
        </div>
        <div className="flex flex-wrap gap-1">
          {sortCountEntries(counts).map(([kind, count]) => (
            <Badge key={kind} variant="secondary">
              {referenceEnumLabel(NODE_KIND_LABELS, kind)} · {formatNumber(count)}
            </Badge>
          ))}
        </div>
      </div>
      <ul>
        {visible.map((node) => (
          <GraphNodeRow
            key={node.id}
            node={node}
            edges={edgesBySource.get(node.id) ?? []}
            nodesById={nodesById}
          />
        ))}
      </ul>
      {group.nodes.length > GRAPH_NODES_PER_GROUP ? (
        <div className="border-t border-border px-3 py-2">
          <Button
            type="button"
            size="sm"
            variant="ghost"
            onClick={() => setExpanded((current) => !current)}
            className="h-7 px-2 text-[11px]"
            aria-label={
              expanded
                ? `Show fewer nodes in ${group.part}`
                : `Show all ${group.nodes.length} nodes in ${group.part}`
            }
          >
            {expanded
              ? `Show first ${GRAPH_NODES_PER_GROUP} nodes`
              : `Show all ${group.nodes.length} nodes`}
          </Button>
        </div>
      ) : null}
    </section>
  );
}

export function ReferenceGraphPanel({ graph }: { graph: ReferenceGraph }) {
  const [showAllUnresolved, setShowAllUnresolved] = useState(false);
  const summary = graph.summary;
  const unresolved = showAllUnresolved
    ? graph.unresolved
    : graph.unresolved.slice(0, GRAPH_UNRESOLVED_INITIAL);

  const nodesById = useMemo(
    () => new Map(graph.nodes.map((node) => [node.id, node])),
    [graph.nodes],
  );
  const edgesBySource = useMemo(() => {
    const map = new Map<string, ReferenceGraphEdge[]>();
    for (const edge of graph.edges) {
      const current = map.get(edge.source);
      if (current) {
        current.push(edge);
      } else {
        map.set(edge.source, [edge]);
      }
    }
    return map;
  }, [graph.edges]);
  const groups = useMemo(() => {
    const map = new Map<string, GraphGroup>();
    for (const node of graph.nodes) {
      const part = node.part ?? "(no part)";
      const key = `${node.document_sha256 ?? ""}::${part}`;
      const current = map.get(key);
      if (current) {
        current.nodes.push(node);
      } else {
        map.set(key, {
          key,
          part,
          documentName: node.document_name,
          nodes: [node],
        });
      }
    }
    return Array.from(map.values());
  }, [graph.nodes]);

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="gap-3 pb-3">
          <div className="flex flex-col justify-between gap-2 sm:flex-row sm:items-start">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-1.5">
                <CardTitle className="flex items-center gap-2 text-base">
                  <GitBranch aria-hidden="true" className="h-4 w-4 text-muted-foreground" />
                  Reference graph
                </CardTitle>
                <Badge variant="secondary">
                  {referenceEnumLabel(PLATFORM_LABELS, graph.platform)}
                </Badge>
                <Badge variant="outline">
                  {referenceEnumLabel(SCHEMA_SOURCE_LABELS, graph.schema_source)}
                </Badge>
                <Badge variant="unverified">Runtime not tested</Badge>
              </div>
              <CardDescription className="mt-1 text-[13px]">
                Controls, ProjectData elements, sources and DDSP schema fields connected by typed
                edges. Nothing is executed and unresolved material is retained explicitly.
              </CardDescription>
            </div>
            <div className="flex flex-wrap gap-1.5 text-[10px] text-muted-foreground">
              <span className="font-mono">graph {graph.graph_version}</span>
              <span className="font-mono" title={graph.graph_digest}>
                digest {truncateMiddle(graph.graph_digest, 10, 6)}
              </span>
              {graph.schema_sections.length > 0 ? (
                <span>sections: {graph.schema_sections.join(", ")}</span>
              ) : null}
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <dl className="grid gap-2 sm:grid-cols-2 xl:grid-cols-5">
            <div className="rounded-lg border border-border bg-muted/15 p-3">
              <dt className="text-[11px] uppercase tracking-wide text-muted-foreground">Nodes</dt>
              <dd className="mt-1 text-xl font-semibold tabular-nums">{formatNumber(summary.node_count)}</dd>
              <p className="mt-0.5 text-[11px] text-muted-foreground">
                {formatNumber(summary.elements_total)} elements ·{" "}
                {formatNumber(summary.sources_total)} sources
              </p>
            </div>
            <div className="rounded-lg border border-border bg-muted/15 p-3">
              <dt className="text-[11px] uppercase tracking-wide text-muted-foreground">Edges</dt>
              <dd className="mt-1 text-xl font-semibold tabular-nums">{formatNumber(summary.edge_count)}</dd>
              <p className="mt-0.5 text-[11px] text-muted-foreground">
                {formatNumber(summary.resolved_edges)} resolved ·{" "}
                {formatNumber(summary.ambiguous_edges)} ambiguous ·{" "}
                {formatNumber(summary.unknown_edges)} unknown
              </p>
            </div>
            <div className="rounded-lg border border-border bg-muted/15 p-3">
              <dt className="text-[11px] uppercase tracking-wide text-muted-foreground">
                Controls
              </dt>
              <dd className="mt-1 text-xl font-semibold tabular-nums">
                {formatNumber(summary.controls_total)}
              </dd>
              <p className="mt-0.5 text-[11px] text-muted-foreground">
                {formatNumber(summary.controls_resolved)} resolved ·{" "}
                {formatNumber(summary.controls_ambiguous)} ambiguous ·{" "}
                {formatNumber(summary.controls_unknown)} unknown
              </p>
            </div>
            <div className="rounded-lg border border-border bg-muted/15 p-3">
              <dt className="text-[11px] uppercase tracking-wide text-muted-foreground">
                Schema fields
              </dt>
              <dd className="mt-1 text-xl font-semibold tabular-nums">
                {formatNumber(summary.schema_fields_total)}
              </dd>
              <p className="mt-0.5 text-[11px] text-muted-foreground">
                {formatNumber(summary.schema_fields_resolved)} resolved
              </p>
            </div>
            <div className="rounded-lg border border-border bg-muted/15 p-3">
              <dt className="text-[11px] uppercase tracking-wide text-muted-foreground">
                Unresolved
              </dt>
              <dd className="mt-1 text-xl font-semibold tabular-nums">
                {formatNumber(summary.unresolved_total)}
              </dd>
              <p className="mt-0.5 text-[11px] text-muted-foreground">
                {formatNumber(summary.lists_detected)} lists ·{" "}
                {formatNumber(summary.conditions_detected)} conditions
              </p>
            </div>
          </dl>

          <div className="grid gap-3 lg:grid-cols-2">
            <div className="space-y-2">
              <ReferenceCoverageBar ratio={summary.edge_coverage_ratio} label="Edge coverage" />
              <ReferenceCoverageBar
                ratio={summary.evidence_coverage_ratio}
                label={`Schema evidence coverage (${formatNumber(summary.resolves_to_with_evidence)}/${formatNumber(summary.resolves_to_edges)} resolves_to edges)`}
              />
              <div>
                <p className="mb-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                  Nodes by kind
                </p>
                <CountChips counts={summary.by_node_kind} labels={NODE_KIND_LABELS} />
              </div>
              <div>
                <p className="mb-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                  Edges by type
                </p>
                <CountChips counts={summary.by_edge_type} labels={EDGE_TYPE_LABELS} />
              </div>
            </div>
            <div className="space-y-2">
              <div>
                <p className="mb-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                  Nodes by status
                </p>
                <CountChips
                  counts={summary.by_node_status}
                  labels={{ resolved: "Resolved", ambiguous: "Ambiguous", unknown: "Unknown" }}
                />
              </div>
              <div>
                <p className="mb-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                  Edges by status
                </p>
                <CountChips
                  counts={summary.by_edge_status}
                  labels={{ resolved: "Resolved", ambiguous: "Ambiguous", unknown: "Unknown" }}
                />
              </div>
              <div>
                <p className="mb-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                  Unresolved binding statuses
                </p>
                <CountChips
                  counts={summary.unresolved_by_status}
                  labels={BINDING_STATUS_LABELS}
                />
              </div>
              <p className="text-[11px] leading-5 text-muted-foreground">{graph.note}</p>
              {graph.schema_provider_types.length > 0 ? (
                <p className="break-all font-mono text-[10px] text-muted-foreground">
                  providers: {graph.schema_provider_types.join(", ")}
                </p>
              ) : null}
              {graph.schema_ids.length > 0 ? (
                <p className="break-all font-mono text-[10px] text-muted-foreground">
                  schema ids: {graph.schema_ids.join(", ")}
                </p>
              ) : null}
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Unresolved</CardTitle>
          <CardDescription>
            Every unresolved node with its explicit reason. Nothing is silently dropped from the
            graph.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {graph.unresolved.length === 0 ? (
            <p className="text-xs text-muted-foreground">
              No unresolved nodes were recorded for this graph.
            </p>
          ) : (
            <ul className="space-y-1.5">
              {unresolved.map((item) => (
                <li
                  key={item.node_id}
                  className="rounded-md border border-border bg-card px-2.5 py-2"
                >
                  <div className="flex flex-wrap items-center gap-1.5">
                    <NodeKindBadge kind={item.kind} />
                    <span className="min-w-0 break-words text-xs font-medium text-foreground">
                      {item.label}
                    </span>
                    <GraphStatusBadge status={item.status} />
                    <Badge variant="warning" className="font-mono">
                      {item.reason}
                    </Badge>
                  </div>
                  <code className="mt-1 block break-all font-mono text-[10px] text-muted-foreground">
                    {item.node_id}
                  </code>
                </li>
              ))}
            </ul>
          )}
          {graph.unresolved.length > GRAPH_UNRESOLVED_INITIAL ? (
            <Button
              type="button"
              size="sm"
              variant="outline"
              className="mt-2"
              onClick={() => setShowAllUnresolved((current) => !current)}
              aria-label={
                showAllUnresolved
                  ? "Show fewer unresolved nodes"
                  : `Show all ${graph.unresolved.length} unresolved nodes`
              }
            >
              {showAllUnresolved
                ? "Show fewer"
                : `Show all ${graph.unresolved.length} unresolved nodes`}
            </Button>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <ListTree aria-hidden="true" className="h-4 w-4 text-muted-foreground" />
            Nodes by section / part
          </CardTitle>
          <CardDescription>
            A compact tree of the graph grouped by document part. Each row lists outgoing edges,
            their target and the edge status.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {graph.nodes.length === 0 ? (
            <EmptyState
              icon={GitBranch}
              title="No graph nodes"
              description="The inspected source did not produce any control, element, source or schema-field nodes. Upload a reference DOCX with ProjectData and an optional DDSP schema."
            />
          ) : (
            <div className="space-y-3">
              {groups.map((group) => (
                <GraphGroupSection
                  key={group.key}
                  group={group}
                  edgesBySource={edgesBySource}
                  nodesById={nodesById}
                />
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border bg-muted/15 px-3 py-2 text-[11px] text-muted-foreground">
        <span>
          Graph digest {truncateMiddle(graph.graph_digest, 12, 8)} · edge coverage{" "}
          {formatRatio(summary.edge_coverage_ratio)}. Runtime compatibility: not tested.
        </span>
      </div>
    </div>
  );
}
