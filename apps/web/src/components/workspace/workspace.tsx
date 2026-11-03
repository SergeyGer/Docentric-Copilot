"use client";

import {
  FileCheck2,
  FileType2,
  Loader2,
  ShieldAlert,
  ShieldCheck,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ArtifactsPanel } from "@/components/workspace/artifacts-panel";
import { DemoTour } from "@/components/workspace/demo-tour";
import { ErrorAlert } from "@/components/workspace/error-alert";
import { MappingPanel } from "@/components/workspace/mapping-panel";
import { PreviewPanel } from "@/components/workspace/preview-panel";
import { PromptPanel } from "@/components/workspace/prompt-panel";
import { QualityPanel } from "@/components/workspace/quality-panel";
import { RevisionPanel } from "@/components/workspace/revision-panel";
import { SchemaExplorer } from "@/components/workspace/schema-explorer";
import { SourcePanel } from "@/components/workspace/source-panel";
import { ValidationPanel } from "@/components/workspace/validation-panel";
import { VersionCompareDialog } from "@/components/workspace/version-compare-dialog";
import { WorkspaceToast } from "@/components/workspace/toast";
import { WorkflowStepper, type WorkflowStep } from "@/components/workflow-stepper";
import { useWorkspaceContext } from "@/hooks/workspace-context";
import { focusElement, scrollToElement } from "@/lib/clipboard";
import { PANEL_IDS } from "@/lib/constants";

export function Workspace() {
  const workspace = useWorkspaceContext();

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
    {
      id: "artifacts",
      label: "Artifacts & DOCX",
      panelId: PANEL_IDS.artifacts,
      done: workspace.compileResult !== null || workspace.artifacts.length > 0,
    },
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

      {workspace.demoPending ? (
        <div
          role="status"
          aria-live="polite"
          className="mt-4 flex flex-wrap items-center gap-2 rounded-lg border border-info/30 bg-info/5 px-3 py-2 text-xs text-info"
        >
          <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" />
          Running the demo: parsing the bundled source and building the plan, mapping, validation
          and preview. The guided tour starts automatically.
        </div>
      ) : null}

      {workspace.demoError ? (
        <ErrorAlert
          error={workspace.demoError}
          title="Demo failed"
          className="mt-4"
          onDismiss={() => workspace.dismissError("demo")}
          action={
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => {
                void workspace.runDemo();
              }}
              disabled={workspace.demoPending}
            >
              {workspace.demoPending ? (
                <Loader2 aria-hidden="true" className="animate-spin" />
              ) : null}
              Retry demo
            </Button>
          }
        />
      ) : null}

      {workspace.demoExamplesError ? (
        <ErrorAlert
          error={workspace.demoExamplesError}
          title="Demo examples unavailable"
          className="mt-4"
          onDismiss={() => workspace.dismissError("demo-examples")}
          action={
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => {
                void workspace.reloadDemoCases();
              }}
              disabled={workspace.demoCasesPending}
            >
              {workspace.demoCasesPending ? (
                <Loader2 aria-hidden="true" className="animate-spin" />
              ) : null}
              Retry examples
            </Button>
          }
        />
      ) : null}

      <div
        className={
          workspace.demoPending
            ? "pointer-events-none mt-6 space-y-6 opacity-60"
            : "mt-6 space-y-6"
        }
        aria-busy={workspace.demoPending}
      >
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
          activePreviewPath={workspace.activePreviewPath}
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
          routingMode={workspace.routingMode}
          onRoutingModeChange={workspace.setRoutingMode}
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
          routing={workspace.routing}
          routingPending={workspace.routingPending}
          routingUnavailable={workspace.routingUnavailable}
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
          activePath={workspace.activePreviewPath}
          mappingFocus={workspace.mappingFocus}
          confirming={workspace.confirmPending}
          reviewError={workspace.reviewError}
          onSelectCandidate={workspace.setSelectedMappingCandidate}
          onClearCandidate={workspace.clearSelectedMappingCandidate}
          onCopyPath={handleCopyPath}
          onInsertPath={handleInsertPath}
          onConfirmMapping={workspace.confirmMapping}
          onDismissReviewError={() => workspace.dismissError("review")}
        />

        <Tabs defaultValue="validation">
          <TabsList aria-label="Validation and quality results">
            <TabsTrigger value="validation">Validation</TabsTrigger>
            <TabsTrigger value="quality">Quality</TabsTrigger>
          </TabsList>
          <TabsContent value="validation">
            <ValidationPanel
              validation={workspace.validation}
              overall={workspace.overall}
              report={workspace.report}
              warnings={workspace.warnings}
              templateId={workspace.templateId}
              activeVersion={workspace.activeVersion}
            />
          </TabsContent>
          <TabsContent value="quality">
            <QualityPanel
              quality={workspace.quality}
              qualityPending={workspace.qualityPending}
              qualityError={workspace.qualityError}
              qualityOptimization={workspace.qualityOptimization}
              qualityNotice={workspace.qualityNotice}
              optimizing={workspace.optimizing}
              templateId={workspace.templateId}
              activeVersion={workspace.activeVersion}
              canAnalyse={
                workspace.source !== null &&
                workspace.templateId !== null &&
                workspace.activeVersion !== null
              }
              canOptimize={
                workspace.source !== null &&
                workspace.templateId !== null &&
                workspace.activeVersion !== null &&
                workspace.quality !== null
              }
              onRefresh={workspace.refreshQuality}
              onOptimize={() => {
                void workspace.optimizeLayout();
              }}
              onDismissError={workspace.dismissQualityError}
            />
          </TabsContent>
        </Tabs>

        <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
          <PreviewPanel
            previewHtml={workspace.previewHtml}
            previewVersion={workspace.previewVersion}
            activeVersion={workspace.activeVersion}
            previewPending={workspace.previewPending}
            previewError={workspace.previewError}
            templateId={workspace.templateId}
            previewArtifact={previewArtifact}
            activePath={workspace.activePreviewPath}
            onActivePathChange={workspace.setActivePreviewPath}
            onPathClick={workspace.selectPreviewPath}
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
            blockingMappingCount={workspace.blockingMappingCount}
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
          canCompare={workspace.compareVersions !== null}
          compareOpen={workspace.compareOpen}
          onApplyRevision={workspace.applyRevision}
          onRefreshVersions={workspace.refreshVersions}
          onLoadVersion={workspace.loadVersion}
          onToggleCompare={workspace.toggleCompare}
          onDismissRevisionError={() => workspace.dismissError("revise")}
          onDismissVersionsError={() => workspace.dismissError("versions")}
          onDismissLoadVersionError={() => workspace.dismissError("load-version")}
        />
      </div>

      {workspace.compareVersions ? (
        <VersionCompareDialog
          open={workspace.compareOpen}
          versions={workspace.compareVersions}
          revision={workspace.revision}
          activeVersion={workspace.activeVersion}
          loadingVersion={workspace.loadingVersion}
          previews={workspace.comparePreviews}
          onClose={workspace.closeCompare}
          onRetry={workspace.openCompare}
          onRestore={workspace.loadVersion}
        />
      ) : null}

      {workspace.tourSteps ? (
        <DemoTour steps={workspace.tourSteps} onClose={workspace.closeTour} />
      ) : null}

      <WorkspaceToast toast={workspace.toast} onDismiss={workspace.dismissToast} />
    </div>
  );
}
