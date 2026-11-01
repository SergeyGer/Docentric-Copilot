import type { ReactNode } from "react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export interface PanelProps {
  id: string;
  step: number;
  title: string;
  description?: string;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}

/**
 * One numbered workspace panel. The step marker mirrors the workflow rail and
 * the section heading doubles as the accessible name of the region.
 */
export function Panel({
  id,
  step,
  title,
  description,
  actions,
  children,
  className,
  bodyClassName,
}: PanelProps) {
  return (
    <section
      id={id}
      aria-labelledby={`${id}-title`}
      className={cn("scroll-mt-36", className)}
    >
      <Card className="h-full">
        <CardHeader className="gap-3 pb-4">
          <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-start">
            <div className="flex min-w-0 items-start gap-3">
              <span
                aria-hidden="true"
                className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-primary/20 bg-primary/10 text-xs font-semibold text-primary"
              >
                {step}
              </span>
              <div className="min-w-0">
                <CardTitle id={`${id}-title`} className="text-[15px]">
                  {title}
                </CardTitle>
                {description ? (
                  <CardDescription className="mt-1 text-[13px]">{description}</CardDescription>
                ) : null}
              </div>
            </div>
            {actions ? (
              <div className="flex shrink-0 flex-wrap items-center gap-2 sm:justify-end">
                {actions}
              </div>
            ) : null}
          </div>
        </CardHeader>
        <CardContent className={cn("flex-1", bodyClassName)}>{children}</CardContent>
      </Card>
    </section>
  );
}
