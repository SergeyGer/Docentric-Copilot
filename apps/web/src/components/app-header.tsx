"use client";

import { ExternalLink, FileText, FileType2, Loader2, Play } from "lucide-react";

import { ApiStatusBadge } from "@/components/api-status-badge";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { useWorkspaceContext } from "@/hooks/workspace-context";
import { API_BASE_URL } from "@/lib/api";
import { DEFAULT_DEMO_CASE_ID } from "@/lib/constants";
import type { DemoCase } from "@/lib/types";
import { cn } from "@/lib/utils";

const FALLBACK_DEMO_CASE: DemoCase = {
  id: DEFAULT_DEMO_CASE_ID,
  title: "Sales quotation",
  description: "Bundled synthetic quotation demo.",
  prompt: "",
};

export function AppHeader() {
  const workspace = useWorkspaceContext();
  const demoCases =
    workspace.demoCases.length > 0 ? workspace.demoCases : [FALLBACK_DEMO_CASE];
  const selectedCaseId = demoCases.some((item) => item.id === workspace.demoCaseId)
    ? workspace.demoCaseId
    : (demoCases[0]?.id ?? DEFAULT_DEMO_CASE_ID);
  const demoBusy = workspace.demoPending;
  const demoDisabled =
    demoBusy ||
    workspace.uploadPending ||
    workspace.planPending ||
    workspace.revisionPending ||
    workspace.compilePending ||
    workspace.confirmPending !== null;

  return (
    <header className="sticky top-0 z-40 border-b border-border/80 bg-card/90 backdrop-blur supports-[backdrop-filter]:bg-card/75">
      <div className="mx-auto flex h-16 w-full max-w-[1440px] items-center justify-between gap-3 px-4 sm:px-6 lg:px-8">
        <div className="flex min-w-0 items-center gap-3">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-primary to-blue-700 text-primary-foreground shadow-sm">
            <FileText aria-hidden="true" className="h-5 w-5" />
          </span>
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold leading-5 tracking-tight text-foreground">
              Docentric Copilot
            </p>
            <p className="truncate text-[11px] leading-4 text-muted-foreground">
              Template engineering workspace
            </p>
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          <Badge variant="outline" className="hidden gap-1 xl:inline-flex">
            <FileType2 aria-hidden="true" className="h-3 w-3" />
            Generic DOCX target
          </Badge>

          <div className="hidden items-center gap-1.5 lg:flex">
            <label htmlFor="demo-case" className="sr-only">
              Demo example
            </label>
            <Select
              id="demo-case"
              value={selectedCaseId}
              onChange={(event) => workspace.setDemoCaseId(event.target.value)}
              disabled={demoBusy || workspace.demoCasesPending}
              aria-busy={workspace.demoCasesPending}
              aria-describedby="demo-case-hint"
              className="h-8 w-[148px] text-xs"
              title="Choose the bundled demo scenario"
            >
              {demoCases.map((item) => (
                <option key={item.id} value={item.id} title={item.description}>
                  {item.title}
                </option>
              ))}
            </Select>
            <span id="demo-case-hint" className="sr-only">
              Choose the bundled demo scenario, then run it to hydrate the whole workspace and
              start the guided tour.
            </span>
          </div>

          <Button
            type="button"
            size="sm"
            onClick={() => {
              void workspace.runDemo(selectedCaseId);
            }}
            disabled={demoDisabled}
            aria-busy={demoBusy}
            aria-label={
              demoBusy ? "Running the demo" : "Run demo: hydrate the workspace from a demo case"
            }
            title={
              demoDisabled && !demoBusy
                ? "Finish the current operation before running the demo"
                : "Run a complete demo: source, schema, plan, mapping, validation and preview"
            }
            className="shadow-sm"
          >
            {demoBusy ? (
              <Loader2 aria-hidden="true" className="animate-spin" />
            ) : (
              <Play aria-hidden="true" />
            )}
            {demoBusy ? "Running demo…" : "Run demo"}
          </Button>

          <a
            href={`${API_BASE_URL}/docs`}
            target="_blank"
            rel="noopener noreferrer"
            className={cn(buttonVariants({ variant: "ghost", size: "sm" }), "hidden lg:inline-flex")}
            title="Open the FastAPI OpenAPI documentation"
          >
            API docs
            <ExternalLink aria-hidden="true" />
          </a>
          <ApiStatusBadge />
        </div>
      </div>
    </header>
  );
}
