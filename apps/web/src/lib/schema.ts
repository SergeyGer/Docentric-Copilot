/** Normalized-schema traversal used by the explorer and the mapping review. */

import type { DataType, NormalizedSchema, SchemaNode } from "@/lib/types";

export type NodeKind = DataType | "object";

export interface SchemaTreeRow {
  node: SchemaNode;
  depth: number;
  sectionName: string;
  parentPath: string | null;
  hasChildren: boolean;
  expanded: boolean;
}

export interface SchemaSectionTree {
  name: string;
  source: string | null;
  nodeCount: number;
  rows: SchemaTreeRow[];
}

export interface SchemaTreeResult {
  sections: SchemaSectionTree[];
  /** Number of nodes whose name, path or data type matches the filter. */
  matchCount: number;
  /** Number of node rows currently visible (after expansion and filtering). */
  visibleCount: number;
  totalPaths: number;
}

const KNOWN_TYPES: readonly string[] = [
  "string",
  "number",
  "boolean",
  "date",
  "image",
  "collection",
  "any",
];

export function nodeKind(node: SchemaNode): NodeKind {
  if (node.collection) {
    return "collection";
  }
  if (node.children.length > 0) {
    return "object";
  }
  if (node.data_type && KNOWN_TYPES.includes(node.data_type)) {
    return node.data_type as DataType;
  }
  return "any";
}

export function countSchemaNodes(nodes: SchemaNode[]): number {
  let count = 0;
  const stack = [...nodes];
  while (stack.length > 0) {
    const node = stack.pop();
    if (!node) {
      continue;
    }
    count += 1;
    stack.push(...node.children);
  }
  return count;
}

export function indexSchemaNodes(schema: NormalizedSchema | null): Map<string, SchemaNode> {
  const index = new Map<string, SchemaNode>();
  if (!schema) {
    return index;
  }
  const stack = schema.sections.flatMap((section) => [...section.nodes]);
  while (stack.length > 0) {
    const node = stack.pop();
    if (!node) {
      continue;
    }
    index.set(node.path, node);
    stack.push(...node.children);
  }
  return index;
}

export function findSchemaNode(
  schema: NormalizedSchema | null,
  path: string | null,
): SchemaNode | null {
  if (!schema || !path) {
    return null;
  }
  const stack = schema.sections.flatMap((section) => [...section.nodes]);
  while (stack.length > 0) {
    const node = stack.pop();
    if (!node) {
      continue;
    }
    if (node.path === path) {
      return node;
    }
    stack.push(...node.children);
  }
  return null;
}

function normalizeQuery(query: string): string {
  return query.trim().toLowerCase();
}

function nodeMatches(node: SchemaNode, query: string): boolean {
  return (
    node.name.toLowerCase().includes(query) ||
    node.path.toLowerCase().includes(query) ||
    node.data_type.toLowerCase().includes(query)
  );
}

function hasMatchInSubtree(
  node: SchemaNode,
  query: string,
  cache: Map<string, boolean>,
): boolean {
  const cached = cache.get(node.path);
  if (cached !== undefined) {
    return cached;
  }
  const result = nodeMatches(node, query) || node.children.some((child) => hasMatchInSubtree(child, query, cache));
  cache.set(node.path, result);
  return result;
}

/**
 * Flatten the schema into the rows the explorer renders.
 *
 * When a filter is active it overrides manual expansion: ancestors of matches
 * are opened so every match is visible, and a matching container shows its whole
 * subtree. With an empty query, only rows under expanded containers are shown.
 */
export function buildSchemaTree(
  schema: NormalizedSchema | null,
  expanded: ReadonlySet<string>,
  query: string,
): SchemaTreeResult {
  if (!schema) {
    return { sections: [], matchCount: 0, visibleCount: 0, totalPaths: 0 };
  }

  const normalized = normalizeQuery(query);
  const filtering = normalized.length > 0;
  const matchCache = new Map<string, boolean>();

  let totalPaths = 0;
  let matchCount = 0;
  for (const section of schema.sections) {
    for (const node of section.nodes) {
      const stack = [node];
      while (stack.length > 0) {
        const current = stack.pop();
        if (!current) {
          continue;
        }
        totalPaths += 1;
        if (filtering && nodeMatches(current, normalized)) {
          matchCount += 1;
        }
        stack.push(...current.children);
      }
    }
  }

  const sections: SchemaSectionTree[] = [];
  for (const section of schema.sections) {
    const rows: SchemaTreeRow[] = [];

    const visit = (
      nodes: SchemaNode[],
      depth: number,
      parentPath: string | null,
      insideMatch: boolean,
    ): void => {
      for (const node of nodes) {
        const hasChildren = node.children.length > 0;

        if (filtering) {
          const selfMatches = nodeMatches(node, normalized);
          const branchMatches = selfMatches || hasMatchInSubtree(node, normalized, matchCache);
          if (!insideMatch && !branchMatches) {
            continue;
          }
          rows.push({
            node,
            depth,
            sectionName: section.name,
            parentPath,
            hasChildren,
            expanded: hasChildren,
          });
          if (hasChildren) {
            visit(node.children, depth + 1, node.path, insideMatch || selfMatches);
          }
          continue;
        }

        const isExpanded = hasChildren && expanded.has(node.path);
        rows.push({
          node,
          depth,
          sectionName: section.name,
          parentPath,
          hasChildren,
          expanded: isExpanded,
        });
        if (hasChildren && isExpanded) {
          visit(node.children, depth + 1, node.path, false);
        }
      }
    };

    visit(section.nodes, 0, null, false);

    if (!filtering || rows.length > 0) {
      sections.push({
        name: section.name,
        source: section.source,
        nodeCount: countSchemaNodes(section.nodes),
        rows,
      });
    }
  }

  return {
    sections,
    matchCount: filtering ? matchCount : 0,
    visibleCount: sections.reduce((sum, section) => sum + section.rows.length, 0),
    totalPaths,
  };
}

/**
 * Initial expansion: everything for small schemas (great for demos) and the
 * top-level containers for larger ones.
 */
export function defaultExpandedPaths(schema: NormalizedSchema | null): Set<string> {
  if (!schema) {
    return new Set();
  }
  let total = 0;
  const expandable: string[] = [];
  for (const section of schema.sections) {
    const stack = [...section.nodes];
    while (stack.length > 0) {
      const node = stack.pop();
      if (!node) {
        continue;
      }
      total += 1;
      if (node.children.length > 0) {
        expandable.push(node.path);
      }
      stack.push(...node.children);
    }
  }
  if (total <= 48) {
    return new Set(expandable);
  }
  const topLevel: string[] = [];
  for (const section of schema.sections) {
    for (const node of section.nodes) {
      if (node.children.length > 0) {
        topLevel.push(node.path);
      }
    }
  }
  return new Set(topLevel);
}

/** Every path with children, used by the explorer's "Expand all" action. */
export function allExpandablePaths(schema: NormalizedSchema | null): Set<string> {
  if (!schema) {
    return new Set();
  }
  const paths: string[] = [];
  for (const section of schema.sections) {
    const stack = [...section.nodes];
    while (stack.length > 0) {
      const node = stack.pop();
      if (!node) {
        continue;
      }
      if (node.children.length > 0) {
        paths.push(node.path);
      }
      stack.push(...node.children);
    }
  }
  return new Set(paths);
}
