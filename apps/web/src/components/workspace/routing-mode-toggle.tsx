"use client";

import { useId } from "react";
import { Route, SlidersHorizontal } from "lucide-react";

import type { RoutingMode } from "@/lib/types";
import { cn } from "@/lib/utils";

export interface RoutingModeToggleProps {
  mode: RoutingMode;
  onModeChange: (mode: RoutingMode) => void;
  /** True while a plan is running: neither option can change. */
  disabled?: boolean;
  /** Auto planning needs a loaded source, so the option is unavailable without one. */
  autoDisabled: boolean;
  autoDisabledReason?: string;
}

/**
 * Two-state routing control. It is a real radio group so arrow keys, Space and
 * screen-reader semantics come from the platform; the radios are visually
 * replaced by a segmented control and keep a visible focus ring.
 */
export function RoutingModeToggle({
  mode,
  onModeChange,
  disabled = false,
  autoDisabled,
  autoDisabledReason = "Upload a data source to enable auto routing.",
}: RoutingModeToggleProps) {
  const groupId = useId();
  const labelId = `${groupId}-label`;
  const descriptionId = `${groupId}-description`;
  const autoReasonId = `${groupId}-auto-reason`;

  const options = [
    {
      value: "manual" as const,
      label: "Manual",
      Icon: SlidersHorizontal,
      unavailable: false,
      title: undefined as string | undefined,
    },
    {
      value: "auto" as const,
      label: "Auto",
      Icon: Route,
      unavailable: autoDisabled,
      title: autoDisabled ? autoDisabledReason : undefined,
    },
  ];

  return (
    <fieldset className="min-w-0 space-y-1.5" disabled={disabled}>
      <legend id={labelId} className="text-xs font-medium text-foreground">
        Routing mode
      </legend>
      <div
        role="radiogroup"
        aria-labelledby={labelId}
        aria-describedby={descriptionId}
        className="inline-flex rounded-md border border-input bg-muted/40 p-0.5"
      >
        {options.map((option) => {
          const optionDisabled = disabled || option.unavailable;
          return (
            <label
              key={option.value}
              htmlFor={`${groupId}-${option.value}`}
              title={option.title}
              className={cn("inline-flex rounded-[5px]", optionDisabled && "cursor-not-allowed")}
            >
              <input
                id={`${groupId}-${option.value}`}
                type="radio"
                name={`${groupId}-routing-mode`}
                value={option.value}
                checked={mode === option.value}
                onChange={() => onModeChange(option.value)}
                disabled={optionDisabled}
                aria-describedby={
                  option.value === "auto" && autoDisabled ? autoReasonId : undefined
                }
                className="peer sr-only"
              />
              <span
                className={cn(
                  "inline-flex h-7 items-center gap-1.5 rounded-[5px] px-2.5 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground",
                  "peer-checked:bg-card peer-checked:text-foreground peer-checked:shadow-sm",
                  "peer-focus-visible:ring-2 peer-focus-visible:ring-ring peer-focus-visible:ring-offset-1 peer-focus-visible:ring-offset-background",
                  optionDisabled && "opacity-50 hover:text-muted-foreground",
                )}
              >
                <option.Icon aria-hidden="true" className="h-3.5 w-3.5" />
                {option.label}
              </span>
            </label>
          );
        })}
      </div>
      {autoDisabled ? (
        <span id={autoReasonId} className="sr-only">
          {autoDisabledReason}
        </span>
      ) : null}
      <p id={descriptionId} className="text-[11px] leading-4 text-muted-foreground">
        The router classifies the brief and calls the selected model automatically. Manual selection
        is recorded as an override.
      </p>
    </fieldset>
  );
}
