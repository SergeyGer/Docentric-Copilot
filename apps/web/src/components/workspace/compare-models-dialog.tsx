"use client";

import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, GitCompare, Loader2, Play } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import { Select } from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ErrorAlert } from "@/components/workspace/error-alert";
import { ValidationStatusBadge } from "@/components/workspace/status-badges";
import { postJson, toApiError, type ApiError } from "@/lib/api";
import { formatCostUsd, formatNumber } from "@/lib/format";
import type {
  CompareRequest,
  CompareResponse,
  CompareRun,
  MappingStatus,
  ProviderView,
  SourceView,
} from "@/lib/types";
import { VALIDATION_LEVELS, isCheckStatus } from "@/lib/validation";

const MAPPING_COUNT_ORDER: readonly MappingStatus[] = [
  "confirmed",
  "schema_valid",
  "needs_review",
  "conflict",
  "missing",
  "invalid",
];

const MAPPING_COUNT_LABELS: Record<MappingStatus, string> = {
  confirmed: "Confirmed",
  schema_valid: "Schema valid",
  needs_review: "Needs review",
  conflict: "Conflict",
  missing: "Missing",
  invalid: "Invalid",
};

interface TargetSelection {
  provider: string;
  model: string;
}

export interface CompareModelsDialogProps {
  source: SourceView | null;
  prompt: string;
  providers: ProviderView[];
  onClose: () => void;
}

function ComparisonRow({
  run,
  recommended,
}: {
  run: CompareRun;
  recommended: boolean;
}) {
  return (
    <TableRow className={recommended ? "bg-success/5" : undefined}>
      <TableCell>
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="font-medium text-foreground">{run.provider}</span>
          {run.model ? (
            <span className="font-mono text-[10px] text-muted-foreground">{run.model}</span>
          ) : (
            <span className="text-[10px] text-muted-foreground">default model</span>
          )}
          {recommended ? <Badge variant="success">Recommended</Badge> : null}
        </div>
        <p className="mt-1 text-[10px] text-muted-foreground">
          {formatNumber(run.requirements)} requirements
        </p>
      </TableCell>
      <TableCell>
        <Badge variant={run.ok ? "success" : "destructive"}>{run.ok ? "OK" : "Failed"}</Badge>
        {!run.ok && run.error ? (
          <p className="mt-1 max-w-[220px] break-words text-[11px] leading-4 text-destructive">
            {run.error}
          </p>
        ) : null}
      </TableCell>
      <TableCell className="whitespace-nowrap font-mono text-xs">
        {formatNumber(run.latency_ms)} ms
      </TableCell>
      <TableCell className="whitespace-nowrap font-mono text-xs">
        {run.ok ? formatNumber(run.tokens) : "—"}
      </TableCell>
      <TableCell className="whitespace-nowrap font-mono text-xs">
        {run.ok ? formatCostUsd(run.cost_usd) : "—"}
      </TableCell>
      <TableCell>
        <ul className="grid grid-cols-2 gap-x-3 gap-y-0.5">
          {MAPPING_COUNT_ORDER.map((status) => (
            <li key={status} className="flex items-baseline justify-between gap-2 text-[10px]">
              <span className="text-muted-foreground">{MAPPING_COUNT_LABELS[status]}</span>
              <span className="font-mono text-foreground">
                {formatNumber(run.counts[status] ?? 0)}
              </span>
            </li>
          ))}
        </ul>
      </TableCell>
      <TableCell>
        <ul className="space-y-0.5">
          {VALIDATION_LEVELS.map((level) => {
            const status = run.validation[level.key];
            return (
              <li key={level.key} className="flex items-center gap-1.5">
                <span className="w-5 shrink-0 font-mono text-[10px] text-muted-foreground">
                  {level.code}
                </span>
                {isCheckStatus(status) ? (
                  <ValidationStatusBadge status={status} showIcon={false} className="text-[10px]" />
                ) : (
                  <span className="text-[10px] text-muted-foreground">—</span>
                )}
              </li>
            );
          })}
        </ul>
      </TableCell>
    </TableRow>
  );
}

export function CompareModelsDialog({
  source,
  prompt,
  providers,
  onClose,
}: CompareModelsDialogProps) {
  const configuredProviders = useMemo(
    () => providers.filter((provider) => provider.configured),
    [providers],
  );

  const [targets, setTargets] = useState<TargetSelection[]>(() => [
    { provider: configuredProviders[0]?.name ?? "", model: "" },
    { provider: configuredProviders[1]?.name ?? "", model: "" },
  ]);
  const [pending, setPending] = useState(false);
  const [response, setResponse] = useState<CompareResponse | null>(null);
  const [error, setError] = useState<ApiError | null>(null);

  // Providers load asynchronously; fill an empty target once the catalogue
  // arrives without overwriting a deliberate selection.
  useEffect(() => {
    if (configuredProviders.length === 0) {
      return;
    }
    setTargets((current) => {
      let changed = false;
      const next = current.map((target, index) => {
        if (configuredProviders.some((provider) => provider.name === target.provider)) {
          return target;
        }
        const fallback = configuredProviders[index] ?? configuredProviders[0];
        changed = true;
        return { provider: fallback.name, model: "" };
      });
      return changed ? next : current;
    });
  }, [configuredProviders]);

  const trimmedPrompt = prompt.trim();
  const twoProviders = configuredProviders.length >= 2;
  const bothSelected = targets.every((target) => target.provider.length > 0);
  const distinctProviders = targets[0].provider !== targets[1].provider;
  const canRun =
    source !== null &&
    trimmedPrompt.length >= 3 &&
    twoProviders &&
    bothSelected &&
    distinctProviders &&
    !pending;

  const changeProvider = (index: number, providerName: string) => {
    setTargets((current) =>
      current.map((target, targetIndex) =>
        targetIndex === index ? { provider: providerName, model: "" } : target,
      ),
    );
  };

  const changeModel = (index: number, modelValue: string) => {
    setTargets((current) =>
      current.map((target, targetIndex) =>
        targetIndex === index ? { ...target, model: modelValue } : target,
      ),
    );
  };

  const runComparison = async () => {
    if (!canRun || !source) {
      return;
    }
    setPending(true);
    setError(null);
    setResponse(null);
    try {
      const body: CompareRequest = {
        source_id: source.source_id,
        prompt: trimmedPrompt,
        targets: targets.map((target) => ({
          provider: target.provider,
          model: target.model.trim().length > 0 ? target.model.trim() : null,
        })),
      };
      const result = await postJson<CompareResponse>("/api/v1/templates/compare", body, {
        timeoutMs: 300_000,
      });
      setResponse(result);
    } catch (requestError) {
      setError(toApiError(requestError));
    } finally {
      setPending(false);
    }
  };

  const resultSummary = response
    ? `Comparison complete: ${response.runs.length} runs.${
        response.recommended ? ` Recommended provider: ${response.recommended}.` : " No recommendation."
      }`
    : "";

  return (
    <Modal
      open
      onClose={onClose}
      title="Compare models"
      description="Run the same brief through two configured providers and compare measured latency, token usage, cost, mapping counts and validation statuses."
      className="max-w-6xl"
      bodyClassName="space-y-4"
    >
      <Alert variant="warning">
        <AlertTriangle aria-hidden="true" />
        <div>
          <AlertTitle>Live call, may incur cost</AlertTitle>
          <AlertDescription className="text-xs leading-5">
            This is not an automatic action. Each target sends the current brief and schema to a
            live provider, so provider usage and cost may be incurred. Nothing runs until you press
            Run comparison.
          </AlertDescription>
        </div>
      </Alert>

      <div className="grid gap-3 sm:grid-cols-2">
        {[0, 1].map((index) => {
          const target = targets[index] ?? { provider: "", model: "" };
          const info = configuredProviders.find((provider) => provider.name === target.provider);
          return (
            <fieldset
              key={index}
              className="rounded-lg border border-border bg-muted/15 p-3"
            >
              <legend className="px-1 text-xs font-semibold text-foreground">
                Target {index === 0 ? "A" : "B"}
              </legend>
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <label
                    htmlFor={`compare-provider-${index}`}
                    className="text-[11px] font-medium text-foreground"
                  >
                    Provider
                  </label>
                  <Select
                    id={`compare-provider-${index}`}
                    value={target.provider}
                    onChange={(event) => changeProvider(index, event.target.value)}
                    disabled={pending || configuredProviders.length === 0}
                  >
                    {configuredProviders.length === 0 ? (
                      <option value="">No configured providers</option>
                    ) : null}
                    {target.provider.length === 0 ? (
                      <option value="">Choose a provider</option>
                    ) : null}
                    {configuredProviders.map((provider) => (
                      <option key={provider.name} value={provider.name}>
                        {provider.name}
                      </option>
                    ))}
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <label
                    htmlFor={`compare-model-${index}`}
                    className="text-[11px] font-medium text-foreground"
                  >
                    Model <span className="font-normal text-muted-foreground">(optional)</span>
                  </label>
                  <Select
                    id={`compare-model-${index}`}
                    value={target.model}
                    onChange={(event) => changeModel(index, event.target.value)}
                    disabled={pending || !info}
                  >
                    <option value="">Provider default</option>
                    {(info?.models ?? []).map((modelName) => (
                      <option key={modelName} value={modelName}>
                        {modelName}
                      </option>
                    ))}
                  </Select>
                </div>
              </div>
            </fieldset>
          );
        })}
      </div>

      {!source ? (
        <p className="text-[11px] text-warning">
          Load a data source (upload or run the demo) before comparing models.
        </p>
      ) : null}
      {source && trimmedPrompt.length < 3 ? (
        <p className="text-[11px] text-warning">
          Enter a brief of at least 3 characters in the prompt panel before comparing.
        </p>
      ) : null}
      {!twoProviders ? (
        <p className="text-[11px] text-warning">
          At least two configured providers are required. The API currently reports{" "}
          {configuredProviders.length} configured provider
          {configuredProviders.length === 1 ? "" : "s"}.
        </p>
      ) : null}
      {twoProviders && bothSelected && !distinctProviders ? (
        <p className="text-[11px] text-warning">
          Choose two different providers so the comparison has two measured runs.
        </p>
      ) : null}

      {error ? <ErrorAlert error={error} title="Model comparison failed" /> : null}

      <div className="flex flex-wrap items-center gap-2">
        <Button
          type="button"
          onClick={() => {
            void runComparison();
          }}
          disabled={!canRun}
          aria-busy={pending}
        >
          {pending ? (
            <Loader2 aria-hidden="true" className="animate-spin" />
          ) : (
            <Play aria-hidden="true" />
          )}
          {pending ? "Running comparison…" : "Run comparison"}
        </Button>
        {pending ? (
          <span
            role="status"
            aria-live="polite"
            className="inline-flex items-center gap-1.5 text-[11px] text-muted-foreground"
          >
            <Loader2 aria-hidden="true" className="h-3.5 w-3.5 animate-spin" />
            Running each target sequentially; live providers can take a while.
          </span>
        ) : (
          <span className="text-[11px] text-muted-foreground">
            Runs are sequential and never start automatically.
          </span>
        )}
      </div>

      <p className="sr-only" role="status" aria-live="polite">
        {resultSummary}
      </p>

      {response ? (
        <section aria-labelledby="compare-results-title" className="space-y-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3
              id="compare-results-title"
              className="inline-flex items-center gap-1.5 text-xs font-semibold text-foreground"
            >
              <GitCompare aria-hidden="true" className="h-3.5 w-3.5" />
              Measured results
            </h3>
            {response.recommended ? (
              <Badge variant="success">Recommended: {response.recommended}</Badge>
            ) : (
              <Badge variant="muted">No recommendation</Badge>
            )}
          </div>
          <Table aria-label="Model comparison results">
            <TableHeader>
              <TableRow>
                <TableHead>Provider / model</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Latency</TableHead>
                <TableHead>Tokens</TableHead>
                <TableHead>Cost</TableHead>
                <TableHead>Mapping counts</TableHead>
                <TableHead>Validation</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {response.runs.map((run, index) => (
                <ComparisonRow
                  key={`${run.provider}-${run.model ?? "default"}-${index}`}
                  run={run}
                  recommended={run.ok && run.provider === response.recommended}
                />
              ))}
            </TableBody>
          </Table>
          <p className="text-[11px] leading-5 text-muted-foreground">{response.note}</p>
        </section>
      ) : (
        <p className="rounded-md border border-dashed border-border bg-muted/15 px-3 py-3 text-[11px] leading-5 text-muted-foreground">
          Results appear here after a run. Each run reports provider errors individually, so a
          failed target never hides the other result.
        </p>
      )}

      <p className="text-[11px] leading-5 text-muted-foreground">
        Cost is shown only when the provider reports usage and a known price; zero is expected for
        the deterministic baseline. Validation grades are reported exactly as the API returns them.
      </p>
    </Modal>
  );
}
