"use client";

import { FileCheck2, FileType2, ShieldAlert, ShieldCheck } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { ArtifactsPanel } from "@/components/workspace/artifacts-panel";
import { MappingPanel } from "@/components/workspace/mapping-panel";
import { PreviewPanel } from "@/components/workspace/preview-panel";
import { PromptPanel } from "@/components/workspace/prompt-panel";
import { RevisionPanel } from "@/components/workspace/revision-panel";
import { SchemaExplorer } from "@/components/workspace/schema-explorer";
import { SourcePanel } from "@/components/workspace/source-panel";
import { ValidationPanel } from "@/components/workspace/validation-panel";
import { WorkspaceToast } from "@/components/workspace/toast";
import { WorkflowStepper, type WorkflowStep } from "@/components/workflow-stepper";
import { useWorkspace } from "@/hooks/use-workspace";
import { focusElement, scrollToElement } from "@/lib/clipboard";
import { PANEL_IDS } from "@/lib/constants";

export function Workspace() {
  const workspace = useWorkspace();

  const handleInsertPath = (path: string) => {
    const inserted = workspace.insertPathIntoPrompt(path);
    if (inserted) {
      scrollToElement(PANEL_IDS.prompt);
      focusElement("prompt-input");
    }
  };

  const handleCopyPath = (path: string) => {
    void workspace.copyPath(path);
  };

  const steps: WorkflowStep[] = [
    { id: "source", label: "Data source", panelId: PANEL_IDS.source, done: workspace.source !== null },
    { id: "schema", label: "Schema explorer", panelId: PANEL_IDS.schema, done: workspace.schemaView !== null },
    { id: "prompt", label: "Prompt & plan", panelId: PANEL_IDS.prompt, done: workspace.templateId !== null },
    { id: "mapping", label: "Mapping review", panelId: PANEL_IDS.mapping, done: workspace.mapping !== null },
    { id: "validation", label: "Validation", panelId: PANEL_IDS.validation, done: workspace.validation !== null },
    { id: "preview", label: "Preview", panelId: PANEL_IDS.preview, done: workspace.previewHtml !== null },
    { id: "artifacts", label: "Artifacts & DOCX", panelId: PANEL_IDS.artifacts, done: workspace.compileResult !== null },
    { id: "revision", label: "Revision", panelId: PANEL_IDS.revision, done: workspace.revision !== null },
  ];
  const incompleteIndex = steps.findIndex((step) => !step.done);
  const currentStep = incompleteIndex === -1 ? 0 : incompleteIndex + 1;
  const previewArtifact = workspace.artifacts.find((artifact) => artifact.kind === "preview") ?? null;
  const normalizedSchema = workspace.schemaView?.normalized_schema ?? null;

  return (
    <div className="mx-auto w-full max-w-[1440px] px-4 py-6 sm:px-6 lg:px-8">
      <div className="flex flex-col gap-4 border-b border-border pb-6 lg:flex-row lg:items-end lg:justify-between">
        <div className="max-w-3xl">
          <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-primary">
            Schema-aware template engineering
          </p>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight text-foreground sm:text-[28px]">
            Template workspace
          </h1>
          <p className="mt-1.5 text-sm leading-6 text-muted-foreground">
            Upload a DDSP source, plan a template from a natural-language brief, review field
            mappings and five-level validation, preview the HTML rendering, and compile a
            deterministic generic DOCX.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="outline" className="gap-1">
            <FileType2 aria-hidden="true" className="h-3 w-3" />
            Target: generic-docx
          </Badge>
          <Badge variant="outline" className="gap-1">
            <FileCheck2 aria-hidden="true" className="h-3 w-3" />
            Deterministic compile
          </Badge>
          <Badge variant="outline" className="gap-1">
            <ShieldCheck aria-hidden="true" className="h-3 w-3" />
            Sandboxed preview
          </Badge>
          <Badge variant="unverified" className="gap-1">
            <ShieldAlert aria-hidden="true" className="h-3 w-3" />
            AX compatibility not tested
          </Badge>
        </div>
      </div>

      <div className="mt-4">
        <WorkflowStepper steps={steps} currentStep={currentStep} />
      </div>

      <div className="mt-6 space-y-6">
        <SourcePanel
          source={workspace.source}
          diagnostics={workspace.diagnostics}
          uploadPending={workspace.uploadPending}
          schemaPending={workspace.schemaPending}
          uploadError={workspace.uploadError}
          schemaError={workspace.schemaError}
          maxUploadBytes={workspace.maxUploadBytes}
          onUpload={workspace.uploadSource}
          onReloadSchema={workspace.reloadSchema}
          onDismissUploadError={() => workspace.dismissError("upload")}
          onDismissSchemaError={() => workspace.dismissError("schema")}
        />

        <SchemaExplorer
          schemaView={workspace.schemaView}
          hasSource={workspace.source !== null}
          schemaPending={workspace.schemaPending}
          schemaError={workspace.schemaError}
          onReloadSchema={workspace.reloadSchema}
          onDismissSchemaError={() => workspace.dismissError("schema")}
          onCopyPath={handleCopyPath}
          onInsertPath={handleInsertPath}
        />

        <PromptPanel
          source={workspace.source}
          prompt={workspace.prompt}
          onPromptChange={workspace.setPrompt}
          providers={workspace.providers}
          providersPending={workspace.providersPending}
          providerError={workspace.providerError}
          provider={workspace.provider}
          onProviderChange={workspace.changeProvider}
          selectedProvider={workspace.selectedProvider}
          model={workspace.model}
          onModelChange={workspace.setModel}
          designStyle={workspace.designStyle}
          onDesignStyleChange={workspace.setDesignStyle}
          language={workspace.language}
          onLanguageChange={workspace.setLanguage}
          strictValidation={workspace.strictValidation}
          onStrictValidationChange={workspace.setStrictValidation}
          maxCost={workspace.maxCost}
          onMaxCostChange={workspace.setMaxCost}
          maxRepairAttempts={workspace.maxRepairAttempts}
          onMaxRepairAttemptsChange={workspace.setMaxRepairAttempts}
          planPending={workspace.planPending}
          planError={workspace.planError}
          plan={workspace.plan}
          generation={workspace.generation}
          onPlan={workspace.planTemplate}
          onUseExample={workspace.useExamplePrompt}
          onReloadProviders={workspace.reloadProviders}
          onDismissPlanError={() => workspace.dismissError("plan")}
          onDismissProviderError={() => workspace.dismissError("providers")}
        />

        <MappingPanel
          schema={normalizedSchema}
          mapping={workspace.mapping}
          removedBindings={workspace.removedBindings}
          selectedCandidatePath={workspace.selectedMappingPath}
          onSelectCandidate={workspace.setSelectedMappingCandidate}
          onClearCandidate={workspace.clearSelectedMappingCandidate}
          onCopyPath={handleCopyPath}
          onInsertPath={handleInsertPath}
        />

        <ValidationPanel
          validation={workspace.validation}
          overall={workspace.overall}
          report={workspace.report}
          warnings={workspace.warnings}
          templateId={workspace.templateId}
          activeVersion={workspace.activeVersion}
        />

        <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
          <PreviewPanel
            previewHtml={workspace.previewHtml}
            previewVersion={workspace.previewVersion}
            activeVersion={workspace.activeVersion}
            previewPending={workspace.previewPending}
            previewError={workspace.previewError}
            templateId={workspace.templateId}
            previewArtifact={previewArtifact}
            onRefresh={workspace.refreshPreview}
            onDismissError={() => workspace.dismissError("preview")}
          />

          <ArtifactsPanel
            artifacts={workspace.artifacts}
            compileResult={workspace.compileResult}
            compilePending={workspace.compilePending}
            compileError={workspace.compileError}
            templateId={workspace.templateId}
            activeVersion={workspace.activeVersion}
            documentName={workspace.documentName}
            onDocumentNameChange={workspace.setDocumentName}
            renderMode={workspace.renderMode}
            onRenderModeChange={workspace.setRenderMode}
            includeCompatibilityStamp={workspace.includeCompatibilityStamp}
            onIncludeCompatibilityStampChange={workspace.setIncludeCompatibilityStamp}
            useSampleData={workspace.useSampleData}
            onUseSampleDataChange={workspace.setUseSampleData}
            onCompile={workspace.compileTemplate}
            onDownloadDocx={workspace.downloadCompiledDocx}
            onDismissCompileError={() => workspace.dismissError("compile")}
          />
        </div>

        <RevisionPanel
          templateId={workspace.templateId}
          activeVersion={workspace.activeVersion}
          provider={workspace.provider}
          model={workspace.model}
          instruction={workspace.instruction}
          onInstructionChange={workspace.setInstruction}
          revisionPending={workspace.revisionPending}
          revisionError={workspace.revisionError}
          revision={workspace.revision}
          versions={workspace.versions}
          versionsPending={workspace.versionsPending}
          versionsError={workspace.versionsError}
          loadingVersion={workspace.loadingVersion}
          loadVersionError={workspace.loadVersionError}
          onApplyRevision={workspace.applyRevision}
          onRefreshVersions={workspace.refreshVersions}
          onLoadVersion={workspace.loadVersion}
          onDismissRevisionError={() => workspace.dismissError("revise")}
          onDismissVersionsError={() => workspace.dismissError("versions")}
          onDismissLoadVersionError={() => workspace.dismissError("load-version")}
        />
      </div>

      <WorkspaceToast toast={workspace.toast} onDismiss={workspace.dismissToast} />
    </div>
  );
}
