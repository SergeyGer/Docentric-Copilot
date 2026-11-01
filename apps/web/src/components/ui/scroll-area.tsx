import * as React from "react";

import { cn } from "@/lib/utils";

export interface ScrollAreaProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Class names applied to the inner content wrapper. */
  viewportClassName?: string;
}

/**
 * A styled native scroll container. Radix's scroll area is intentionally not a
 * dependency of this project, so keyboard scrolling and overflow are left to the
 * browser while the visual treatment stays consistent.
 */
const ScrollArea = React.forwardRef<HTMLDivElement, ScrollAreaProps>(
  ({ className, viewportClassName, children, ...props }, ref) => (
    <div
      ref={ref}
      className={cn("scroll-area relative overflow-y-auto overscroll-contain", className)}
      {...props}
    >
      <div className={cn("min-w-0", viewportClassName)}>{children}</div>
    </div>
  ),
);
ScrollArea.displayName = "ScrollArea";

export { ScrollArea };
