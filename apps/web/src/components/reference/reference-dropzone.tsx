"use client";

import { useRef, useState, type DragEvent } from "react";
import { FileText, UploadCloud, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { formatBytes } from "@/lib/format";
import { cn } from "@/lib/utils";

export interface ReferenceDropzoneProps {
  id: string;
  label: string;
  description: string;
  accept: string;
  file: File | null;
  onFileChange: (file: File | null) => void;
  disabled?: boolean;
  optional?: boolean;
  limitBytes?: number | null;
  className?: string;
}

/**
 * Drag-and-drop plus a keyboard-operable file picker. Extension and size policy
 * are enforced by the API (and pre-checked by the caller), so every dropped file
 * is still surfaced by name and size before inspection starts.
 */
export function ReferenceDropzone({
  id,
  label,
  description,
  accept,
  file,
  onFileChange,
  disabled = false,
  optional = false,
  limitBytes = null,
  className,
}: ReferenceDropzoneProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const labelId = `${id}-label`;
  const descriptionId = `${id}-description`;
  const limitId = `${id}-limit`;

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    if (disabled) {
      return;
    }
    const dropped = event.dataTransfer.files?.[0];
    if (dropped) {
      onFileChange(dropped);
    }
  };

  return (
    <div
      role="group"
      aria-labelledby={labelId}
      aria-describedby={`${descriptionId} ${limitId}`}
      className={cn("min-w-0", className)}
    >
      <div className="mb-1.5 flex items-baseline justify-between gap-2">
        <p id={labelId} className="text-xs font-semibold text-foreground">
          {label}
          {optional ? (
            <span className="ml-1 text-[11px] font-normal text-muted-foreground">(optional)</span>
          ) : null}
        </p>
      </div>
      <div
        onDragOver={(event) => {
          event.preventDefault();
          if (!disabled) {
            setDragging(true);
          }
        }}
        onDragEnter={(event) => {
          event.preventDefault();
          if (!disabled) {
            setDragging(true);
          }
        }}
        onDragLeave={(event) => {
          if (event.currentTarget.contains(event.relatedTarget as Node | null)) {
            return;
          }
          setDragging(false);
        }}
        onDrop={handleDrop}
        aria-busy={disabled}
        className={cn(
          "flex flex-col items-start gap-2 rounded-lg border border-dashed border-border bg-muted/20 px-3 py-3 transition-colors",
          dragging && "border-primary bg-primary/5",
          disabled && "opacity-60",
        )}
      >
        <div className="flex items-start gap-2">
          <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-card text-muted-foreground shadow-sm">
            <UploadCloud aria-hidden="true" className="h-3.5 w-3.5" />
          </span>
          <div className="min-w-0">
            <p className="text-xs leading-5 text-foreground">
              Drag and drop, or choose a file.
            </p>
            <p id={descriptionId} className="text-[11px] leading-4 text-muted-foreground">
              {description}
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => inputRef.current?.click()}
            disabled={disabled}
            aria-describedby={`${descriptionId} ${limitId}`}
          >
            <FileText aria-hidden="true" />
            {file ? `Replace ${label.toLocaleLowerCase()}` : `Choose ${label.toLocaleLowerCase()}`}
          </Button>
          <span className="font-mono text-[10px] text-muted-foreground">Accepted: {accept}</span>
        </div>
        <p id={limitId} className="text-[10px] leading-4 text-muted-foreground">
          {limitBytes && limitBytes > 0
            ? `Maximum upload size: ${formatBytes(limitBytes)}. Larger files are rejected by the API.`
            : "The API applies its configured upload size limit."}
        </p>
        <input
          ref={inputRef}
          id={id}
          type="file"
          accept={accept}
          disabled={disabled}
          className="sr-only"
          aria-labelledby={labelId}
          aria-describedby={`${descriptionId} ${limitId}`}
          onChange={(event) => {
            const selected = event.target.files?.[0] ?? null;
            event.target.value = "";
            if (selected) {
              onFileChange(selected);
            }
          }}
        />
      </div>

      {file ? (
        <div className="mt-2 flex items-center gap-2 rounded-md border border-border bg-card px-2.5 py-2">
          <FileText aria-hidden="true" className="h-4 w-4 shrink-0 text-primary" />
          <div className="min-w-0 flex-1">
            <p className="truncate text-xs font-medium text-foreground" title={file.name}>
              {file.name}
            </p>
            <p className="text-[11px] text-muted-foreground">
              {formatBytes(file.size)}
              {file.type ? ` · ${file.type}` : " · type not reported"}
            </p>
          </div>
          <Button
            type="button"
            size="icon-sm"
            variant="ghost"
            onClick={() => onFileChange(null)}
            disabled={disabled}
            aria-label={`Remove ${label.toLocaleLowerCase()} file`}
            title={`Remove ${label.toLocaleLowerCase()}`}
            className="text-muted-foreground hover:text-foreground"
          >
            <X aria-hidden="true" />
          </Button>
        </div>
      ) : null}
    </div>
  );
}
