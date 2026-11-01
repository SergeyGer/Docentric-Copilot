"use client";

import * as React from "react";
import { ChevronDown } from "lucide-react";

import { cn } from "@/lib/utils";

interface CollapsibleContextValue {
  open: boolean;
  toggle: () => void;
  contentId: string;
}

const CollapsibleContext = React.createContext<CollapsibleContextValue | null>(null);

function useCollapsibleContext(): CollapsibleContextValue {
  const context = React.useContext(CollapsibleContext);
  if (!context) {
    throw new Error("Collapsible components must be used within <Collapsible>");
  }
  return context;
}

export interface CollapsibleProps extends Omit<React.HTMLAttributes<HTMLDivElement>, "onChange"> {
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
}

function Collapsible({
  className,
  open,
  defaultOpen = false,
  onOpenChange,
  children,
  ...props
}: CollapsibleProps) {
  const [internalOpen, setInternalOpen] = React.useState(defaultOpen);
  const contentId = React.useId();
  const isControlled = open !== undefined;
  const isOpen = isControlled ? open : internalOpen;

  const toggle = React.useCallback(() => {
    const next = !isOpen;
    if (!isControlled) {
      setInternalOpen(next);
    }
    onOpenChange?.(next);
  }, [isControlled, isOpen, onOpenChange]);

  return (
    <CollapsibleContext.Provider value={{ open: isOpen, toggle, contentId }}>
      <div data-state={isOpen ? "open" : "closed"} className={cn(className)} {...props}>
        {children}
      </div>
    </CollapsibleContext.Provider>
  );
}

export interface CollapsibleTriggerProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  hideChevron?: boolean;
}

const CollapsibleTrigger = React.forwardRef<HTMLButtonElement, CollapsibleTriggerProps>(
  ({ className, children, hideChevron = false, type = "button", onClick, ...props }, ref) => {
    const { open, toggle, contentId } = useCollapsibleContext();
    return (
      <button
        ref={ref}
        type={type}
        aria-expanded={open}
        aria-controls={contentId}
        data-state={open ? "open" : "closed"}
        onClick={(event) => {
          onClick?.(event);
          if (!event.defaultPrevented) {
            toggle();
          }
        }}
        className={cn(
          "inline-flex w-full items-center gap-2 rounded-md text-left text-sm font-medium text-foreground transition-colors hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
          className,
        )}
        {...props}
      >
        {children}
        {hideChevron ? null : (
          <ChevronDown
            aria-hidden="true"
            className={cn(
              "ml-auto h-4 w-4 shrink-0 text-muted-foreground transition-transform duration-150",
              open && "rotate-180",
            )}
          />
        )}
      </button>
    );
  },
);
CollapsibleTrigger.displayName = "CollapsibleTrigger";

const CollapsibleContent = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, children, ...props }, ref) => {
    const { open, contentId } = useCollapsibleContext();
    return (
      <div
        ref={ref}
        id={contentId}
        hidden={!open}
        data-state={open ? "open" : "closed"}
        className={cn("pt-2", className)}
        {...props}
      >
        {children}
      </div>
    );
  },
);
CollapsibleContent.displayName = "CollapsibleContent";

export { Collapsible, CollapsibleContent, CollapsibleTrigger };
