/**
 * MCPProposalReviewPage — route wrapper for /mcp/proposals/$proposalId.
 * Fetches one proposal and renders the full McpProposalReview approval screen.
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";

import { mcpApi } from "@/api/client";
import { Skeleton } from "@/components/ui/skeleton";
import { mcpErrorMessage, useInvalidateMCP } from "./hooks";
import { McpProposalReview } from "./McpProposalReview";

export function MCPProposalReviewPage({
  proposalId,
  onBack,
}: {
  proposalId: string;
  onBack: () => void;
}) {
  const invalidate = useInvalidateMCP();
  const [busy, setBusy] = useState(false);
  const q = useQuery({
    queryKey: ["mcp", "proposal", proposalId],
    queryFn: ({ signal }) => mcpApi.getProposal(proposalId, signal),
    staleTime: 5_000,
  });

  async function run(fn: () => Promise<unknown>, ok: string) {
    setBusy(true);
    try {
      await fn();
      toast.success(ok);
      invalidate();
      await q.refetch();
    } catch (err) {
      toast.error(mcpErrorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  if (q.isLoading) return <Skeleton className="h-96 rounded-[var(--neu-radius-lg)]" />;
  if (q.isError || !q.data) {
    return (
      <div className="space-y-4 pb-7">
        <button onClick={onBack} className="text-xs font-medium text-[var(--neu-text-muted)] hover:underline">
          ← Back to console
        </button>
        <p className="text-sm text-destructive">{mcpErrorMessage(q.error)}</p>
      </div>
    );
  }

  return (
    <McpProposalReview
      proposal={q.data}
      busy={busy}
      onApprove={(id) => run(() => mcpApi.approveProposal(id), "Proposal applied to live config")}
      onReject={(id) => run(() => mcpApi.rejectProposal(id), "Proposal rejected")}
      onRevert={(id) => run(() => mcpApi.revertProposal(id), "Proposal reverted")}
      onBack={onBack}
    />
  );
}
