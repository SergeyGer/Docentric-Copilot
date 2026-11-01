import { Check } from "lucide-react";

import { cn } from "@/lib/utils";

export interface WorkflowStep {
  id: string;
  label: string;
  panelId: string;
  done: boolean;
}

export interface WorkflowStepperProps {
  steps: WorkflowStep[];
  /** 1-based index of the first incomplete step; 0 when every step is complete. */
  currentStep: number;
}

export function WorkflowStepper({ steps, currentStep }: WorkflowStepperProps) {
  return (
    <nav
      aria-label="Workspace steps"
      className="rounded-xl border border-border bg-card p-1.5 shadow-sm"
    >
      <ol className="grid grid-cols-2 gap-1 sm:grid-cols-4 xl:grid-cols-8">
        {steps.map((step, index) => {
          const stepNumber = index + 1;
          const isCurrent = currentStep === stepNumber;
          return (
            <li key={step.id}>
              <a
                href={`#${step.panelId}`}
                aria-current={isCurrent ? "step" : undefined}
                className={cn(
                  "group flex items-center gap-2 rounded-lg px-2.5 py-2 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1",
                  isCurrent ? "bg-accent/60" : "hover:bg-muted/70",
                )}
                title={`Jump to ${step.label}`}
              >
                <span
                  aria-hidden="true"
                  className={cn(
                    "flex h-6 w-6 shrink-0 items-center justify-center rounded-full border text-[11px] font-semibold",
                    step.done
                      ? "border-success/30 bg-success/10 text-success"
                      : isCurrent
                        ? "border-primary bg-primary text-primary-foreground"
                        : "border-border bg-muted text-muted-foreground",
                  )}
                >
                  {step.done ? <Check className="h-3.5 w-3.5" /> : stepNumber}
                </span>
                <span className="min-w-0">
                  <span
                    className={cn(
                      "block truncate text-[11px] font-medium leading-4",
                      isCurrent ? "text-foreground" : "text-foreground/90",
                    )}
                  >
                    {step.label}
                  </span>
                  <span className="block truncate text-[10px] leading-4 text-muted-foreground">
                    {step.done ? "Complete" : isCurrent ? "Current" : "Pending"}
                  </span>
                </span>
              </a>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
