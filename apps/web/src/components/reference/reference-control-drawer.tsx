"use client";

import { useEffect, useId, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";

import {
  ClassificationBadge,
  ElementKindBadge,
  ResolutionBadge,
} from "@/components/reference/reference-badges";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { CopyButton } from "@/components/workspace/copy-button";
import { prettyJson } from "@/lib/format";
import {
  CONTROL_TYPE_LABELS,
  ELEMENT_KIND_LABELS,
  LINK_STATUS_LABELS,
  PATH_STATUS_LABELS,
  PLATFORM_LABELS,
  SCHEMA_SOURCE_LABELS,
  STORY_LABELS,
  referenceControlLabel,
  referenceEnumLabel,
} from "@/lib/reference";
import type { ReferenceControlRow } from "@/lib/reference";

const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), iframe, [tabindex]:not([tabindex="-1"])';

function MonoValue({ value }: { value: string | null }) {
  if (!value) {
    return <span className="text-muted-foreground">—</span>;
  }
  return (
    <span className="inline-flex min-w-0 items-start gap-1">
      <code className="break-all font-mono text-[11px] leading-5 text-foreground">{value}</code>
      <CopyButton value={value} label="Copy value" />
    </span>
  );
}

function DetailItem({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div className="min-w-0">
      <dt className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </dt>
      <dd className="mt-0.5 break-words text-xs leading-5 text-foreground">{children}</dd>
    </div>
  );
}

function DrawerSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-2 border-t border-border pt-3 first:border-t-0 first:pt-0">
      <h3 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </h3>
      {children}
    </section>
  );
}

export interface ReferenceControlDrawerProps {
  row: ReferenceControlRow | null;
  onClose: () => void;
}

/**
 * Side drawer with the complete, non-executed evidence for one control: raw
 * `w:dataBinding`, resolution evidence and the exact source location. Focus is
 * moved into the drawer, trapped while open and restored on close.
 */
export function ReferenceControlDrawer({ row, onClose }: ReferenceControlDrawerProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const titleId = useId();

  useEffect(() => {
    if (!row) {
      return;
    }
    const previous =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const focusTimer = window.setTimeout(() => closeRef.current?.focus(), 0);

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== "Tab") {
        return;
      }
      const panel = panelRef.current;
      if (!panel) {
        return;
      }
      const focusable = Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR));
      if (focusable.length === 0) {
        event.preventDefault();
        panel.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.body.style.overflow = previousOverflow;
      window.clearTimeout(focusTimer);
      previous?.focus({ preventScroll: true });
    };
  }, [onClose, row]);

  if (!row) {
    return null;
  }

  const { control } = row;
  const documentEvidence = row.document;
  const resolution = control.resolution;
  const rawBinding = control.data_binding;

  return createPortal(
    <div
      className="fixed inset-0 z-[65] flex justify-end bg-slate-950/50"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) {
          onClose();
        }
      }}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className="scroll-area flex h-full w-full max-w-xl flex-col border-l border-border bg-card shadow-2xl outline-none"
      >
        <div className="sticky top-0 z-10 flex items-start justify-between gap-3 border-b border-border bg-card/95 px-4 py-3 backdrop-blur">
          <div className="min-w-0">
            <h2 id={titleId} className="truncate text-sm font-semibold text-foreground">
              {referenceControlLabel(control)}
            </h2>
            <p className="mt-0.5 break-all text-[11px] text-muted-foreground">
              Control {control.ordinal} · {control.part} · paragraph {control.paragraph_index}
            </p>
            <div className="mt-1.5 flex flex-wrap gap-1">
              <ClassificationBadge classification={control.classification} />
              <ResolutionBadge status={resolution.status} />
              <ElementKindBadge kind={control.element_kind} />
              <Badge variant="outline">
                {referenceEnumLabel(STORY_LABELS, control.story)}
              </Badge>
            </div>
          </div>
          <Button
            ref={closeRef}
            type="button"
            size="icon-sm"
            variant="ghost"
            onClick={onClose}
            aria-label="Close control details"
            className="-mr-1 shrink-0 text-muted-foreground hover:text-foreground"
          >
            <X aria-hidden="true" />
          </Button>
        </div>

        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-4">
          <DrawerSection title="Source location">
            <dl className="grid gap-x-4 gap-y-2 sm:grid-cols-2">
              <DetailItem label="Document">{documentEvidence.filename}</DetailItem>
              <DetailItem label="Document SHA-256">
                <span className="inline-flex items-center gap-1">
                  <code className="break-all font-mono text-[11px]">{documentEvidence.sha256}</code>
                  <CopyButton value={documentEvidence.sha256} label="Copy document SHA-256" />
                </span>
              </DetailItem>
              <DetailItem label="Part">
                <code className="break-all font-mono text-[11px]">{control.part}</code>
              </DetailItem>
              <DetailItem label="Story">
                {referenceEnumLabel(STORY_LABELS, control.story)}
              </DetailItem>
              <DetailItem label="Paragraph index">
                <span className="font-mono">{control.paragraph_index}</span>
              </DetailItem>
              <DetailItem label="Nesting depth">
                <span className="font-mono">{control.depth}</span>
              </DetailItem>
              <DetailItem label="SDT id (signed)">
                <span className="font-mono">
                  {control.sdt_id_signed === null ? "—" : control.sdt_id_signed}
                </span>
              </DetailItem>
              <DetailItem label="SDT id (unsigned)">
                <MonoValue value={control.sdt_id_unsigned} />
              </DetailItem>
              <DetailItem label="Control type">
                {referenceEnumLabel(CONTROL_TYPE_LABELS, control.control_type)}
              </DetailItem>
              <DetailItem label="Element kind">
                {referenceEnumLabel(ELEMENT_KIND_LABELS, control.element_kind)}
              </DetailItem>
              <DetailItem label="Tag / alias">
                <MonoValue value={control.tag ?? control.alias} />
              </DetailItem>
              <DetailItem label="Placeholder">
                <MonoValue value={control.placeholder} />
              </DetailItem>
              <DetailItem label="Platform hint">
                {referenceEnumLabel(PLATFORM_LABELS, documentEvidence.platform)}
              </DetailItem>
              <DetailItem label="Product version">
                <MonoValue value={documentEvidence.product_version} />
              </DetailItem>
            </dl>
            {control.text_preview ? (
              <div>
                <p className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
                  Text preview
                </p>
                <p className="mt-0.5 break-words rounded-md border border-border bg-muted/20 px-2 py-1.5 font-mono text-[11px] leading-5 text-foreground">
                  {control.text_preview}
                </p>
              </div>
            ) : null}
          </DrawerSection>

          <DrawerSection title="Classification evidence">
            <dl className="grid gap-x-4 gap-y-2 sm:grid-cols-2">
              <DetailItem label="Classification">
                <ClassificationBadge classification={control.classification} />
              </DetailItem>
              <DetailItem label="Reason">
                <MonoValue value={control.classification_reason} />
              </DetailItem>
              <DetailItem label="Docentric namespace">
                {control.has_dc_namespace ? "Detected" : "Not detected"}
              </DetailItem>
              <DetailItem label="Namespaces">
                {control.dc_namespaces.length > 0
                  ? control.dc_namespaces.join(", ")
                  : "None recorded"}
              </DetailItem>
            </dl>
            <div>
              <p className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
                Markers
              </p>
              {control.markers.length > 0 ? (
                <ul className="mt-1 flex flex-wrap gap-1.5">
                  {control.markers.map((marker) => (
                    <li key={marker}>
                      <Badge variant="outline" className="font-mono">
                        {marker}
                      </Badge>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="mt-0.5 text-xs text-muted-foreground">No markers recorded.</p>
              )}
            </div>
          </DrawerSection>

          <DrawerSection title="Raw databinding (w:dataBinding)">
            <dl className="grid gap-x-4 gap-y-2 sm:grid-cols-2">
              <DetailItem label="xpath">
                <MonoValue value={rawBinding.xpath} />
              </DetailItem>
              <DetailItem label="storeItemID">
                <MonoValue value={rawBinding.store_item_id} />
              </DetailItem>
              <DetailItem label="prefixMappings">
                <MonoValue value={rawBinding.prefix_mappings} />
              </DetailItem>
            </dl>
            <details className="rounded-md border border-border bg-muted/15 p-2">
              <summary className="cursor-pointer text-[11px] font-medium text-foreground">
                Raw databinding JSON (never evaluated)
              </summary>
              <pre className="scroll-area mt-2 max-h-48 overflow-auto rounded bg-card p-2 font-mono text-[11px] leading-5 text-foreground">
                {prettyJson(rawBinding)}
              </pre>
            </details>
          </DrawerSection>

          <DrawerSection title="Resolution evidence">
            <div className="flex flex-wrap gap-1.5">
              <ResolutionBadge status={resolution.status} />
              <Badge variant="outline">
                Link: {referenceEnumLabel(LINK_STATUS_LABELS, resolution.link_status)}
              </Badge>
              <Badge variant="outline">
                Path: {referenceEnumLabel(PATH_STATUS_LABELS, resolution.path_status)}
              </Badge>
              <Badge variant="outline">
                {referenceEnumLabel(SCHEMA_SOURCE_LABELS, resolution.schema_source)}
              </Badge>
            </div>
            <dl className="grid gap-x-4 gap-y-2 sm:grid-cols-2">
              <DetailItem label="Element id">
                <MonoValue value={resolution.element_id_unsigned} />
              </DetailItem>
              <DetailItem label="Element type">
                <MonoValue value={resolution.element_type} />
              </DetailItem>
              <DetailItem label="Normalized path">
                <MonoValue value={resolution.normalized_path} />
              </DetailItem>
              <DetailItem label="Schema section">
                <MonoValue value={resolution.schema_section} />
              </DetailItem>
            </dl>
            {resolution.diagnostic_codes.length > 0 ? (
              <div>
                <p className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
                  Diagnostic codes
                </p>
                <ul className="mt-1 flex flex-wrap gap-1.5">
                  {resolution.diagnostic_codes.map((code) => (
                    <li key={code}>
                      <Badge variant="warning" className="font-mono">
                        {code}
                      </Badge>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
            {resolution.path_suggestions.length > 0 ? (
              <div>
                <p className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
                  Path suggestions
                </p>
                <ul className="mt-1 space-y-1">
                  {resolution.path_suggestions.map((suggestion) => (
                    <li
                      key={suggestion}
                      className="break-all rounded border border-border bg-muted/15 px-2 py-1 font-mono text-[11px] text-foreground"
                    >
                      {suggestion}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </DrawerSection>

          <DrawerSection title="Bindings">
            <dl className="grid gap-x-4 gap-y-2 sm:grid-cols-2">
              <DetailItem label="Resolved source binding">
                <pre className="scroll-area max-h-40 overflow-auto rounded border border-border bg-muted/15 p-2 font-mono text-[11px] leading-5">
                  {resolution.source_binding ? prettyJson(resolution.source_binding) : "—"}
                </pre>
              </DetailItem>
              <DetailItem label="Raw metadata binding">
                <pre className="scroll-area max-h-40 overflow-auto rounded border border-border bg-muted/15 p-2 font-mono text-[11px] leading-5">
                  {resolution.source_binding_raw
                    ? prettyJson(resolution.source_binding_raw)
                    : "—"}
                </pre>
              </DetailItem>
            </dl>
          </DrawerSection>

          <p className="rounded-md border border-amber-300/70 bg-amber-50 px-2.5 py-2 text-[11px] leading-5 text-amber-950">
            Raw binding text is untrusted reference data. It is displayed for evidence only and is
            never evaluated. Docentric AX runtime compatibility: not tested.
          </p>
        </div>
      </div>
    </div>,
    document.body,
  );
}
