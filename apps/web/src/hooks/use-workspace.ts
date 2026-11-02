"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  ApiError,
  apiRequest,
  apiRequestText,
  postJson,
  triggerDownload,
} from "@/lib/api";
import { copyToClipboard } from "@/lib/clipboard";
import {
  ACCEPTED_SOURCE_EXTENSIONS,
  DEFAULT_DEMO_CASE_ID,
  DEFAULT_DOCUMENT_NAME,
  EXAMPLE_PROMPT,
  FALLBACK_MAX_UPLOAD_BYTES,
  INSTRUCTION_MAX_LENGTH,
  PROMPT_MAX_LENGTH,
} from "@/lib/constants";
import { isRecord } from "@/lib/guards";
import type {
  ArtifactView,
  CapabilitiesView,
  CheckStatus,
  CompileRequest,
  CompileResponse,
  ConfirmMappingRequest,
  ConfirmMappingResponse,
  DemoCase,
  DemoSessionRequest,
  DemoSessionResponse,
  DemoTourStep,
  DesignStyle,
  Diagnostic,
  GenerationInfo,
  MappingReport,
  PlanRequest,
  PlanResponse,
  PreviewRequest,
  ProviderView,
  RemovedBinding,
  RenderMode,
  RevisionRequest,
  RevisionResponse,
  SchemaView,
  SourceView,
  TemplateIr,
  TemplateVersionDetail,
  ValidationReport,
  ValidationStatuses,
  VersionSummary,
  VersionsResponse,
} from "@/lib/types";
import { deriveStatuses, overallFromStatuses } from "@/lib/validation";

export type ErrorScope =
  | "providers"
  | "upload"
  | "schema"
  | "plan"
  | "compile"
  | "revise"
  | "review"
  | "preview"
  | "versions"
  | "load-version"
  | "demo"
  | "demo-examples";

export type ToastTone = "info" | "success" | "error";

export interface ToastState {
  id: number;
  message: string;
  tone: ToastTone;
}

export interface ConfirmPending {
  requirementId: string;
  mode: "selected" | "confirm";
}

export interface CompareVersions {
  left: number;
  right: number;
}

export interface ComparePreviewState {
  html: string | null;
  pending: boolean;
  error: ApiError | null;
}

export interface MappingFocusRequest {
  path: string;
  token: number;
}

interface ValidationFailure {
  statuses: ValidationStatuses;
  report: ValidationReport | null;
}

const CHECK_STATUSES: readonly CheckStatus[] = [
  "passed",
  "failed",
  "warning",
  "skipped",
  "not_tested",
];

function toApiError(error: unknown): ApiError {
  if (error instanceof ApiError) {
    return error;
  }
  return new ApiError("An unexpected client error occurred.", {
    code: "client_error",
    details: { reason: error instanceof Error ? error.message : String(error) },
  });
}

function isCheckStatus(value: unknown): value is CheckStatus {
  return typeof value === "string" && (CHECK_STATUSES as readonly string[]).includes(value);
}

function coerceStatuses(value: unknown): ValidationStatuses | null {
  if (!isRecord(value)) {
    return null;
  }
  const structural = value.structural;
  const semantic = value.semantic;
  const logical = value.logical;
  const visual = value.visual;
  const compatibility = value.docentric_compatibility;
  if (
    !isCheckStatus(structural) ||
    !isCheckStatus(semantic) ||
    !isCheckStatus(logical) ||
    !isCheckStatus(visual) ||
    !isCheckStatus(compatibility)
  ) {
    return null;
  }
  return {
    structural,
    semantic,
    logical,
    visual,
    docentric_compatibility: compatibility,
  };
}

function isValidationReport(value: unknown): value is ValidationReport {
  return (
    isRecord(value) &&
    typeof value.target === "string" &&
    Array.isArray(value.checks) &&
    value.checks.every((check) => isRecord(check))
  );
}

function extractValidationFailure(error: ApiError): ValidationFailure | null {
  const details = error.details;
  if (!details) {
    return null;
  }
  const report = isValidationReport(details.report) ? details.report : null;
  const statuses = coerceStatuses(details.validation) ?? (report ? deriveStatuses(report) : null);
  if (!statuses) {
    return null;
  }
  return { statuses, report };
}

function isSourceFileAllowed(filename: string): boolean {
  const lower = filename.toLowerCase();
  return ACCEPTED_SOURCE_EXTENSIONS.some((extension) => lower.endsWith(extension));
}

function extensionList(): string {
  return ACCEPTED_SOURCE_EXTENSIONS.join(", ");
}

export function useWorkspace() {
  /* -------------------------------------------------------------- system */

  const [providers, setProviders] = useState<ProviderView[]>([]);
  const [providersPending, setProvidersPending] = useState(false);
  const [capabilities, setCapabilities] = useState<CapabilitiesView | null>(null);

  /* ---------------------------------------------------------------- demo */

  const [demoCases, setDemoCases] = useState<DemoCase[]>([]);
  const [demoCasesPending, setDemoCasesPending] = useState(false);
  const [demoCaseId, setDemoCaseId] = useState(DEFAULT_DEMO_CASE_ID);
  const [demoPending, setDemoPending] = useState(false);
  const [tourSteps, setTourSteps] = useState<DemoTourStep[] | null>(null);

  /* -------------------------------------------------------------- source */

  const [source, setSource] = useState<SourceView | null>(null);
  const [schemaView, setSchemaView] = useState<SchemaView | null>(null);
  const [uploadPending, setUploadPending] = useState(false);
  const [schemaPending, setSchemaPending] = useState(false);

  /* -------------------------------------------------------------- prompt */

  const [prompt, setPrompt] = useState(EXAMPLE_PROMPT);
  const [provider, setProvider] = useState("mock");
  const [model, setModel] = useState("");
  const [designStyle, setDesignStyle] = useState<DesignStyle>("modern");
  const [language, setLanguage] = useState("en");
  const [strictValidation, setStrictValidation] = useState(true);
  const [maxCost, setMaxCost] = useState("0.50");
  const [maxRepairAttempts, setMaxRepairAttempts] = useState(1);

  /* ------------------------------------------------------------ template */

  const [plan, setPlan] = useState<PlanResponse | null>(null);
  const [templateId, setTemplateId] = useState<string | null>(null);
  const [activeVersion, setActiveVersion] = useState<number | null>(null);
  const [ir, setIr] = useState<TemplateIr | null>(null);
  const [irDigest, setIrDigest] = useState<string | null>(null);
  const [mapping, setMapping] = useState<MappingReport | null>(null);
  const [validation, setValidation] = useState<ValidationStatuses | null>(null);
  const [report, setReport] = useState<ValidationReport | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [removedBindings, setRemovedBindings] = useState<RemovedBinding[]>([]);
  const [generation, setGeneration] = useState<GenerationInfo | null>(null);
  const [artifacts, setArtifacts] = useState<ArtifactView[]>([]);
  const [selectedMappingPath, setSelectedMappingPath] = useState<string | null>(null);
  const [activePreviewPath, setActivePreviewPath] = useState<string | null>(null);
  const [mappingFocus, setMappingFocus] = useState<MappingFocusRequest | null>(null);
  const [confirmPending, setConfirmPending] = useState<ConfirmPending | null>(null);

  /* ------------------------------------------------------------- compile */

  const [planPending, setPlanPending] = useState(false);
  const [compilePending, setCompilePending] = useState(false);
  const [compileResult, setCompileResult] = useState<CompileResponse | null>(null);
  const [documentName, setDocumentName] = useState(DEFAULT_DOCUMENT_NAME);
  const [renderMode, setRenderMode] = useState<RenderMode>("auto");
  const [includeCompatibilityStamp, setIncludeCompatibilityStamp] = useState(false);
  const [useSampleData, setUseSampleData] = useState(true);

  /* ------------------------------------------------------------ revision */

  const [instruction, setInstruction] = useState("");
  const [revisionPending, setRevisionPending] = useState(false);
  const [revision, setRevision] = useState<RevisionResponse | null>(null);
  const [versions, setVersions] = useState<VersionSummary[]>([]);
  const [versionsPending, setVersionsPending] = useState(false);
  const [loadingVersion, setLoadingVersion] = useState<number | null>(null);
  const [compareVersions, setCompareVersions] = useState<CompareVersions | null>(null);
  const [compareOpen, setCompareOpen] = useState(false);
  const [comparePreviews, setComparePreviews] = useState<Record<number, ComparePreviewState>>(
    {},
  );

  /* ------------------------------------------------------------- preview */

  const [previewHtml, setPreviewHtml] = useState<string | null>(null);
  const [previewVersion, setPreviewVersion] = useState<number | null>(null);
  const [previewPending, setPreviewPending] = useState(false);

  /* --------------------------------------------------------------- errors */

  const [errors, setErrors] = useState<Partial<Record<ErrorScope, ApiError>>>({});
  const [toast, setToast] = useState<ToastState | null>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const previewRequestId = useRef(0);
  const schemaRequestId = useRef(0);
  const versionsRequestId = useRef(0);
  const mappingFocusToken = useRef(0);
  const confirmLock = useRef(false);
  const demoLock = useRef(false);

  const setScopeError = useCallback((scope: ErrorScope, error: ApiError) => {
    setErrors((previous) => ({ ...previous, [scope]: error }));
  }, []);

  const dismissError = useCallback((scope: ErrorScope) => {
    setErrors((previous) => {
      if (!previous[scope]) {
        return previous;
      }
      const next = { ...previous };
      delete next[scope];
      return next;
    });
  }, []);

  const notify = useCallback((message: string, tone: ToastTone = "info") => {
    setToast({ id: Date.now(), message, tone });
    if (toastTimer.current) {
      clearTimeout(toastTimer.current);
    }
    toastTimer.current = setTimeout(() => {
      setToast(null);
      toastTimer.current = null;
    }, 4_500);
  }, []);

  const dismissToast = useCallback(() => {
    if (toastTimer.current) {
      clearTimeout(toastTimer.current);
      toastTimer.current = null;
    }
    setToast(null);
  }, []);

  useEffect(
    () => () => {
      if (toastTimer.current) {
        clearTimeout(toastTimer.current);
      }
    },
    [],
  );

  const copyPath = useCallback(
    async (path: string) => {
      const copied = await copyToClipboard(path);
      notify(
        copied ? `Copied path: ${path}` : "Could not copy the path to the clipboard.",
        copied ? "success" : "error",
      );
    },
    [notify],
  );

  /* --------------------------------------------------------------- system */

  const loadProviders = useCallback(async () => {
    setProvidersPending(true);
    dismissError("providers");
    try {
      const list = await apiRequest<ProviderView[]>("/api/v1/providers", {}, { timeoutMs: 15_000 });
      setProviders(list);
      setProvider((current) => {
        const match = list.find((item) => item.name === current);
        if (match?.configured) {
          return match.name;
        }
        const mock = list.find((item) => item.name === "mock" && item.configured);
        const configured = list.find((item) => item.configured);
        return (mock ?? configured ?? list[0])?.name ?? current;
      });
    } catch (error) {
      setScopeError("providers", toApiError(error));
    } finally {
      setProvidersPending(false);
    }
  }, [dismissError, setScopeError]);

  const loadCapabilities = useCallback(async () => {
    try {
      const data = await apiRequest<CapabilitiesView>(
        "/api/v1/capabilities",
        {},
        { timeoutMs: 10_000 },
      );
      setCapabilities(data);
    } catch {
      // Capabilities are optional metadata (upload limit, target availability).
      // The UI falls back to the documented defaults when this call fails.
      setCapabilities(null);
    }
  }, []);

  useEffect(() => {
    void loadProviders();
    void loadCapabilities();
  }, [loadCapabilities, loadProviders]);

  const modelInitialised = useRef(false);
  useEffect(() => {
    if (modelInitialised.current || providers.length === 0) {
      return;
    }
    modelInitialised.current = true;
    const selected =
      providers.find((item) => item.name === provider) ??
      providers.find((item) => item.name === "mock") ??
      providers[0];
    if (selected?.default_model) {
      setModel((current) => (current.length > 0 ? current : selected.default_model ?? ""));
    }
  }, [provider, providers]);

  const changeProvider = useCallback(
    (name: string) => {
      setProvider(name);
      const info = providers.find((item) => item.name === name);
      setModel(info?.default_model ?? "");
    },
    [providers],
  );

  const selectedProvider = useMemo(
    () => providers.find((item) => item.name === provider) ?? null,
    [provider, providers],
  );

  /* --------------------------------------------------------------- source */

  const resetTemplateState = useCallback(() => {
    setPlan(null);
    setTemplateId(null);
    setActiveVersion(null);
    setIr(null);
    setIrDigest(null);
    setMapping(null);
    setValidation(null);
    setReport(null);
    setWarnings([]);
    setRemovedBindings([]);
    setGeneration(null);
    setArtifacts([]);
    setCompileResult(null);
    setRevision(null);
    setVersions([]);
    setVersionsPending(false);
    setPreviewHtml(null);
    setPreviewVersion(null);
    setPreviewPending(false);
    previewRequestId.current += 1;
    versionsRequestId.current += 1;
    setSelectedMappingPath(null);
    setActivePreviewPath(null);
    setMappingFocus(null);
    setConfirmPending(null);
    setCompareVersions(null);
    setCompareOpen(false);
    setComparePreviews({});
    setTourSteps(null);
    setLoadingVersion(null);
    setErrors((previous) => {
      const next = { ...previous };
      const scopes: ErrorScope[] = [
        "plan",
        "compile",
        "revise",
        "review",
        "preview",
        "versions",
        "load-version",
      ];
      for (const scope of scopes) {
        delete next[scope];
      }
      return next;
    });
  }, []);

  const loadSchemaFor = useCallback(
    async (sourceId: string) => {
      const requestId = schemaRequestId.current + 1;
      schemaRequestId.current = requestId;
      setSchemaPending(true);
      dismissError("schema");
      try {
        const data = await apiRequest<SchemaView>(
          `/api/v1/sources/${encodeURIComponent(sourceId)}/schema`,
          {},
          { timeoutMs: 30_000 },
        );
        if (requestId !== schemaRequestId.current) {
          return;
        }
        setSchemaView(data);
      } catch (error) {
        if (requestId !== schemaRequestId.current) {
          return;
        }
        setScopeError("schema", toApiError(error));
      } finally {
        if (requestId === schemaRequestId.current) {
          setSchemaPending(false);
        }
      }
    },
    [dismissError, setScopeError],
  );

  const uploadSource = useCallback(
    async (file: File) => {
      if (uploadPending) {
        return;
      }
      if (!isSourceFileAllowed(file.name)) {
        setScopeError(
          "upload",
          new ApiError(`Unsupported file type. Choose one of: ${extensionList()}.`, {
            code: "client_unsupported_file",
            details: { filename: file.name, allowed: [...ACCEPTED_SOURCE_EXTENSIONS] },
          }),
        );
        return;
      }
      const maxBytes = capabilities?.limits.max_ddsp_bytes ?? FALLBACK_MAX_UPLOAD_BYTES;
      if (file.size > maxBytes) {
        setScopeError(
          "upload",
          new ApiError("The selected file is larger than the API upload limit.", {
            code: "client_file_too_large",
            details: { filename: file.name, size_bytes: file.size, max_bytes: maxBytes },
          }),
        );
        return;
      }

      setUploadPending(true);
      dismissError("upload");
      dismissError("schema");
      try {
        const formData = new FormData();
        formData.append("file", file, file.name);
        const uploaded = await apiRequest<SourceView>(
          "/api/v1/sources",
          { method: "POST", body: formData },
          { timeoutMs: 120_000 },
        );
        resetTemplateState();
        setSource(uploaded);
        setSchemaView(null);
        notify(`Uploaded ${uploaded.filename}.`, "success");
        await loadSchemaFor(uploaded.source_id);
      } catch (error) {
        setScopeError("upload", toApiError(error));
      } finally {
        setUploadPending(false);
      }
    },
    [
      capabilities,
      dismissError,
      loadSchemaFor,
      notify,
      resetTemplateState,
      setScopeError,
      uploadPending,
    ],
  );

  const reloadSchema = useCallback(() => {
    if (!source) {
      return;
    }
    void loadSchemaFor(source.source_id);
  }, [loadSchemaFor, source]);

  const diagnostics = useMemo<Diagnostic[]>(
    () => schemaView?.diagnostics ?? source?.diagnostics ?? [],
    [schemaView, source],
  );

  /* ---------------------------------------------------------------- plan */

  const fetchVersions = useCallback(
    async (templateIdValue: string) => {
      const requestId = versionsRequestId.current + 1;
      versionsRequestId.current = requestId;
      setVersionsPending(true);
      dismissError("versions");
      try {
        const data = await apiRequest<VersionsResponse>(
          `/api/v1/templates/${encodeURIComponent(templateIdValue)}/versions`,
          {},
          { timeoutMs: 15_000 },
        );
        if (requestId !== versionsRequestId.current) {
          return;
        }
        setVersions([...data.versions].sort((left, right) => left.version - right.version));
      } catch (error) {
        if (requestId !== versionsRequestId.current) {
          return;
        }
        setScopeError("versions", toApiError(error));
      } finally {
        if (requestId === versionsRequestId.current) {
          setVersionsPending(false);
        }
      }
    },
    [dismissError, setScopeError],
  );

  /** Render a preview request and keep only the latest response. */
  const requestPreview = useCallback(
    async (body: PreviewRequest, versionValue: number) => {
      const requestId = previewRequestId.current + 1;
      previewRequestId.current = requestId;
      setPreviewPending(true);
      dismissError("preview");
      try {
        const html = await apiRequestText(
          "/api/v1/templates/preview",
          {
            method: "POST",
            body: JSON.stringify(body),
            headers: { "Content-Type": "application/json" },
          },
          { timeoutMs: 60_000 },
        );
        if (requestId !== previewRequestId.current) {
          return;
        }
        setPreviewHtml(html);
        setPreviewVersion(versionValue);
        setActivePreviewPath(null);
      } catch (error) {
        if (requestId !== previewRequestId.current) {
          return;
        }
        setScopeError("preview", toApiError(error));
      } finally {
        if (requestId === previewRequestId.current) {
          setPreviewPending(false);
        }
      }
    },
    [dismissError, setScopeError],
  );

  const fetchPreviewFor = useCallback(
    async (templateIdValue: string, versionValue: number) => {
      if (!source) {
        setScopeError(
          "preview",
          new ApiError("Upload a data source before rendering a preview.", {
            code: "client_source_required",
          }),
        );
        return;
      }
      await requestPreview(
        {
          source_id: source.source_id,
          template_id: templateIdValue,
          version: versionValue,
        },
        versionValue,
      );
    },
    [requestPreview, setScopeError, source],
  );

  /** Re-render the preview from an inline IR (review confirmations). */
  const fetchPreviewFromIr = useCallback(
    async (irValue: TemplateIr, versionValue: number) => {
      if (!source) {
        setScopeError(
          "preview",
          new ApiError("Upload a data source before rendering a preview.", {
            code: "client_source_required",
          }),
        );
        return;
      }
      await requestPreview(
        {
          source_id: source.source_id,
          template_id: null,
          version: null,
          ir: irValue,
        },
        versionValue,
      );
    },
    [requestPreview, setScopeError, source],
  );

  const planTemplate = useCallback(async () => {
    if (planPending) {
      return;
    }
    if (!source) {
      setScopeError(
        "plan",
        new ApiError("Upload a data source before planning a template.", {
          code: "client_source_required",
        }),
      );
      return;
    }
    const trimmedPrompt = prompt.trim();
    if (trimmedPrompt.length < 3) {
      setScopeError(
        "plan",
        new ApiError("The prompt must be at least 3 characters long.", {
          code: "client_prompt_too_short",
          details: { field: "prompt", length: trimmedPrompt.length },
        }),
      );
      return;
    }
    if (prompt.length > PROMPT_MAX_LENGTH) {
      setScopeError(
        "plan",
        new ApiError(`The prompt must be at most ${PROMPT_MAX_LENGTH} characters.`, {
          code: "client_prompt_too_long",
          details: { field: "prompt", length: prompt.length, max_length: PROMPT_MAX_LENGTH },
        }),
      );
      return;
    }
    const trimmedLanguage = language.trim();
    if (!/^[a-z]{2}(-[A-Z]{2})?$/.test(trimmedLanguage)) {
      setScopeError(
        "plan",
        new ApiError("Language must look like 'en' or 'en-US'.", {
          code: "client_language_invalid",
          details: { field: "language", value: trimmedLanguage },
        }),
      );
      return;
    }
    const parsedCost = Number.parseFloat(maxCost);
    if (!Number.isFinite(parsedCost) || parsedCost < 0 || parsedCost > 50) {
      setScopeError(
        "plan",
        new ApiError("The generation cost cap must be a number between 0 and 50 USD.", {
          code: "client_cost_invalid",
          details: { field: "max_generation_cost_usd", value: maxCost },
        }),
      );
      return;
    }

    resetTemplateState();
    setPlanPending(true);
    try {
      const body: PlanRequest = {
        source_id: source.source_id,
        prompt: trimmedPrompt,
        provider,
        model: model.trim().length > 0 ? model.trim() : null,
        design_style: designStyle,
        target: "generic-docx",
        options: {
          language: trimmedLanguage,
          strict_validation: strictValidation,
          max_generation_cost_usd: parsedCost,
          max_repair_attempts: maxRepairAttempts,
        },
      };
      const response = await postJson<PlanResponse>("/api/v1/templates/plan", body, {
        timeoutMs: 180_000,
      });
      setPlan(response);
      setTemplateId(response.template_id);
      setActiveVersion(response.version);
      setIr(response.ir);
      setIrDigest(response.ir_digest);
      setMapping(response.mapping);
      setValidation(response.validation);
      setReport(response.report);
      setWarnings(response.warnings ?? []);
      setRemovedBindings(response.removed_bindings ?? []);
      setGeneration(response.generation);
      setArtifacts(response.artifacts ?? []);
      setSelectedMappingPath(null);
      notify("Template planned. Review the mapping and validation.", "success");
      void fetchVersions(response.template_id);
      void fetchPreviewFor(response.template_id, response.version);
    } catch (error) {
      const apiError = toApiError(error);
      setScopeError("plan", apiError);
      const failure = extractValidationFailure(apiError);
      if (failure) {
        setValidation(failure.statuses);
        setReport(failure.report);
      }
    } finally {
      setPlanPending(false);
    }
  }, [
    designStyle,
    fetchPreviewFor,
    fetchVersions,
    language,
    maxCost,
    maxRepairAttempts,
    model,
    notify,
    planPending,
    prompt,
    provider,
    resetTemplateState,
    setScopeError,
    source,
    strictValidation,
  ]);

  const useExamplePrompt = useCallback(() => {
    setPrompt(EXAMPLE_PROMPT);
    notify("Example prompt loaded.", "info");
  }, [notify]);

  const insertPathIntoPrompt = useCallback(
    (path: string): boolean => {
      if (prompt.includes(path)) {
        notify("That path is already in the prompt.", "info");
        return false;
      }
      const next =
        prompt.trim().length === 0 ? path : `${prompt.trimEnd()}\n${path}`;
      if (next.length > PROMPT_MAX_LENGTH) {
        notify(
          `The prompt is limited to ${PROMPT_MAX_LENGTH.toLocaleString("en-GB")} characters. Shorten it before inserting another path.`,
          "error",
        );
        return false;
      }
      setPrompt(next);
      notify(`Inserted ${path} into the prompt.`, "success");
      return true;
    },
    [notify, prompt],
  );

  /* -------------------------------------------------------------- compile */

  const downloadArtifact = useCallback(
    (artifact: ArtifactView) => {
      triggerDownload(artifact.url, artifact.filename);
      notify(`Downloading ${artifact.filename}.`, "info");
    },
    [notify],
  );

  const compileTemplate = useCallback(async () => {
    if (compilePending) {
      return;
    }
    if (!source || !templateId || activeVersion === null) {
      setScopeError(
        "compile",
        new ApiError("Plan a template before compiling a DOCX.", {
          code: "client_template_required",
        }),
      );
      return;
    }
    const trimmedName = documentName.trim();
    if (trimmedName.length === 0) {
      setScopeError(
        "compile",
        new ApiError("Give the document a file name.", {
          code: "client_document_name_required",
          details: { field: "document_name" },
        }),
      );
      return;
    }
    const normalizedName = /\.docx$/i.test(trimmedName) ? trimmedName : `${trimmedName}.docx`;
    if (normalizedName.length > 120) {
      setScopeError(
        "compile",
        new ApiError("The document name must be at most 120 characters.", {
          code: "client_document_name_too_long",
          details: { field: "document_name", max_length: 120 },
        }),
      );
      return;
    }
    setDocumentName(normalizedName);
    setCompilePending(true);
    dismissError("compile");
    try {
      const body: CompileRequest = {
        source_id: source.source_id,
        template_id: templateId,
        version: activeVersion,
        target: "generic-docx",
        options: {
          render_mode: renderMode,
          include_compatibility_stamp: includeCompatibilityStamp,
          document_name: normalizedName,
          use_sample_data: useSampleData,
        },
      };
      const response = await postJson<CompileResponse>("/api/v1/templates/compile", body, {
        timeoutMs: 180_000,
      });
      setCompileResult(response);
      setArtifacts(response.artifacts ?? []);
      setValidation(response.validation);
      setReport(response.report);
      setWarnings(response.warnings ?? []);
      setIrDigest(response.ir_digest);
      const docx = response.artifacts.find((artifact) => artifact.id === response.artifact_id);
      if (docx) {
        triggerDownload(docx.url, docx.filename);
      } else {
        triggerDownload(`/api/v1/artifacts/${encodeURIComponent(response.artifact_id)}`, normalizedName);
      }
      notify("DOCX compiled. Your download should start.", "success");
    } catch (error) {
      const apiError = toApiError(error);
      setScopeError("compile", apiError);
      const failure = extractValidationFailure(apiError);
      if (failure) {
        setValidation(failure.statuses);
        setReport(failure.report);
      }
    } finally {
      setCompilePending(false);
    }
  }, [
    activeVersion,
    compilePending,
    dismissError,
    documentName,
    includeCompatibilityStamp,
    notify,
    renderMode,
    setScopeError,
    source,
    templateId,
    useSampleData,
  ]);

  const downloadCompiledDocx = useCallback(() => {
    if (!compileResult) {
      return;
    }
    const docx = compileResult.artifacts.find(
      (artifact) => artifact.id === compileResult.artifact_id,
    );
    if (docx) {
      downloadArtifact(docx);
      return;
    }
    const fallback: ArtifactView = {
      id: compileResult.artifact_id,
      kind: "docx",
      filename: documentName,
      media_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      size_bytes: 0,
      digest: compileResult.ir_digest,
      url: `/api/v1/artifacts/${encodeURIComponent(compileResult.artifact_id)}`,
      expires_at: 0,
    };
    downloadArtifact(fallback);
  }, [compileResult, documentName, downloadArtifact]);

  /* ------------------------------------------------------------- revision */

  const applyRevision = useCallback(async () => {
    if (revisionPending) {
      return;
    }
    if (!source || !templateId) {
      setScopeError(
        "revise",
        new ApiError("Plan a template before requesting a revision.", {
          code: "client_template_required",
        }),
      );
      return;
    }
    const trimmedInstruction = instruction.trim();
    if (trimmedInstruction.length < 3) {
      setScopeError(
        "revise",
        new ApiError("Describe the change in at least 3 characters.", {
          code: "client_instruction_too_short",
          details: { field: "instruction", length: trimmedInstruction.length },
        }),
      );
      return;
    }
    if (trimmedInstruction.length > INSTRUCTION_MAX_LENGTH) {
      setScopeError(
        "revise",
        new ApiError(`The instruction must be at most ${INSTRUCTION_MAX_LENGTH} characters.`, {
          code: "client_instruction_too_long",
          details: { field: "instruction", max_length: INSTRUCTION_MAX_LENGTH },
        }),
      );
      return;
    }

    setRevisionPending(true);
    dismissError("revise");
    const previousVersion = activeVersion;
    try {
      const body: RevisionRequest = {
        source_id: source.source_id,
        template_id: templateId,
        version: activeVersion,
        instruction: trimmedInstruction,
        provider,
        model: model.trim().length > 0 ? model.trim() : null,
      };
      const response = await postJson<RevisionResponse>("/api/v1/templates/revise", body, {
        timeoutMs: 180_000,
      });
      setRevision(response);
      setTemplateId(response.template_id);
      setActiveVersion(response.version);
      setIr(response.ir);
      setIrDigest(response.ir_digest);
      setMapping(response.mapping);
      setValidation(response.validation);
      setReport(response.report);
      setWarnings(response.warnings ?? []);
      setRemovedBindings([]);
      setArtifacts(response.artifacts ?? []);
      setCompileResult(null);
      setSelectedMappingPath(null);
      setActivePreviewPath(null);
      setMappingFocus(null);
      setInstruction("");
      setPlan((previous) =>
        previous
          ? {
              ...previous,
              version: response.version,
              ir_digest: response.ir_digest,
              ir: response.ir,
              mapping: response.mapping,
              report: response.report,
              validation: response.validation,
            }
          : previous,
      );
      if (previousVersion !== null && previousVersion !== response.version) {
        setCompareVersions({ left: previousVersion, right: response.version });
      } else {
        setCompareVersions(null);
      }
      setCompareOpen(false);
      setComparePreviews({});
      notify(`Revision applied. Version ${response.version} is now active.`, "success");
      void fetchVersions(response.template_id);
      void fetchPreviewFor(response.template_id, response.version);
    } catch (error) {
      const apiError = toApiError(error);
      setScopeError("revise", apiError);
      const failure = extractValidationFailure(apiError);
      if (failure) {
        setValidation(failure.statuses);
        setReport(failure.report);
      }
    } finally {
      setRevisionPending(false);
    }
  }, [
    activeVersion,
    dismissError,
    fetchPreviewFor,
    fetchVersions,
    instruction,
    model,
    notify,
    provider,
    revisionPending,
    setScopeError,
    source,
    templateId,
  ]);

  const loadVersion = useCallback(
    async (version: number) => {
      if (!templateId || loadingVersion !== null) {
        return;
      }
      setLoadingVersion(version);
      dismissError("load-version");
      try {
        const detail = await apiRequest<TemplateVersionDetail>(
          `/api/v1/templates/${encodeURIComponent(templateId)}/export/${version}`,
          {},
          { timeoutMs: 30_000 },
        );
        const statuses = deriveStatuses(detail.validation);
        setActiveVersion(detail.version);
        setIr(detail.ir);
        setIrDigest(detail.ir_digest);
        setMapping(detail.mapping);
        setReport(detail.validation);
        setValidation(statuses);
        setWarnings([]);
        setRemovedBindings([]);
        setCompileResult(null);
        setSelectedMappingPath(null);
        setActivePreviewPath(null);
        setMappingFocus(null);
        setPreviewHtml(null);
        setPreviewVersion(null);
        setPlan((previous) =>
          previous
            ? {
                ...previous,
                version: detail.version,
                ir_digest: detail.ir_digest,
                ir: detail.ir,
                mapping: detail.mapping,
                report: detail.validation,
                validation: statuses,
              }
            : previous,
        );
        notify(`Restored version ${version} into the workspace.`, "success");
        void fetchPreviewFor(templateId, version);
      } catch (error) {
        setScopeError("load-version", toApiError(error));
      } finally {
        setLoadingVersion(null);
      }
    },
    [dismissError, fetchPreviewFor, loadingVersion, notify, setScopeError, templateId],
  );

  const refreshVersions = useCallback(() => {
    if (!templateId) {
      return;
    }
    void fetchVersions(templateId);
  }, [fetchVersions, templateId]);

  /* --------------------------------------------------------------- review */

  const confirmMapping = useCallback(
    async (requirementId: string, selectedFieldPath: string | null, note: string | null) => {
      if (confirmPending || confirmLock.current) {
        return;
      }
      if (!templateId || activeVersion === null) {
        setScopeError(
          "review",
          new ApiError("Plan a template before confirming a mapping.", {
            code: "client_template_required",
          }),
        );
        return;
      }
      confirmLock.current = true;
      setConfirmPending({
        requirementId,
        mode: selectedFieldPath === null ? "confirm" : "selected",
      });
      dismissError("review");
      try {
        const body: ConfirmMappingRequest = {
          selected_field_path: selectedFieldPath,
          note,
        };
        const response = await postJson<ConfirmMappingResponse>(
          `/api/v1/templates/${encodeURIComponent(templateId)}/versions/${activeVersion}/mappings/${encodeURIComponent(requirementId)}/confirm`,
          body,
          { timeoutMs: 120_000 },
        );
        setTemplateId(response.template_id);
        setActiveVersion(response.version);
        setIr(response.ir);
        setIrDigest(response.ir_digest);
        setMapping(response.mapping);
        setReport(response.report);
        setValidation(response.validation);
        setWarnings([]);
        setRemovedBindings([]);
        setCompileResult(null);
        setSelectedMappingPath(null);
        setActivePreviewPath(null);
        setMappingFocus(null);
        setPreviewHtml(null);
        setPreviewVersion(null);
        setPlan((previous) =>
          previous
            ? {
                ...previous,
                version: response.version,
                ir_digest: response.ir_digest,
                ir: response.ir,
                mapping: response.mapping,
                report: response.report,
                validation: response.validation,
              }
            : previous,
        );
        notify(`Review recorded — version ${response.version}`, "success");
        void fetchVersions(response.template_id);
        void fetchPreviewFromIr(response.ir, response.version);
      } catch (error) {
        setScopeError("review", toApiError(error));
      } finally {
        confirmLock.current = false;
        setConfirmPending(null);
      }
    },
    [
      activeVersion,
      confirmPending,
      dismissError,
      fetchPreviewFromIr,
      fetchVersions,
      notify,
      setScopeError,
      templateId,
    ],
  );

  /* -------------------------------------------------------------- compare */

  const loadComparePreview = useCallback(
    async (version: number) => {
      if (!source || !templateId) {
        return;
      }
      setComparePreviews((previous) => ({
        ...previous,
        [version]: {
          html: previous[version]?.html ?? null,
          pending: true,
          error: null,
        },
      }));
      try {
        const html = await apiRequestText(
          "/api/v1/templates/preview",
          {
            method: "POST",
            body: JSON.stringify({
              source_id: source.source_id,
              template_id: templateId,
              version,
            }),
            headers: { "Content-Type": "application/json" },
          },
          { timeoutMs: 60_000 },
        );
        setComparePreviews((previous) => ({
          ...previous,
          [version]: { html, pending: false, error: null },
        }));
      } catch (error) {
        setComparePreviews((previous) => ({
          ...previous,
          [version]: { html: null, pending: false, error: toApiError(error) },
        }));
      }
    },
    [source, templateId],
  );

  const openCompare = useCallback(() => {
    if (!compareVersions || !templateId) {
      return;
    }
    setCompareOpen(true);
    void loadComparePreview(compareVersions.left);
    void loadComparePreview(compareVersions.right);
  }, [compareVersions, loadComparePreview, templateId]);

  const closeCompare = useCallback(() => {
    setCompareOpen(false);
  }, []);

  const toggleCompare = useCallback(() => {
    if (compareOpen) {
      setCompareOpen(false);
      return;
    }
    openCompare();
  }, [compareOpen, openCompare]);

  /* --------------------------------------------------------------- reveal */

  const selectPreviewPath = useCallback((path: string) => {
    setSelectedMappingPath(path);
    mappingFocusToken.current += 1;
    setMappingFocus({ path, token: mappingFocusToken.current });
  }, []);

  /* ----------------------------------------------------------------- demo */

  const loadDemoCases = useCallback(async () => {
    setDemoCasesPending(true);
    dismissError("demo-examples");
    try {
      const list = await apiRequest<DemoCase[]>(
        "/api/v1/demo/examples",
        {},
        { timeoutMs: 15_000 },
      );
      setDemoCases(list);
      setDemoCaseId((current) =>
        list.some((item) => item.id === current)
          ? current
          : (list[0]?.id ?? DEFAULT_DEMO_CASE_ID),
      );
    } catch (error) {
      setScopeError("demo-examples", toApiError(error));
    } finally {
      setDemoCasesPending(false);
    }
  }, [dismissError, setScopeError]);

  useEffect(() => {
    void loadDemoCases();
  }, [loadDemoCases]);

  const runDemo = useCallback(
    async (caseIdValue?: string) => {
      if (demoPending || demoLock.current) {
        return;
      }
      const requested = (caseIdValue ?? demoCaseId).trim() || DEFAULT_DEMO_CASE_ID;
      demoLock.current = true;
      setDemoPending(true);
      dismissError("demo");
      try {
        const body: DemoSessionRequest = { case_id: requested };
        const response = await postJson<DemoSessionResponse>(
          "/api/v1/demo/sessions",
          body,
          { timeoutMs: 180_000 },
        );
        resetTemplateState();
        const sourceSummary: SourceView = {
          source_id: response.source_id,
          filename: `${response.case.id}.ddsp`,
          schema_id: response.schema_id,
          sections: response.sections,
          stats: response.stats,
          // The demo pipeline always renders the packaged sample data.
          sample_data_available: true,
          diagnostics: response.diagnostics,
          // The demo response does not enumerate package entries.
          entry_names: [],
        };
        const demoPlan: PlanResponse = {
          job_id: "",
          status: "completed",
          template_id: response.template_id,
          version: response.version,
          ir_digest: response.ir_digest,
          ir: response.ir,
          mapping: response.mapping,
          report: response.report,
          validation: response.validation,
          warnings: [],
          removed_bindings: [],
          generation: null,
          artifacts: response.artifacts,
        };
        setSource(sourceSummary);
        setSchemaView(null);
        setDemoCaseId(response.case.id);
        setPrompt(response.case.prompt);
        setDocumentName(`${response.case.id}.docx`);
        setInstruction("");
        setPlan(demoPlan);
        setTemplateId(response.template_id);
        setActiveVersion(response.version);
        setIr(response.ir);
        setIrDigest(response.ir_digest);
        setMapping(response.mapping);
        setValidation(response.validation);
        setReport(response.report);
        setWarnings([]);
        setRemovedBindings([]);
        setGeneration(null);
        setArtifacts(response.artifacts);
        setSelectedMappingPath(null);
        setActivePreviewPath(null);
        setMappingFocus(null);
        setPreviewHtml(response.preview_html);
        setPreviewVersion(response.version);
        setPreviewPending(false);
        setTourSteps(response.tour.length > 0 ? response.tour : null);
        notify(`Demo ready in ${response.elapsed_ms} ms`, "success");
        void fetchVersions(response.template_id);
        void loadSchemaFor(response.source_id);
      } catch (error) {
        setScopeError("demo", toApiError(error));
      } finally {
        demoLock.current = false;
        setDemoPending(false);
      }
    },
    [
      demoCaseId,
      demoPending,
      dismissError,
      fetchVersions,
      loadSchemaFor,
      notify,
      resetTemplateState,
      setScopeError,
    ],
  );

  const closeTour = useCallback(() => {
    setTourSteps(null);
  }, []);

  /* -------------------------------------------------------------- preview */

  const refreshPreview = useCallback(async () => {
    if (previewPending) {
      return;
    }
    if (!templateId || activeVersion === null) {
      setScopeError(
        "preview",
        new ApiError("Plan a template before rendering a preview.", {
          code: "client_template_required",
        }),
      );
      return;
    }
    await fetchPreviewFor(templateId, activeVersion);
  }, [activeVersion, fetchPreviewFor, previewPending, setScopeError, templateId]);

  const setSelectedMappingCandidate = useCallback((path: string) => {
    setSelectedMappingPath(path);
  }, []);

  const clearSelectedMappingCandidate = useCallback(() => {
    setSelectedMappingPath(null);
  }, []);

  /* -------------------------------------------------------------- derived */

  const overall = useMemo(
    () => (validation ? overallFromStatuses(validation) : null),
    [validation],
  );

  const maxUploadBytes = capabilities?.limits.max_ddsp_bytes ?? FALLBACK_MAX_UPLOAD_BYTES;

  // The compile endpoint refuses to build a document while any mapping still
  // needs a human decision; surface the same gate in the UI.
  const blockingMappingCount = useMemo(() => {
    if (!mapping) {
      return 0;
    }
    const blockingStatuses = new Set(["needs_review", "conflict", "missing", "invalid"]);
    return mapping.mappings.filter((item) => blockingStatuses.has(item.status)).length;
  }, [mapping]);

  return {
    // system
    providers,
    providersPending,
    capabilities,
    maxUploadBytes,
    reloadProviders: loadProviders,
    providerError: errors.providers ?? null,
    // demo
    demoCases,
    demoCasesPending,
    demoCaseId,
    setDemoCaseId,
    demoPending,
    demoError: errors.demo ?? null,
    demoExamplesError: errors["demo-examples"] ?? null,
    runDemo,
    reloadDemoCases: loadDemoCases,
    tourSteps,
    closeTour,
    // source
    source,
    schemaView,
    diagnostics,
    uploadPending,
    schemaPending,
    uploadError: errors.upload ?? null,
    schemaError: errors.schema ?? null,
    uploadSource,
    reloadSchema,
    // prompt
    prompt,
    setPrompt,
    provider,
    changeProvider,
    selectedProvider,
    model,
    setModel,
    designStyle,
    setDesignStyle,
    language,
    setLanguage,
    strictValidation,
    setStrictValidation,
    maxCost,
    setMaxCost,
    maxRepairAttempts,
    setMaxRepairAttempts,
    planPending,
    planError: errors.plan ?? null,
    planTemplate,
    useExamplePrompt,
    insertPathIntoPrompt,
    // template
    plan,
    templateId,
    activeVersion,
    ir,
    irDigest,
    mapping,
    blockingMappingCount,
    validation,
    overall,
    report,
    warnings,
    removedBindings,
    generation,
    artifacts,
    selectedMappingPath,
    setSelectedMappingCandidate,
    clearSelectedMappingCandidate,
    activePreviewPath,
    setActivePreviewPath,
    selectPreviewPath,
    mappingFocus,
    confirmPending,
    confirmMapping,
    reviewError: errors.review ?? null,
    // compile
    compilePending,
    compileError: errors.compile ?? null,
    compileResult,
    documentName,
    setDocumentName,
    renderMode,
    setRenderMode,
    includeCompatibilityStamp,
    setIncludeCompatibilityStamp,
    useSampleData,
    setUseSampleData,
    compileTemplate,
    downloadArtifact,
    downloadCompiledDocx,
    // revision
    instruction,
    setInstruction,
    revisionPending,
    revisionError: errors.revise ?? null,
    revision,
    applyRevision,
    versions,
    versionsPending,
    versionsError: errors.versions ?? null,
    loadingVersion,
    loadVersion,
    refreshVersions,
    loadVersionError: errors["load-version"] ?? null,
    compareVersions,
    compareOpen,
    comparePreviews,
    openCompare,
    closeCompare,
    toggleCompare,
    // preview
    previewHtml,
    previewVersion,
    previewPending,
    previewError: errors.preview ?? null,
    refreshPreview,
    // ui
    dismissError,
    toast,
    notify,
    dismissToast,
    copyPath,
  };
}

export type WorkspaceController = ReturnType<typeof useWorkspace>;
