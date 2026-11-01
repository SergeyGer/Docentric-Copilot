"use client";

import { useEffect, useRef, useState } from "react";
import { Check, Copy } from "lucide-react";

import { Button } from "@/components/ui/button";
import { copyToClipboard } from "@/lib/clipboard";
import { cn } from "@/lib/utils";

export interface CopyButtonProps {
  value: string;
  label?: string;
  className?: string;
  size?: "icon-sm" | "sm";
  onCopied?: () => void;
  onFailed?: () => void;
}

export function CopyButton({
  value,
  label = "Copy",
  className,
  size = "icon-sm",
  onCopied,
  onFailed,
}: CopyButtonProps) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      if (timer.current) {
        clearTimeout(timer.current);
      }
    },
    [],
  );

  const handleCopy = async () => {
    const succeeded = await copyToClipboard(value);
    if (!succeeded) {
      onFailed?.();
      return;
    }
    setCopied(true);
    onCopied?.();
    if (timer.current) {
      clearTimeout(timer.current);
    }
    timer.current = setTimeout(() => setCopied(false), 1_800);
  };

  const iconOnly = size === "icon-sm";

  return (
    <Button
      type="button"
      variant="ghost"
      size={size}
      onClick={() => {
        void handleCopy();
      }}
      aria-label={copied ? "Copied" : label}
      title={copied ? "Copied" : label}
      className={cn(
        "shrink-0 text-muted-foreground hover:text-foreground",
        copied && "text-success hover:text-success",
        className,
      )}
    >
      {copied ? (
        <Check aria-hidden="true" className="h-3.5 w-3.5" />
      ) : (
        <Copy aria-hidden="true" className="h-3.5 w-3.5" />
      )}
      {iconOnly ? null : <span>{copied ? "Copied" : label}</span>}
    </Button>
  );
}
