import { API_BASE_URL } from "@/lib/api";

export function AppFooter() {
  return (
    <footer className="mt-10 border-t border-border bg-card/50">
      <div className="mx-auto flex w-full max-w-[1440px] flex-col gap-1.5 px-4 py-5 text-[11px] leading-5 text-muted-foreground sm:flex-row sm:items-center sm:justify-between sm:px-6 lg:px-8">
        <p>
          Docentric Copilot · Template IR 1.0 · deterministic generic DOCX · HTML preview in a
          sandboxed frame
        </p>
        <p className="font-mono">API {API_BASE_URL}</p>
      </div>
    </footer>
  );
}
