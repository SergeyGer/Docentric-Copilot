"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent } from "react";
import {
  ChevronRight,
  ChevronsDownUp,
  ChevronsUpDown,
  CornerDownLeft,
  Copy,
  ListTree,
  Loader2,
  MousePointerClick,
  RefreshCw,
  Search,
  X,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/workspace/empty-state";
import { ErrorAlert } from "@/components/workspace/error-alert";
import { NodeTypeBadge } from "@/components/workspace/node-type-badge";
import { Panel } from "@/components/workspace/panel";
import type { ApiError } from "@/lib/api";
import { PANEL_IDS } from "@/lib/constants";
import { formatNumber } from "@/lib/format";
import {
  allExpandablePaths,
  buildSchemaTree,
  defaultExpandedPaths,
  findSchemaNode,
  nodeKind,
  schemaAncestorPaths,
  type SchemaTreeRow,
} from "@/lib/schema";
import type { SchemaNode, SchemaView } from "@/lib/types";
import { cn } from "@/lib/utils";

interface SchemaDetailProps {
  node: SchemaNode;
  onCopyPath: (path: string) => void;
  onInsertPath: (path: string) => void;
}

function SchemaDetail({ node, onCopyPath, onInsertPath }: SchemaDetailProps) {
  const kind = nodeKind(node);
  return (
    <div className="flex h-full flex-col rounded-lg border bg-muted/20 p-4">
      <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
        Selected field
      </p>
      <p className="mt-1 break-all font-mono text-xs font-medium leading-5 text-foreground">
        {node.path}
      </p>
      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        <NodeTypeBadge node={node} />
        {node.required ? <Badge variant="destructive">required</Badge> : null}
        {node.collection ? <Badge variant="secondary">one item per repeat</Badge> : null}
        {node.children.length > 0 ? (
          <Badge variant="outline">{node.children.length} children</Badge>
        ) : null}
        {node.attributes.length > 0 ? (
          <Badge variant="outline">{node.attributes.length} attributes</Badge>
        ) : null}
      </div>

      <dl className="mt-3 space-y-2 text-xs">
        <div>
          <dt className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
            Declared type
          </dt>
          <dd className="font-mono text-foreground">{node.data_type}</dd>
        </div>
        {node.description ? (
          <div>
            <dt className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
              Description
            </dt>
            <dd className="text-foreground">{node.description}</dd>
          </div>
        ) : null}
        {node.source ? (
          <div>
            <dt className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
              Source
            </dt>
            <dd className="break-all font-mono text-[11px] text-muted-foreground">{node.source}</dd>
          </div>
        ) : null}
      </dl>

      {node.attributes.length > 0 ? (
        <Collapsible className="mt-3 rounded-md border bg-card px-2.5 py-2">
          <CollapsibleTrigger className="text-xs text-muted-foreground hover:text-foreground">
            Attributes ({node.attributes.length})
          </CollapsibleTrigger>
          <CollapsibleContent>
            <ul className="space-y-1">
              {node.attributes.map((attribute) => (
                <li key={attribute.name} className="flex flex-wrap items-baseline gap-1.5 text-[11px]">
                  <code className="font-mono text-foreground">{attribute.name}</code>
                  <span className="text-muted-foreground">{attribute.data_type}</span>
                </li>
              ))}
            </ul>
          </CollapsibleContent>
        </Collapsible>
      ) : null}

      <div className="mt-auto space-y-2 pt-4">
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => onCopyPath(node.path)}
          >
            <Copy aria-hidden="true" />
            Copy path
          </Button>
          <Button type="button" size="sm" onClick={() => onInsertPath(node.path)}>
            <CornerDownLeft aria-hidden="true" />
            Insert into prompt
          </Button>
        </div>
        <p className="text-[10px] leading-4 text-muted-foreground">
          Field type: {kind}. Sample values are deliberately not displayed.
        </p>
      </div>
    </div>
  );
}

function SchemaLoading() {
  return (
    <div className="space-y-3" role="status" aria-live="polite">
      <span className="flex items-center gap-2 text-xs text-muted-foreground">
        <Loader2 aria-hidden="true" className="h-3.5 w-3.5 animate-spin" />
        Loading the normalized schema…
      </span>
      <Skeleton className="h-8 w-full" />
      <div className="space-y-1.5 rounded-lg border p-3">
        {Array.from({ length: 8 }).map((_, index) => (
          <Skeleton
            key={index}
            className="h-5"
            style={{ width: `${84 - (index % 4) * 9}%`, marginLeft: `${(index % 3) * 12}px` }}
          />
        ))}
      </div>
    </div>
  );
}

export interface SchemaExplorerProps {
  schemaView: SchemaView | null;
  hasSource: boolean;
  schemaPending: boolean;
  schemaError: ApiError | null;
  /** Absolute schema path currently hovered in the preview. */
  activePreviewPath: string | null;
  onReloadSchema: () => void;
  onDismissSchemaError: () => void;
  onCopyPath: (path: string) => void;
  onInsertPath: (path: string) => void;
}

export function SchemaExplorer({
  schemaView,
  hasSource,
  schemaPending,
  schemaError,
  activePreviewPath,
  onReloadSchema,
  onDismissSchemaError,
  onCopyPath,
  onInsertPath,
}: SchemaExplorerProps) {
  const schema = schemaView?.normalized_schema ?? null;
  const [filter, setFilter] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [focusedPath, setFocusedPath] = useState<string | null>(null);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [pendingScrollPath, setPendingScrollPath] = useState<string | null>(null);
  const rowRefs = useRef<Map<string, HTMLDivElement>>(new Map());

  useEffect(() => {
    setExpanded(defaultExpandedPaths(schema));
    setFilter("");
    setFocusedPath(null);
    setSelectedPath(null);
    setPendingScrollPath(null);
    rowRefs.current.clear();
  }, [schema]);

  // Hovering a preview value reveals the matching field in the tree.
  useEffect(() => {
    if (!activePreviewPath || !schema) {
      return;
    }
    if (!findSchemaNode(schema, activePreviewPath)) {
      return;
    }
    const ancestors = schemaAncestorPaths(schema, activePreviewPath);
    setExpanded((previous) => {
      const next = new Set(previous);
      for (const ancestor of ancestors) {
        next.add(ancestor);
      }
      return next;
    });
    setFocusedPath(activePreviewPath);
    setSelectedPath(activePreviewPath);
    setPendingScrollPath(activePreviewPath);
  }, [activePreviewPath, schema]);

  const tree = useMemo(
    () => buildSchemaTree(schema, expanded, filter),
    [expanded, filter, schema],
  );
  const rows = useMemo(() => tree.sections.flatMap((section) => section.rows), [tree]);
  const rowIndexByPath = useMemo(() => {
    const index = new Map<string, number>();
    rows.forEach((row, position) => index.set(row.node.path, position));
    return index;
  }, [rows]);
  const activePath = useMemo(() => {
    if (focusedPath && rowIndexByPath.has(focusedPath)) {
      return focusedPath;
    }
    return rows[0]?.node.path ?? null;
  }, [focusedPath, rowIndexByPath, rows]);
  const selectedNode = useMemo(
    () => findSchemaNode(schema, selectedPath),
    [schema, selectedPath],
  );
  const filtering = filter.trim().length > 0;

  useEffect(() => {
    if (!pendingScrollPath) {
      return;
    }
    const element = rowRefs.current.get(pendingScrollPath);
    if (!element) {
      return;
    }
    const scroller = element.closest<HTMLElement>(".scroll-area");
    if (scroller) {
      const elementRect = element.getBoundingClientRect();
      const scrollerRect = scroller.getBoundingClientRect();
      if (elementRect.top < scrollerRect.top) {
        scroller.scrollTop += elementRect.top - scrollerRect.top - 6;
      } else if (elementRect.bottom > scrollerRect.bottom) {
        scroller.scrollTop += elementRect.bottom - scrollerRect.bottom + 6;
      }
    }
    setPendingScrollPath(null);
  }, [pendingScrollPath, rows]);

  const registerRow = useCallback((path: string, element: HTMLDivElement | null) => {
    if (element) {
      rowRefs.current.set(path, element);
    } else {
      rowRefs.current.delete(path);
    }
  }, []);

  const focusRow = useCallback((path: string | null | undefined) => {
    if (!path) {
      return;
    }
    const element = rowRefs.current.get(path);
    if (element) {
      element.focus();
      setFocusedPath(path);
      setSelectedPath(path);
    }
  }, []);

  const togglePath = useCallback((path: string) => {
    setExpanded((previous) => {
      const next = new Set(previous);
      if (next.has(path)) {
        next.delete(path);
      } else {
        next.add(path);
      }
      return next;
    });
  }, []);

  const handleKeyDown = (
    event: KeyboardEvent<HTMLDivElement>,
    row: SchemaTreeRow,
    index: number,
  ) => {
    if (event.altKey || event.ctrlKey || event.metaKey) {
      return;
    }
    const path = row.node.path;
    switch (event.key) {
      case "ArrowDown":
        event.preventDefault();
        focusRow(rows[index + 1]?.node.path);
        break;
      case "ArrowUp":
        event.preventDefault();
        focusRow(rows[index - 1]?.node.path);
        break;
      case "Home":
        event.preventDefault();
        focusRow(rows[0]?.node.path);
        break;
      case "End":
        event.preventDefault();
        focusRow(rows[rows.length - 1]?.node.path);
        break;
      case "ArrowRight": {
        event.preventDefault();
        if (!row.hasChildren) {
          break;
        }
        if (!row.expanded) {
          togglePath(path);
        } else {
          const next = rows[index + 1];
          if (next && next.depth > row.depth) {
            focusRow(next.node.path);
          }
        }
        break;
      }
      case "ArrowLeft": {
        event.preventDefault();
        if (row.hasChildren && row.expanded && !filtering) {
          togglePath(path);
        } else if (row.parentPath) {
          focusRow(row.parentPath);
        }
        break;
      }
      case "Enter":
      case " ": {
        event.preventDefault();
        if (row.hasChildren) {
          togglePath(path);
        } else {
          setSelectedPath(path);
          onCopyPath(path);
        }
        break;
      }
      case "c":
      case "C": {
        event.preventDefault();
        setSelectedPath(path);
        onCopyPath(path);
        break;
      }
      case "i":
      case "I": {
        event.preventDefault();
        setSelectedPath(path);
        onInsertPath(path);
        break;
      }
      default:
        break;
    }
  };

  const headerActions = schema ? (
    <Badge variant="outline">{formatNumber(tree.totalPaths)} paths</Badge>
  ) : null;

  let body;
  if (!schema && schemaPending) {
    body = <SchemaLoading />;
  } else if (!schema) {
    body = (
      <EmptyState
        icon={ListTree}
        title={hasSource ? "Schema unavailable" : "No schema yet"}
        description={
          hasSource
            ? "The schema request did not return a normalized schema. Retry the request."
            : "Upload a DDSP or XML source to explore its sections and fields."
        }
      />
    );
  } else if (rows.length === 0 && !filtering) {
    body = (
      <EmptyState
        icon={ListTree}
        title="No fields in this schema"
        description="The parser did not discover any bindable fields. Check the source diagnostics."
      />
    );
  } else {
    body = (
      <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
        <div className="min-w-0">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
            <div className="relative min-w-0 flex-1">
              <Search
                aria-hidden="true"
                className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground"
              />
              <Input
                id="schema-filter"
                value={filter}
                onChange={(event) => setFilter(event.target.value)}
                placeholder="Filter by name, path or type"
                className="h-8 pl-8 pr-8 text-xs"
                aria-label="Filter schema fields"
                onKeyDown={(event) => {
                  if (event.key === "ArrowDown" && rows.length > 0) {
                    event.preventDefault();
                    focusRow(rows[0].node.path);
                  }
                  if (event.key === "Escape") {
                    setFilter("");
                  }
                }}
              />
              {filtering ? (
                <button
                  type="button"
                  onClick={() => setFilter("")}
                  aria-label="Clear schema filter"
                  className="absolute right-1.5 top-1/2 flex h-5 w-5 -translate-y-1/2 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <X aria-hidden="true" className="h-3.5 w-3.5" />
                </button>
              ) : null}
            </div>
            <div className="flex items-center gap-1">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setExpanded(allExpandablePaths(schema))}
              >
                <ChevronsUpDown aria-hidden="true" />
                Expand all
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => setExpanded(new Set())}
              >
                <ChevronsDownUp aria-hidden="true" />
                Collapse
              </Button>
            </div>
          </div>

          <div className="mt-2 flex flex-wrap items-center justify-between gap-2 px-0.5">
            <p className="text-[11px] text-muted-foreground" aria-live="polite">
              {filtering
                ? `${formatNumber(tree.matchCount)} matching fields · ${formatNumber(tree.visibleCount)} shown`
                : `${formatNumber(tree.totalPaths)} fields · ${formatNumber(tree.visibleCount)} visible`}
            </p>
            <p className="text-[10px] text-muted-foreground">
              Click a path to copy · {filtering ? "clear the filter to collapse" : "chevron expands"}
            </p>
          </div>

          <div
            role="tree"
            aria-label="Normalized schema fields"
            aria-multiselectable={false}
            className="mt-2 rounded-lg border bg-card"
          >
            <ScrollArea className="max-h-[480px] p-1">
              {rows.length === 0 ? (
                <EmptyState
                  icon={Search}
                  title={`No fields match "${filter.trim()}"`}
                  description="Try a partial path, a field name or a data type."
                  compact
                  className="m-2"
                />
              ) : (
                tree.sections.map((section) => (
                  <div
                    key={section.name}
                    role="group"
                    aria-label={`${section.name} section`}
                    className="pb-1"
                  >
                    <div
                      role="presentation"
                      className="sticky top-0 z-10 flex items-center gap-2 border-b border-border/70 bg-card/95 px-2 py-1.5 backdrop-blur"
                    >
                      <span className="font-mono text-[11px] font-semibold uppercase tracking-wide text-foreground">
                        {section.name}
                      </span>
                      <span className="text-[10px] text-muted-foreground">
                        {formatNumber(section.nodeCount)} fields
                      </span>
                    </div>
                    {section.rows.map((row) => {
                      const index = rowIndexByPath.get(row.node.path) ?? 0;
                      const isSelected = selectedPath === row.node.path;
                      const isFocused = activePath === row.node.path;
                      const isPreviewActive = activePreviewPath === row.node.path;
                      return (
                        <div
                          key={row.node.path}
                          ref={(element) => registerRow(row.node.path, element)}
                          role="treeitem"
                          aria-level={row.depth + 1}
                          aria-expanded={row.hasChildren ? row.expanded : undefined}
                          aria-selected={isSelected}
                          data-preview-active={isPreviewActive ? "true" : undefined}
                          tabIndex={isFocused ? 0 : -1}
                          title={row.node.path}
                          style={{ paddingLeft: `${8 + row.depth * 16}px` }}
                          onClick={() => {
                            setSelectedPath(row.node.path);
                            setFocusedPath(row.node.path);
                            onCopyPath(row.node.path);
                          }}
                          onFocus={() => {
                            setFocusedPath(row.node.path);
                            setSelectedPath(row.node.path);
                          }}
                          onKeyDown={(event) => handleKeyDown(event, row, index)}
                          className={cn(
                            "group flex cursor-pointer items-center gap-1 rounded-md py-1 pr-1 outline-none transition-colors",
                            isPreviewActive
                              ? "bg-info/10 ring-2 ring-inset ring-info/50"
                              : isSelected
                                ? "bg-primary/10"
                                : "hover:bg-muted/60",
                            "focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring",
                          )}
                        >
                          <button
                            type="button"
                            tabIndex={-1}
                            aria-label={
                              row.expanded
                                ? `Collapse ${row.node.name}`
                                : `Expand ${row.node.name}`
                            }
                            onClick={(event) => {
                              event.stopPropagation();
                              if (row.hasChildren) {
                                togglePath(row.node.path);
                              }
                            }}
                            className={cn(
                              "flex h-5 w-5 shrink-0 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-muted hover:text-foreground",
                              !row.hasChildren && "invisible",
                            )}
                          >
                            <ChevronRight
                              aria-hidden="true"
                              className={cn(
                                "h-3.5 w-3.5 transition-transform",
                                row.expanded && "rotate-90",
                              )}
                            />
                          </button>
                          <span className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5">
                            <span className="truncate font-mono text-xs text-foreground">
                              {row.node.name}
                            </span>
                            <NodeTypeBadge node={row.node} />
                            {row.node.required ? (
                              <span
                                className="font-semibold text-destructive"
                                title="Required field"
                                aria-label="Required field"
                              >
                                *
                              </span>
                            ) : null}
                            {row.node.attributes.length > 0 ? (
                              <Badge variant="muted" className="text-[10px]">
                                {row.node.attributes.length} attr
                              </Badge>
                            ) : null}
                          </span>
                          <span
                            className="hidden min-w-0 max-w-[42%] truncate font-mono text-[10px] text-muted-foreground md:inline"
                            title={row.node.path}
                          >
                            {row.node.path}
                          </span>
                          <button
                            type="button"
                            tabIndex={-1}
                            aria-label={`Insert ${row.node.path} into the prompt`}
                            title="Insert path into the prompt (I)"
                            onClick={(event) => {
                              event.stopPropagation();
                              setSelectedPath(row.node.path);
                              onInsertPath(row.node.path);
                            }}
                            className="ml-1 flex h-6 w-6 shrink-0 items-center justify-center rounded text-muted-foreground opacity-0 transition-all hover:bg-muted hover:text-foreground focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring group-hover:opacity-100"
                          >
                            <CornerDownLeft aria-hidden="true" className="h-3.5 w-3.5" />
                          </button>
                        </div>
                      );
                    })}
                  </div>
                ))
              )}
            </ScrollArea>
          </div>
          <p className="mt-1.5 px-0.5 text-[10px] text-muted-foreground">
            Arrow keys navigate · Enter toggles · C copies · I inserts into the prompt · Hover a
            preview value to reveal its field
          </p>
        </div>

        <aside className="min-w-0 self-start xl:sticky xl:top-36" aria-live="polite">
          {selectedNode ? (
            <SchemaDetail
              node={selectedNode}
              onCopyPath={onCopyPath}
              onInsertPath={onInsertPath}
            />
          ) : (
            <div className="flex min-h-[220px] flex-col items-center justify-center rounded-lg border border-dashed border-border bg-muted/10 p-6 text-center">
              <span className="flex h-10 w-10 items-center justify-center rounded-full bg-muted text-muted-foreground">
                <MousePointerClick aria-hidden="true" className="h-5 w-5" />
              </span>
              <p className="mt-3 text-sm font-medium text-foreground">Select a field</p>
              <p className="mt-1 max-w-xs text-xs leading-5 text-muted-foreground">
                Click a path to copy it, or use the insert action to add it to the prompt. The
                details pane shows the exact schema evidence.
              </p>
            </div>
          )}
        </aside>
      </div>
    );
  }

  return (
    <Panel
      id={PANEL_IDS.schema}
      step={2}
      title="Schema explorer"
      description="Inspect the normalized section tree. Type badges, collection markers and required markers come straight from the parsed schema."
      actions={headerActions}
    >
      {schemaError ? (
        <ErrorAlert
          error={schemaError}
          title="Schema reload failed"
          className="mb-4"
          onDismiss={onDismissSchemaError}
          action={
            <Button type="button" size="sm" variant="outline" onClick={onReloadSchema}>
              <RefreshCw aria-hidden="true" />
              Retry schema
            </Button>
          }
        />
      ) : null}
      {body}
    </Panel>
  );
}
