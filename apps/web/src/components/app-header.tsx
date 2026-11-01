import { ExternalLink, FileText, FileType2 } from "lucide-react";

import { ApiStatusBadge } from "@/components/api-status-badge";
import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { API_BASE_URL } from "@/lib/api";
import { cn } from "@/lib/utils";

export function AppHeader() {
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
          <Badge variant="outline" className="hidden gap-1 md:inline-flex">
            <FileType2 aria-hidden="true" className="h-3 w-3" />
            Generic DOCX target
          </Badge>
          <a
            href={`${API_BASE_URL}/docs`}
            target="_blank"
            rel="noopener noreferrer"
            className={cn(buttonVariants({ variant: "ghost", size: "sm" }), "hidden sm:inline-flex")}
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
