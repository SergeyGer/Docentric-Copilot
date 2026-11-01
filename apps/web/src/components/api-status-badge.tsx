"use client";

import { useCallback, useEffect, useState } from "react";
import { Loader2, RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { API_BASE_URL, apiRequest } from "@/lib/api";
import type { HealthView } from "@/lib/types";
import { cn } from "@/lib/utils";

type ApiStatus = "checking" | "connected" | "unreachable";

export function ApiStatusBadge() {
  const [status, setStatus] = useState<ApiStatus>("checking");
  const [health, setHealth] = useState<HealthView | null>(null);

  const check = useCallback(async () => {
    setStatus("checking");
    try {
      const data = await apiRequest<HealthView>("/api/v1/health", {}, { timeoutMs: 8_000 });
      setHealth(data);
      setStatus("connected");
    } catch {
      setHealth(null);
      setStatus("unreachable");
    }
  }, []);

  useEffect(() => {
    void check();
  }, [check]);

  const label =
    status === "connected"
      ? `API ${health?.version ?? "connected"}`
      : status === "unreachable"
        ? "API unreachable"
        : "Checking API";

  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      onClick={() => {
        void check();
      }}
      disabled={status === "checking"}
      aria-busy={status === "checking"}
      aria-label={`API health: ${label}. Click to check again.`}
      title={`${API_BASE_URL}/api/v1/health`}
      className="gap-2"
    >
      {status === "checking" ? (
        <Loader2 aria-hidden="true" className="h-3.5 w-3.5 animate-spin" />
      ) : (
        <span className="relative flex h-2 w-2" aria-hidden="true">
          {status === "connected" ? (
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-success opacity-50" />
          ) : null}
          <span
            className={cn(
              "relative inline-flex h-2 w-2 rounded-full",
              status === "connected" ? "bg-success" : "bg-destructive",
            )}
          />
        </span>
      )}
      <span aria-live="polite">{label}</span>
      <RefreshCw aria-hidden="true" className="h-3 w-3 opacity-60" />
    </Button>
  );
}
