"use client";

import { useState } from "react";
import {
  ClipboardList,
  Loader2,
  Sparkles,
  Wand2,
} from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { CheckboxRow } from "@/components/workspace/checkbox-row";
import { CopyButton } from "@/components/workspace/copy-button";
import { ErrorAlert } from "@/components/workspace/error-alert";
import { Panel } from "@/components/workspace/panel";
import type { ApiError } from "@/lib/api";
import {
  PANEL_IDS,
  PROMPT_MAX_LENGTH,
} from "@/lib/constants";
import {
  formatProviderLabel,
  truncateMiddle,
} from "@/lib/format";
import type {
  DesignStyle,
  GenerationInfo,
  PlanResponse,
  ProviderView,
  SourceView,
} from "@/lib/types";
import { cn } from "@/lib/utils";

const DESIGN_STYLES: ReadonlyArray<{ value: DesignStyle; label: string }> = [
  { value: "modern", label: "Modern" },
  { value: "classic", label: "Classic" },
  { value: "minimal", label: "Minimal" },
];

const LANGUAGE_PATTERN = /^[a-z]{2}(-[A-Z]{2})?$/;

export interface PromptPanelProps {
  source: SourceView | null;
  prompt: string;
  onPromptChange: (value: string) => void;
  providers: ProviderView[];
  providersPending: boolean;
  providerError: ApiError | null;
  provider: string;
  onProviderChange: (value: string) => void;
  selectedProvider: ProviderView | null;
  model: string;
  onModelChange: (value: string) => void;
  designStyle: DesignStyle;
  onDesignStyleChange: (value: DesignStyle) => void;
  language: string;
  onLanguageChange: (value: string) => void;
  strictValidation: boolean;
  onStrictValidationChange: (value: boolean) => void;
  maxCost: string;
  onMaxCostChange: (value: string) => void;
  maxRepairAttempts: number;
  onMaxRepairAttemptsChange: (value: number) => void;
  planPending: boolean;
  planError: ApiError | null;
  plan: PlanResponse | null;
  generation: GenerationInfo | null;
  onPlan: () => void;
  onUseExample: () => void;
  onReloadProviders: () => void;
  onDismissPlanError: () => void;
  onDismissProviderError: () => void;
}

export function PromptPanel({
  source,
  prompt,
  onPromptChange,
  providers,
  providersPending,
  providerError,
  provider,
  onProviderChange,
  selectedProvider,
  model,
  onModelChange,
  designStyle,
  onDesignStyleChange,
  language,
  onLanguageChange,
  strictValidation,
  onStrictValidationChange,
  maxCost,
  onMaxCostChange,
  maxRepairAttempts,
  onMaxRepairAttemptsChange,
  planPending,
  planError,
  plan,
  generation,
  onPlan,
  onUseExample,
  onReloadProviders,
  onDismissPlanError,
  onDismissProviderError,
}: PromptPanelProps) {
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const languageValid = LANGUAGE_PATTERN.test(language.trim());
  const counterTone =
    prompt.length > PROMPT_MAX_LENGTH * 0.92 ? "text-warning" : "text-muted-foreground";

  return (
    <Panel
      id={PANEL_IDS.prompt}
      step={3}
      title="Prompt & provider"
      description="Describe the document you need. The planner maps each requirement to schema fields and returns a validated Template IR."
      actions={
        <Badge variant="outline" className="gap-1">
          <ClipboardList aria-hidden="true" className="h-3 w-3" />
          {PROMPT_MAX_LENGTH.toLocaleString("en-GB")} char limit
        </Badge>
      }
    >
      <div className="grid gap-5 xl:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
        <div className="flex min-w-0 flex-col gap-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <label htmlFor="prompt-input" className="text-xs font-medium text-foreground">
              Document brief
            </label>
            <div className="flex items-center gap-2">
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={onUseExample}
                disabled={planPending}
              >
                <Sparkles aria-hidden="true" />
                Use example
              </Button>
              <span className={cn("font-mono text-[11px]", counterTone)}>
                {prompt.length}/{PROMPT_MAX_LENGTH}
              </span>
            </div>
          </div>
          <Textarea
            id="prompt-input"
            value={prompt}
            onChange={(event) => onPromptChange(event.target.value)}
            maxLength={PROMPT_MAX_LENGTH}
            rows={8}
            disabled={planPending}
            placeholder="Create a professional sales quotation with the company logo, customer details, line items and totals…"
            aria-describedby="prompt-hint"
            className="min-h-[180px] resize-y"
          />
          <p id="prompt-hint" className="text-xs leading-5 text-muted-foreground">
            Describe content, layout and required fields. Paths inserted from the schema explorer
            are appended to this brief.
          </p>

          {planError ? (
            <ErrorAlert error={planError} title="Planning failed" onDismiss={onDismissPlanError} />
          ) : null}

          {plan ? (
            <div className="rounded-lg border border-border bg-muted/25 p-3">
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[11px] text-muted-foreground">
                <span className="inline-flex items-center gap-1.5 font-medium text-foreground">
                  <Badge variant="success" className="h-5">
                    Planned
                  </Badge>
                  Template
                  <code className="font-mono text-foreground">{plan.template_id}</code>
                  <CopyButton value={plan.template_id} label="Copy template ID" />
                </span>
                <span>Version {plan.version}</span>
                <span className="font-mono">IR {truncateMiddle(plan.ir_digest)}</span>
                {generation ? (
                  <span>
                    {generation.provider}
                    {generation.model ? ` / ${generation.model}` : ""} ·{" "}
                    {generation.latency_ms.toLocaleString("en-GB")} ms ·{" "}
                    {generation.usage.estimated_cost_usd.toFixed(3)} USD
                  </span>
                ) : null}
              </div>
            </div>
          ) : null}

          <div className="mt-auto flex flex-wrap items-center gap-3 pt-1">
            <Button
              type="button"
              onClick={onPlan}
              disabled={!source || planPending}
              aria-busy={planPending}
              className="min-w-[168px]"
            >
              {planPending ? (
                <Loader2 aria-hidden="true" className="animate-spin" />
              ) : (
                <Wand2 aria-hidden="true" />
              )}
              {planPending ? "Planning template…" : "Plan template"}
            </Button>
            {!source ? (
              <p className="text-xs text-muted-foreground">
                Upload a data source above to enable planning.
              </p>
            ) : planPending ? (
              <p
                role="status"
                aria-live="polite"
                className="flex items-center gap-1.5 text-xs text-muted-foreground"
              >
                <Loader2 aria-hidden="true" className="h-3.5 w-3.5 animate-spin" />
                Mapping requirements and running validation…
              </p>
            ) : (
              <p className="text-xs text-muted-foreground">
                Deterministic mock provider is available offline.
              </p>
            )}
          </div>
        </div>

        <div className="flex min-w-0 flex-col gap-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <label htmlFor="provider-select" className="text-xs font-medium text-foreground">
                Provider
              </label>
              {providersPending ? (
                <Skeleton className="h-9 w-full" />
              ) : (
                <Select
                  id="provider-select"
                  value={provider}
                  onChange={(event) => onProviderChange(event.target.value)}
                  disabled={planPending || providers.length === 0}
                  aria-describedby="provider-hint"
                >
                  {providers.length === 0 ? <option value={provider}>{provider}</option> : null}
                  {providers.map((item) => (
                    <option key={item.name} value={item.name} disabled={!item.configured}>
                      {formatProviderLabel(item.name, item.configured)}
                    </option>
                  ))}
                </Select>
              )}
              <p id="provider-hint" className="text-[11px] leading-4 text-muted-foreground">
                {selectedProvider?.configured
                  ? "Configured provider"
                  : "Mock always works offline; other providers require API keys."}
              </p>
            </div>

            <div className="space-y-1.5">
              <label htmlFor="model-input" className="text-xs font-medium text-foreground">
                Model <span className="font-normal text-muted-foreground">(optional)</span>
              </label>
              <Input
                id="model-input"
                list="provider-models"
                value={model}
                onChange={(event) => onModelChange(event.target.value)}
                placeholder={selectedProvider?.default_model ?? "Provider default"}
                maxLength={120}
                disabled={planPending}
              />
              <datalist id="provider-models">
                {(selectedProvider?.models ?? []).map((item) => (
                  <option key={item} value={item} />
                ))}
              </datalist>
              <p className="text-[11px] leading-4 text-muted-foreground">
                Leave blank to use the provider default.
              </p>
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <label htmlFor="design-style" className="text-xs font-medium text-foreground">
                Design style
              </label>
              <Select
                id="design-style"
                value={designStyle}
                onChange={(event) => onDesignStyleChange(event.target.value as DesignStyle)}
                disabled={planPending}
              >
                {DESIGN_STYLES.map((style) => (
                  <option key={style.value} value={style.value}>
                    {style.label}
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-1.5">
              <label htmlFor="language-input" className="text-xs font-medium text-foreground">
                Language
              </label>
              <Input
                id="language-input"
                value={language}
                onChange={(event) => onLanguageChange(event.target.value)}
                maxLength={5}
                placeholder="en"
                disabled={planPending}
                aria-invalid={!languageValid}
                aria-describedby="language-hint"
                className="font-mono"
              />
              <p id="language-hint" className="text-[11px] leading-4 text-muted-foreground">
                {languageValid ? "ISO 639-1, e.g. en or en-US." : "Use a value like en or en-US."}
              </p>
            </div>
          </div>

          <Collapsible
            open={advancedOpen}
            onOpenChange={setAdvancedOpen}
            className="rounded-md border bg-muted/20 px-3 py-2"
          >
            <CollapsibleTrigger className="text-xs text-muted-foreground hover:text-foreground">
              <span className="inline-flex items-center gap-1.5">Advanced plan options</span>
            </CollapsibleTrigger>
            <CollapsibleContent className="space-y-3 pt-3">
              <CheckboxRow
                id="strict-validation"
                checked={strictValidation}
                onChange={onStrictValidationChange}
                label="Strict validation"
                description="Reject a plan that fails structural, semantic or logical checks."
                disabled={planPending}
              />
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <label htmlFor="max-cost" className="text-xs font-medium text-foreground">
                    Cost cap (USD)
                  </label>
                  <Input
                    id="max-cost"
                    type="number"
                    min={0}
                    max={50}
                    step={0.05}
                    value={maxCost}
                    onChange={(event) => onMaxCostChange(event.target.value)}
                    disabled={planPending}
                  />
                </div>
                <div className="space-y-1.5">
                  <label htmlFor="repair-attempts" className="text-xs font-medium text-foreground">
                    Repair attempts
                  </label>
                  <Select
                    id="repair-attempts"
                    value={String(maxRepairAttempts)}
                    onChange={(event) =>
                      onMaxRepairAttemptsChange(Number.parseInt(event.target.value, 10))
                    }
                    disabled={planPending}
                  >
                    <option value="0">0 — no repairs</option>
                    <option value="1">1 — one repair</option>
                    <option value="2">2 — two repairs</option>
                  </Select>
                </div>
              </div>
            </CollapsibleContent>
          </Collapsible>

          {providerError ? (
            <ErrorAlert
              error={providerError}
              title="Provider catalogue unavailable"
              onDismiss={onDismissProviderError}
              action={
                <Button type="button" size="sm" variant="outline" onClick={onReloadProviders}>
                  Retry providers
                </Button>
              }
            />
          ) : null}

          {!providersPending && providers.length === 0 && !providerError ? (
            <Alert variant="warning">
              <AlertTitle>No providers reported</AlertTitle>
              <AlertDescription>
                The API returned an empty provider list. Refresh the catalogue before planning.
              </AlertDescription>
            </Alert>
          ) : null}
        </div>
      </div>
    </Panel>
  );
}
