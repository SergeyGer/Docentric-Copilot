"use client";

import { AlertCircle, CheckCircle2, Info, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { ToastState } from "@/hooks/use-workspace";
import { cn } from "@/lib/utils";

const TONE_STYLE = {
  info: {
    icon: Info,
    iconClass: "text-info",
    borderClass: "border-info/30",
  },
  success: {
    icon: CheckCircle2,
    iconClass: "text-success",
    borderClass: "border-success/30",
  },
  error: {
    icon: AlertCircle,
    iconClass: "text-destructive",
    borderClass: "border-destructive/30",
  },
} as const;

export interface WorkspaceToastProps {
  toast: ToastState | null;
  onDismiss: () => void;
}

export function WorkspaceToast({ toast, onDismiss }: WorkspaceToastProps) {
  if (!toast) {
    return null;
  }
  const style = TONE_STYLE[toast.tone];
  const Icon = style.icon;
  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-4 z-50 flex justify-center px-4 sm:justify-end sm:px-6">
      <div
        role="status"
        aria-live="polite"
        className={cn(
          "pointer-events-auto flex w-full max-w-sm items-start gap-3 rounded-lg border bg-card p-3 shadow-lg animate-fade-in",
          style.borderClass,
        )}
      >
        <Icon aria-hidden="true" className={cn("mt-0.5 h-4 w-4 shrink-0", style.iconClass)} />
        <p className="min-w-0 flex-1 break-words text-xs leading-5 text-foreground">
          {toast.message}
        </p>
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          onClick={onDismiss}
          aria-label="Dismiss notification"
          className="-mr-1 -mt-1 text-muted-foreground hover:text-foreground"
        >
          <X aria-hidden="true" />
        </Button>
      </div>
    </div>
  );
}
