import { ShieldAlert } from "lucide-react";

/**
 * Persistent compatibility disclaimer. It lives in the application shell so it is
 * visible for every workspace state, including before anything has been planned.
 */
export function CompatibilityNotice() {
  return (
    <div
      role="note"
      aria-label="Docentric AX compatibility notice"
      className="border-b border-amber-300/70 bg-amber-50 text-amber-950"
    >
      <div className="mx-auto flex w-full max-w-[1440px] items-start gap-2.5 px-4 py-2.5 sm:px-6 lg:px-8">
        <ShieldAlert aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
        <p className="text-[11px] leading-5">
          <span className="font-semibold">
            Docentric AX compatibility is not verified. Output is a generic DOCX.
          </span>{" "}
          The compatibility level (V5) is reported as <span className="font-medium">not tested</span>
          ; it is never treated as passed. No part of this workspace is a compatibility claim.
        </p>
      </div>
    </div>
  );
}
