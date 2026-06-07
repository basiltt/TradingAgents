/**
 * MCPPage — the operator console for the Model Context Protocol server.
 *
 * Composes four sections:
 *  1. Master control (on/off + live status)
 *  2. Tool budget manager (context-window-aware enable/disable)
 *  3. Connection panel (token + client config)
 *  4. Proposal queue (human approval of agent config changes)
 *
 * The console works while the server is OFF — the user configures the token and
 * tool budget first, then enables. A 503 means the MCP module is absent from the
 * build (feature-flagged off); we show a clear, non-alarming notice.
 */
import { useState } from "react";
import { AlertTriangle, Network, RefreshCw, ShieldCheck, Sparkles, Share2 } from "lucide-react";
import { toast } from "sonner";

import { mcpApi, ApiError } from "@/api/client";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  mcpErrorMessage,
  useApplyPreset,
  useInvalidateMCP,
  useMCPConfig,
  useMCPProposals,
  useMCPRegistry,
  useMCPStatus,
  usePatchMCPConfig,
  useToggleMCP,
} from "./hooks";
import { MCPMasterControl } from "./MCPMasterControl";
import { MCPToolBudget } from "./MCPToolBudget";
import { MCPConnectionPanel } from "./MCPConnectionPanel";
import { MCPProposals } from "./MCPProposals";
import { MCPSweepBrowser } from "./MCPSweepBrowser";

export function MCPPage({ onOpenProposal }: { onOpenProposal?: (id: string) => void } = {}) {
  const configQ = useMCPConfig();
  const statusQ = useMCPStatus();
  const registryQ = useMCPRegistry();
  const proposalsQ = useMCPProposals();
  const invalidate = useInvalidateMCP();

  const toggle = useToggleMCP();
  const patch = usePatchMCPConfig();
  const applyPreset = useApplyPreset();

  const [freshToken, setFreshToken] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const [proposalBusyId, setProposalBusyId] = useState<string | null>(null);

  // 503 → MCP module not in this build. Show a dedicated notice (not an error).
  const moduleAbsent =
    (configQ.error instanceof ApiError && configQ.error.status === 503) ||
    (statusQ.error instanceof ApiError && statusQ.error.status === 503);

  // A non-503 config failure must surface as an error (not an infinite skeleton).
  const configFailed = configQ.isError && !moduleAbsent;

  const config = configQ.data;
  const status = statusQ.data;
  const registry = registryQ.data;
  const pending = status?.pending_proposals ?? 0;

  async function handleRegenerate() {
    setGenerating(true);
    try {
      const { token } = await mcpApi.regenerateToken();
      setFreshToken(token);
      toast.success("New token generated — copy it now");
      invalidate();
    } catch (err) {
      toast.error(mcpErrorMessage(err));
    } finally {
      setGenerating(false);
    }
  }

  function handleToggleTool(toolName: string, next: boolean) {
    if (!config) return;
    const enabled_tools = { ...config.enabled_tools, [toolName]: next };
    patch.mutate({ patch: { enabled_tools }, rowVersion: config.row_version });
  }

  async function runProposalAction(id: string, fn: () => Promise<unknown>, okMsg: string) {
    setProposalBusyId(id);
    try {
      await fn();
      toast.success(okMsg);
      invalidate();
    } catch (err) {
      toast.error(mcpErrorMessage(err));
    } finally {
      setProposalBusyId(null);
    }
  }

  return (
    <div className="space-y-5 pb-7">
      <PageHeader
        eyebrow="Integrations"
        title="MCP Server"
        description="Let an external AI agent drive the app — safely, with a context-aware tool budget and human approval for any change to live trading."
        stats={
          status
            ? [
                { label: "State", value: status.state === "running" ? "Running" : "Off", tone: status.state === "running" ? "success" : "neutral" },
                { label: "Active tools", value: String(status.active_tools), tone: "accent" },
                { label: "Pending", value: String(pending), tone: pending ? "warning" : "neutral" },
              ]
            : []
        }
      >
        <div className="flex flex-wrap gap-2">
          <span className="inline-flex items-center gap-2 rounded-full border border-border/60 bg-background/55 px-3 py-1.5 text-[11px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
            <ShieldCheck className="size-3.5 text-success" />
            Default off
          </span>
          <span className="inline-flex items-center gap-2 rounded-full border border-border/60 bg-background/55 px-3 py-1.5 text-[11px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
            <Sparkles className="size-3.5 text-primary" />
            Agent proposes, you approve
          </span>
        </div>
      </PageHeader>

      {moduleAbsent ? (
        <ModuleAbsentNotice />
      ) : configFailed ? (
        <ErrorState message={mcpErrorMessage(configQ.error)} onRetry={() => configQ.refetch()} />
      ) : configQ.isLoading || !config ? (
        <LoadingState />
      ) : (
        <>
          <EgressNotice consentedAt={config.egress_consent_at} />
          <MCPMasterControl
            config={config}
            status={status}
            pending={pending}
            toggling={toggle.isPending}
            onToggle={(next) => toggle.mutate(next)}
          />

          <div className="grid gap-5 xl:grid-cols-[1.25fr_0.75fr]">
            <div className="space-y-5">
              {registry ? (
                <MCPToolBudget
                  registry={registry}
                  busy={patch.isPending || applyPreset.isPending}
                  onToggleTool={handleToggleTool}
                  onApplyPreset={(preset) => applyPreset.mutate({ preset, rowVersion: config.row_version })}
                />
              ) : registryQ.isError ? (
                <ErrorState message={mcpErrorMessage(registryQ.error)} onRetry={() => registryQ.refetch()} />
              ) : (
                <Skeleton className="h-96 rounded-[var(--neu-radius-lg)]" />
              )}

              <MCPProposals
                proposals={proposalsQ.data?.items ?? []}
                isLoading={proposalsQ.isLoading}
                isError={proposalsQ.isError}
                busyId={proposalBusyId}
                onOpenReview={onOpenProposal}
                onApprove={(id) => runProposalAction(id, () => mcpApi.approveProposal(id), "Proposal applied to live config")}
                onReject={(id) => runProposalAction(id, () => mcpApi.rejectProposal(id), "Proposal rejected")}
                onRevert={(id) => runProposalAction(id, () => mcpApi.revertProposal(id), "Proposal reverted")}
              />

              <MCPSweepBrowser />
            </div>

            <MCPConnectionPanel
              config={config}
              generating={generating}
              freshToken={freshToken}
              onRegenerate={handleRegenerate}
              onDismissToken={() => setFreshToken(null)}
            />
          </div>
        </>
      )}
    </div>
  );
}

function LoadingState() {
  return (
    <div className="space-y-5">
      <Skeleton className="h-28 rounded-[var(--neu-radius-lg)]" />
      <div className="grid gap-5 xl:grid-cols-[1.25fr_0.75fr]">
        <Skeleton className="h-96 rounded-[var(--neu-radius-lg)]" />
        <Skeleton className="h-80 rounded-[var(--neu-radius-lg)]" />
      </div>
    </div>
  );
}

function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="neu-surface-base neu-surface-raised flex flex-col items-center justify-center gap-3 rounded-[var(--neu-radius-lg)] py-16 text-center shadow-[var(--neu-shadow-float)]">
      <div className="flex size-12 items-center justify-center rounded-[var(--neu-radius-md)] bg-destructive/12 text-destructive">
        <AlertTriangle className="size-6" />
      </div>
      <h2 className="text-lg font-bold text-[var(--neu-text-strong)]">Couldn't load the MCP console</h2>
      <p className="max-w-md text-sm text-[var(--neu-text-muted)]">{message}</p>
      <Button variant="outline" size="sm" onClick={onRetry} className="mt-1">
        <RefreshCw className="size-4" />
        Retry
      </Button>
    </div>
  );
}

function EgressNotice({ consentedAt }: { consentedAt?: string | null }) {
  return (
    <div className="flex items-start gap-3 rounded-[var(--neu-radius-md)] border border-warning/25 bg-warning/8 px-4 py-3">
      <Share2 className="mt-0.5 size-4 shrink-0 text-warning" />
      <div className="text-xs leading-relaxed text-[var(--neu-text-muted)]">
        <span className="font-semibold text-[var(--neu-text-strong)]">Data egress notice. </span>
        When the server is on, the tools you enable send their results to the connected AI
        model provider. Enable only what you're comfortable sharing; money figures are
        redacted to ratios by default.
        {consentedAt ? (
          <span className="ml-1 opacity-80">Consent recorded {new Date(consentedAt).toLocaleDateString()}.</span>
        ) : null}
      </div>
    </div>
  );
}

function ModuleAbsentNotice() {
  return (
    <div className="neu-surface-base neu-surface-raised flex flex-col items-center justify-center gap-3 rounded-[var(--neu-radius-lg)] py-16 text-center shadow-[var(--neu-shadow-float)]">
      <div className="flex size-12 items-center justify-center rounded-[var(--neu-radius-md)] bg-[var(--neu-surface-inset)] text-[var(--neu-text-muted)]">
        <Network className="size-6" />
      </div>
      <h2 className="text-lg font-bold text-[var(--neu-text-strong)]">MCP module not available</h2>
      <p className="max-w-md text-sm text-[var(--neu-text-muted)]">
        The Model Context Protocol integration is not enabled in this build. It is an optional,
        default-off module; enable it in the backend configuration to use this console.
      </p>
      <span className="mt-1 inline-flex items-center gap-1.5 text-[11px] font-medium text-[var(--neu-text-muted)]">
        <AlertTriangle className="size-3.5" />
        Endpoint /api/v1/mcp/* returned 503
      </span>
    </div>
  );
}
