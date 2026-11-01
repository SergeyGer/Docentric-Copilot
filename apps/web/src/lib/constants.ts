export const EXAMPLE_PROMPT =
  "Create a professional sales quotation with the company logo, customer details, quotation number and date, line items with quantity and price, totals, payment terms, and bank details in the footer.";

export const PROMPT_MAX_LENGTH = 5_000;
export const INSTRUCTION_MAX_LENGTH = 2_000;
export const DOCUMENT_NAME_MAX_LENGTH = 120;
export const FALLBACK_MAX_UPLOAD_BYTES = 10 * 1024 * 1024;

export const ACCEPTED_SOURCE_EXTENSIONS = [".ddsp", ".xml", ".xsd", ".zip"] as const;

export const TARGET_LABEL = "Generic DOCX";

export const PANEL_IDS = {
  source: "source-panel",
  schema: "schema-panel",
  prompt: "prompt-panel",
  mapping: "mapping-panel",
  validation: "validation-panel",
  preview: "preview-panel",
  artifacts: "artifacts-panel",
  revision: "revision-panel",
} as const;

export const DEFAULT_DOCUMENT_NAME = "document.docx";
