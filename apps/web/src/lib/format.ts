/** Presentation helpers: numbers, bytes, timestamps and inline values. */

export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) {
    return "—";
  }
  if (bytes < 1024) {
    return `${Math.round(bytes)} B`;
  }
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  const precision = value >= 100 ? 0 : 1;
  return `${value.toFixed(precision)} ${units[unitIndex]}`;
}

export function formatNumber(value: number): string {
  if (!Number.isFinite(value)) {
    return "—";
  }
  return new Intl.NumberFormat("en-GB").format(value);
}

/** Format a USD amount; budget figures use two decimals, tiny costs keep detail. */
export function formatUsd(value: number | null | undefined, fractionDigits = 2): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "—";
  }
  return new Intl.NumberFormat("en-GB", {
    style: "currency",
    currency: "USD",
    currencyDisplay: "narrowSymbol",
    minimumFractionDigits: fractionDigits,
    maximumFractionDigits: fractionDigits,
  }).format(value);
}

/** Format a measured provider cost without hiding sub-cent amounts. */
export function formatCostUsd(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "—";
  }
  if (value === 0) {
    return "$0.00";
  }
  const fractionDigits = value < 0.01 ? 4 : value < 1 ? 3 : 2;
  return formatUsd(value, fractionDigits);
}

export function formatDateTime(unixSeconds: number): string {
  if (!Number.isFinite(unixSeconds) || unixSeconds <= 0) {
    return "—";
  }
  return new Intl.DateTimeFormat("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(unixSeconds * 1000));
}

export function formatConfidence(value: number | null): string {
  if (value === null || !Number.isFinite(value)) {
    return "—";
  }
  return `${Math.round(Math.min(Math.max(value, 0), 1) * 100)}%`;
}

export function confidenceTone(value: number | null): "strong" | "medium" | "weak" | "unknown" {
  if (value === null || !Number.isFinite(value)) {
    return "unknown";
  }
  if (value >= 0.7) {
    return "strong";
  }
  if (value >= 0.4) {
    return "medium";
  }
  return "weak";
}

export function truncateMiddle(value: string, head = 8, tail = 4): string {
  if (value.length <= head + tail + 1) {
    return value;
  }
  return `${value.slice(0, head)}…${value.slice(value.length - tail)}`;
}

export function truncate(value: string, maxLength = 160): string {
  if (value.length <= maxLength) {
    return value;
  }
  return `${value.slice(0, Math.max(0, maxLength - 1))}…`;
}

/** Render an arbitrary JSON value as a short, single-line preview. */
export function formatJsonValue(value: unknown, maxLength = 180): string {
  if (value === null || value === undefined) {
    return "—";
  }
  if (typeof value === "string") {
    return truncate(value, maxLength);
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  try {
    return truncate(JSON.stringify(value), maxLength);
  } catch {
    return String(value);
  }
}

export function prettyJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2) ?? String(value);
  } catch {
    return String(value);
  }
}

export function pluralize(count: number, singular: string, plural?: string): string {
  return count === 1 ? singular : (plural ?? `${singular}s`);
}

export function humanizeKey(key: string): string {
  const words = key.replace(/[_-]+/g, " ").trim();
  return words.length > 0 ? words.charAt(0).toUpperCase() + words.slice(1) : key;
}

const ARTIFACT_KIND_LABELS: Record<string, string> = {
  docx: "DOCX document",
  ir: "Template IR",
  mapping: "Mapping JSON",
  validation: "Validation JSON",
  validation_html: "Validation HTML",
  preview: "Preview HTML",
};

export function artifactKindLabel(kind: string): string {
  return ARTIFACT_KIND_LABELS[kind] ?? humanizeKey(kind);
}

export function formatProviderLabel(provider: string, configured: boolean): string {
  return configured ? provider : `${provider} (not configured)`;
}
