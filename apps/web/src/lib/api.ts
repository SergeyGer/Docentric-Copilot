/**
 * Typed fetch wrapper for the Docentric Copilot REST API.
 *
 * Every failure is normalised to {@link ApiError}: HTTP errors carry the
 * backend's `{ error: { code, message, details } }` envelope, while network
 * failures and timeouts are reported with status `0`.
 */

import { isRecord } from "@/lib/guards";
import type {
  ReferenceDiff,
  ReferenceGraph,
  ReferenceReport,
  ReferenceReportExportFormat,
  StoredReferenceReport,
} from "@/lib/types";

// Same origin by default: Next.js proxies /api/v1/* to the backend, so the
// browser only needs the web port. Set NEXT_PUBLIC_API_BASE_URL to call a
// different origin directly (for example a hosted API).
const DEFAULT_API_BASE_URL = "";
const DEFAULT_TIMEOUT_MS = 30_000;

function resolveBaseUrl(): string {
  const configured = process.env.NEXT_PUBLIC_API_BASE_URL;
  const value = configured && configured.trim().length > 0 ? configured.trim() : DEFAULT_API_BASE_URL;
  return value.replace(/\/+$/, "");
}

/** Base URL of the API this build talks to (no trailing slash). */
export const API_BASE_URL = resolveBaseUrl();

export interface ApiErrorInit {
  status?: number;
  code?: string;
  details?: Record<string, unknown> | null;
}

/** A failed API call, already normalised for display in the UI. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown> | null;

  constructor(message: string, init: ApiErrorInit = {}) {
    super(message);
    this.name = "ApiError";
    this.status = init.status ?? 0;
    this.code = init.code ?? "request_failed";
    this.details = init.details ?? null;
  }

  static async fromResponse(response: Response): Promise<ApiError> {
    let code = `http_${response.status}`;
    let message = `The API returned HTTP ${response.status}.`;
    let details: Record<string, unknown> | null = null;

    try {
      const text = await response.text();
      if (text) {
        const payload: unknown = JSON.parse(text);
        if (isRecord(payload) && isRecord(payload.error)) {
          const envelope = payload.error;
          if (typeof envelope.code === "string" && envelope.code) {
            code = envelope.code;
          }
          if (typeof envelope.message === "string" && envelope.message) {
            message = envelope.message;
          }
          if (isRecord(envelope.details)) {
            details = envelope.details;
          } else if (envelope.details !== undefined && envelope.details !== null) {
            details = { value: envelope.details };
          }
        }
      }
    } catch {
      // The body was not the documented JSON envelope; keep the HTTP fallback.
    }

    return new ApiError(message, { status: response.status, code, details });
  }
}

/** Normalise an arbitrary thrown value to an {@link ApiError} for display. */
export function toApiError(error: unknown): ApiError {
  if (error instanceof ApiError) {
    return error;
  }
  return new ApiError("An unexpected client error occurred.", {
    code: "client_error",
    details: { reason: error instanceof Error ? error.message : String(error) },
  });
}

export interface ApiRequestOptions {
  timeoutMs?: number;
}

export interface ApiRequestInit extends RequestInit {
  /** Abort after this many milliseconds (defaults to 30s). */
  timeoutMs?: number;
}

export function apiUrl(path: string): string {
  if (/^https?:\/\//i.test(path)) {
    return path;
  }
  return `${API_BASE_URL}${path.startsWith("/") ? path : `/${path}`}`;
}

/**
 * Run a fetch with an abort-based timeout, then consume the body inside the same
 * guarded scope so slow or stalled responses are covered by the timeout too.
 */
async function withResponse<T>(
  path: string,
  init: ApiRequestInit,
  options: ApiRequestOptions,
  consume: (response: Response) => Promise<T>,
): Promise<T> {
  const { timeoutMs: initTimeout, ...requestInit } = init;
  const timeoutMs = options.timeoutMs ?? initTimeout ?? DEFAULT_TIMEOUT_MS;

  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);

  const externalSignal = requestInit.signal;
  const onExternalAbort = () => controller.abort();
  if (externalSignal) {
    if (externalSignal.aborted) {
      controller.abort();
    } else {
      externalSignal.addEventListener("abort", onExternalAbort, { once: true });
    }
  }

  const headers = new Headers(requestInit.headers);
  if (!headers.has("Accept")) {
    headers.set("Accept", "application/json, text/html;q=0.9, */*;q=0.8");
  }
  if (requestInit.body && !(requestInit.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  try {
    const response = await fetch(apiUrl(path), {
      ...requestInit,
      headers,
      signal: controller.signal,
    });
    if (!response.ok) {
      throw await ApiError.fromResponse(response);
    }
    return await consume(response);
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    if (timedOut) {
      throw new ApiError(
        `The request timed out after ${Math.round(timeoutMs / 1000)} seconds.`,
        {
          status: 0,
          code: "request_timeout",
          details: { path, timeout_ms: timeoutMs },
        },
      );
    }
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new ApiError("The request was cancelled.", {
        status: 0,
        code: "request_cancelled",
        details: { path },
      });
    }
    throw new ApiError(
      "Could not reach the API. Check that the backend is running and that NEXT_PUBLIC_API_BASE_URL points to it.",
      {
        status: 0,
        code: "network_error",
        details: {
          path,
          base_url: API_BASE_URL,
          reason: error instanceof Error ? error.message : String(error),
        },
      },
    );
  } finally {
    clearTimeout(timer);
    externalSignal?.removeEventListener("abort", onExternalAbort);
  }
}

/** Perform a request and parse the JSON response body. */
export async function apiRequest<T>(
  path: string,
  init: ApiRequestInit = {},
  options: ApiRequestOptions = {},
): Promise<T> {
  return withResponse(path, init, options, async (response) => {
    if (response.status === 204) {
      return undefined as T;
    }
    const text = await response.text();
    if (!text) {
      return undefined as T;
    }
    try {
      return JSON.parse(text) as T;
    } catch {
      throw new ApiError("The API returned a response that was not valid JSON.", {
        status: response.status,
        code: "invalid_response",
        details: { path },
      });
    }
  });
}

/** Perform a request and return the raw response body as text (HTML preview). */
export async function apiRequestText(
  path: string,
  init: ApiRequestInit = {},
  options: ApiRequestOptions = {},
): Promise<string> {
  return withResponse(path, init, options, (response) => response.text());
}

/** POST a JSON body with the conventional headers. */
export function postJson<T>(
  path: string,
  body: unknown,
  options: ApiRequestOptions = {},
): Promise<T> {
  return apiRequest<T>(
    path,
    {
      method: "POST",
      body: JSON.stringify(body),
      headers: { "Content-Type": "application/json" },
    },
    options,
  );
}

/**
 * Reference inspection can walk large ZIP/AXPP containers, so it gets a longer
 * timeout than ordinary JSON calls. The endpoint is strictly read-only.
 */
const REFERENCE_REQUEST_TIMEOUT_MS = 180_000;

function appendUpload(formData: FormData, field: string, file: File): void {
  formData.append(field, file, file.name);
}

/** POST a multipart body; Content-Type is left to the browser boundary. */
export function postMultipart<T>(
  path: string,
  formData: FormData,
  options: ApiRequestOptions = {},
): Promise<T> {
  return apiRequest<T>(path, { method: "POST", body: formData }, options);
}

/** `POST /api/v1/reference/inspect` — read-only reference report. */
export function inspectReference(
  file: File,
  ddsp: File | null = null,
  options: ApiRequestOptions = {},
): Promise<ReferenceReport> {
  const body = new FormData();
  appendUpload(body, "file", file);
  if (ddsp) {
    appendUpload(body, "ddsp", ddsp);
  }
  return postMultipart<ReferenceReport>("/api/v1/reference/inspect", body, {
    timeoutMs: REFERENCE_REQUEST_TIMEOUT_MS,
    ...options,
  });
}

/** `POST /api/v1/reference/graph` — read-only ReferenceGraph. */
export function buildReferenceGraph(
  file: File,
  ddsp: File | null = null,
  options: ApiRequestOptions = {},
): Promise<ReferenceGraph> {
  const body = new FormData();
  appendUpload(body, "file", file);
  if (ddsp) {
    appendUpload(body, "ddsp", ddsp);
  }
  return postMultipart<ReferenceGraph>("/api/v1/reference/graph", body, {
    timeoutMs: REFERENCE_REQUEST_TIMEOUT_MS,
    ...options,
  });
}

/**
 * `POST /api/v1/reference/reports?kind=inspection` — run the read-only
 * inspection and persist the report + graph with a TTL.
 */
export function persistReferenceInspection(
  file: File,
  ddsp: File | null = null,
  options: ApiRequestOptions = {},
): Promise<StoredReferenceReport> {
  const body = new FormData();
  appendUpload(body, "file", file);
  if (ddsp) {
    appendUpload(body, "ddsp", ddsp);
  }
  return postMultipart<StoredReferenceReport>(
    "/api/v1/reference/reports?kind=inspection",
    body,
    { timeoutMs: REFERENCE_REQUEST_TIMEOUT_MS, ...options },
  );
}

/** `GET /api/v1/reference/reports/{id}` — reopen a persisted report. */
export function getStoredReferenceReport(
  reportId: string,
  options: ApiRequestOptions = {},
): Promise<StoredReferenceReport> {
  const encoded = encodeURIComponent(reportId);
  return apiRequest<StoredReferenceReport>(`/api/v1/reference/reports/${encoded}`, {}, options);
}

/** Download path for a persisted report export (JSON or safe HTML). */
export function referenceReportExportPath(
  reportId: string,
  format: ReferenceReportExportFormat,
): string {
  if (format !== "json" && format !== "html") {
    throw new Error("Unsupported reference report export format");
  }
  const encoded = encodeURIComponent(reportId);
  return `/api/v1/reference/reports/${encoded}/export?format=${format}`;
}

/** `POST /api/v1/reference/diff` — read-only structural/semantic comparison. */
export function diffReferences(
  left: File,
  right: File,
  ddsp: File | null = null,
  options: ApiRequestOptions = {},
): Promise<ReferenceDiff> {
  const body = new FormData();
  appendUpload(body, "left", left);
  appendUpload(body, "right", right);
  if (ddsp) {
    appendUpload(body, "ddsp", ddsp);
  }
  return postMultipart<ReferenceDiff>("/api/v1/reference/diff", body, {
    timeoutMs: REFERENCE_REQUEST_TIMEOUT_MS,
    ...options,
  });
}

/**
 * Resolve an API download path to an absolute HTTP(S) URL.
 *
 * `path` can originate from a DOM value (for example the selected export
 * format). Browsers treat `javascript:` and `data:` hrefs as executable or
 * navigable content, so the protocol is checked against an allowlist before the
 * value reaches an anchor. CodeQL flagged the previous direct assignment as
 * `js/xss-through-dom` (code scanning alert #10).
 */
function resolveDownloadUrl(path: string): URL {
  const base = typeof window === "undefined" ? "http://localhost/" : window.location.href;
  const url = new URL(apiUrl(path), base);
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new Error(`Refusing to download a non-HTTP(S) URL: ${url.protocol}`);
  }
  return url;
}

/**
 * Start a browser download of an API artifact.
 *
 * The backend replies with `Content-Disposition: attachment`, so a synthetic
 * anchor is enough even though the API origin differs from the web origin.
 */
export function triggerDownload(path: string, filename?: string): void {
  if (typeof document === "undefined") {
    return;
  }
  const href = resolveDownloadUrl(path).href;
  if (!href.startsWith("http://") && !href.startsWith("https://")) {
    throw new Error("Refusing to download a non-HTTP(S) URL");
  }
  const anchor = document.createElement("a");
  anchor.setAttribute("href", href);
  anchor.rel = "noopener";
  if (filename) {
    anchor.download = filename;
  }
  anchor.style.display = "none";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
}
