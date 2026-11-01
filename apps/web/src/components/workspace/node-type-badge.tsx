import { nodeKind, type NodeKind } from "@/lib/schema";
import type { SchemaNode } from "@/lib/types";
import { Badge } from "@/components/ui/badge";

const KIND_STYLE: Record<NodeKind, { label: string; className: string }> = {
  string: {
    label: "string",
    className: "border-sky-200 bg-sky-50 text-sky-700",
  },
  number: {
    label: "number",
    className: "border-violet-200 bg-violet-50 text-violet-700",
  },
  boolean: {
    label: "boolean",
    className: "border-amber-200 bg-amber-50 text-amber-700",
  },
  date: {
    label: "date",
    className: "border-cyan-200 bg-cyan-50 text-cyan-700",
  },
  image: {
    label: "image",
    className: "border-fuchsia-200 bg-fuchsia-50 text-fuchsia-700",
  },
  collection: {
    label: "collection",
    className: "border-indigo-200 bg-indigo-50 text-indigo-700",
  },
  object: {
    label: "object",
    className: "border-slate-200 bg-slate-50 text-slate-600",
  },
  any: {
    label: "any",
    className: "border-border bg-muted text-muted-foreground",
  },
};

export function NodeTypeBadge({ node }: { node: SchemaNode }) {
  const kind = nodeKind(node);
  const style = KIND_STYLE[kind];
  return (
    <Badge variant="outline" className={style.className} title={`Data type: ${kind}`}>
      {style.label}
    </Badge>
  );
}
