import type { Metadata } from "next";

import { ReferenceInspector } from "@/components/reference/reference-inspector";

export const metadata: Metadata = {
  title: "Reference template inspector · Docentric Copilot",
  description:
    "Read-only inspection of existing Docentric Word templates: content controls, ProjectData bindings, DDSP resolution, reference graph and structural/semantic diff.",
};

export default function ReferencePage() {
  return <ReferenceInspector />;
}
