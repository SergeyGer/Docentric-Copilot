import type { ChangeEvent } from "react";

import { cn } from "@/lib/utils";

export interface CheckboxRowProps {
  id: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
  description?: string;
  disabled?: boolean;
  className?: string;
}

export function CheckboxRow({
  id,
  checked,
  onChange,
  label,
  description,
  disabled = false,
  className,
}: CheckboxRowProps) {
  const handleChange = (event: ChangeEvent<HTMLInputElement>) => {
    onChange(event.target.checked);
  };
  return (
    <div className={cn("flex items-start gap-2.5", className)}>
      <input
        id={id}
        type="checkbox"
        checked={checked}
        onChange={handleChange}
        disabled={disabled}
        className="mt-0.5 h-4 w-4 shrink-0 cursor-pointer rounded border-input accent-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 disabled:cursor-not-allowed disabled:opacity-50"
      />
      <label htmlFor={id} className="min-w-0 cursor-pointer select-none text-xs leading-5">
        <span className="font-medium text-foreground">{label}</span>
        {description ? (
          <span className="mt-0.5 block text-muted-foreground">{description}</span>
        ) : null}
      </label>
    </div>
  );
}
