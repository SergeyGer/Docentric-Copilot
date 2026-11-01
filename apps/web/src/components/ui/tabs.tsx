"use client";

import * as React from "react";

import { cn } from "@/lib/utils";

interface TabsContextValue {
  value: string;
  setValue: (value: string) => void;
  baseId: string;
}

const TabsContext = React.createContext<TabsContextValue | null>(null);

function useTabsContext(): TabsContextValue {
  const context = React.useContext(TabsContext);
  if (!context) {
    throw new Error("Tabs components must be used within <Tabs>");
  }
  return context;
}

export interface TabsProps extends React.HTMLAttributes<HTMLDivElement> {
  defaultValue: string;
  value?: string;
  onValueChange?: (value: string) => void;
}

function Tabs({
  className,
  defaultValue,
  value,
  onValueChange,
  children,
  ...props
}: TabsProps) {
  const [internalValue, setInternalValue] = React.useState(defaultValue);
  const baseId = React.useId();
  const currentValue = value ?? internalValue;

  const setValue = React.useCallback(
    (nextValue: string) => {
      if (value === undefined) {
        setInternalValue(nextValue);
      }
      onValueChange?.(nextValue);
    },
    [onValueChange, value],
  );

  return (
    <TabsContext.Provider value={{ value: currentValue, setValue, baseId }}>
      <div className={cn("flex flex-col gap-3", className)} data-value={currentValue} {...props}>
        {children}
      </div>
    </TabsContext.Provider>
  );
}

const TabsList = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      role="tablist"
      className={cn(
        "inline-flex h-9 items-center justify-start gap-1 rounded-lg bg-muted p-1 text-muted-foreground",
        className,
      )}
      {...props}
    />
  ),
);
TabsList.displayName = "TabsList";

export interface TabsTriggerProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  value: string;
}

const TabsTrigger = React.forwardRef<HTMLButtonElement, TabsTriggerProps>(
  ({ className, value, children, onKeyDown, ...props }, ref) => {
    const { value: activeValue, setValue, baseId } = useTabsContext();
    const selected = activeValue === value;

    const handleKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>) => {
      onKeyDown?.(event);
      if (event.defaultPrevented) {
        return;
      }
      if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") {
        return;
      }
      event.preventDefault();
      const list = event.currentTarget.parentElement;
      const tabs = list
        ? Array.from(
            list.querySelectorAll<HTMLButtonElement>('[role="tab"]:not([disabled])'),
          )
        : [];
      if (tabs.length === 0) {
        return;
      }
      const index = tabs.indexOf(event.currentTarget);
      if (index === -1) {
        return;
      }
      const direction = event.key === "ArrowRight" ? 1 : -1;
      const next = tabs[(index + direction + tabs.length) % tabs.length];
      next?.focus();
      next?.click();
    };

    return (
      <button
        ref={ref}
        type="button"
        role="tab"
        id={`${baseId}-tab-${value}`}
        aria-selected={selected}
        aria-controls={`${baseId}-panel-${value}`}
        tabIndex={selected ? 0 : -1}
        data-state={selected ? "active" : "inactive"}
        onClick={() => setValue(value)}
        onKeyDown={handleKeyDown}
        className={cn(
          "inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-md px-3 py-1 text-sm font-medium transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 disabled:pointer-events-none disabled:opacity-50 data-[state=active]:bg-card data-[state=active]:text-foreground data-[state=active]:shadow-sm",
          className,
        )}
        {...props}
      >
        {children}
      </button>
    );
  },
);
TabsTrigger.displayName = "TabsTrigger";

export interface TabsContentProps extends React.HTMLAttributes<HTMLDivElement> {
  value: string;
}

const TabsContent = React.forwardRef<HTMLDivElement, TabsContentProps>(
  ({ className, value, children, ...props }, ref) => {
    const { value: activeValue, baseId } = useTabsContext();
    if (activeValue !== value) {
      return null;
    }
    return (
      <div
        ref={ref}
        role="tabpanel"
        id={`${baseId}-panel-${value}`}
        aria-labelledby={`${baseId}-tab-${value}`}
        tabIndex={0}
        className={cn("focus-visible:outline-none", className)}
        {...props}
      >
        {children}
      </div>
    );
  },
);
TabsContent.displayName = "TabsContent";

export { Tabs, TabsContent, TabsList, TabsTrigger };
