/**
 * MCPProposals — the human-approval queue for agent config changes (money path).
 *
 * The agent can only PROPOSE changes to live auto-trade config; a human approves
 * here. Each card shows the field-level diff (old → new), the sweep's robustness
 * verdict and expected uplift, and the expiry. Approve applies atomically on the
 * backend (drift-guarded); reject discards; revert restores a previously-applied
 * proposal. Approve is the only destructive-to-live action, so it confirms.
 */
import { useState } from "react";
import {
  Inbox,
  Check,
  X,
  Undo2,
  Loader2,
  ArrowRight,
  ShieldCheck,
  ShieldAlert,
  Clock,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import type { MCPProposal } from "./types";

export function MCPProposals({
  proposals,
  isLoading,
  isError,
  busyId,
  onApprove,
  onReject,
  onRevert,
  onOpenReview,
}: {
  proposals: MCPProposal[];
  isLoading: boolean;
  isError?: boolean;
  busyId: string | null;
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
  onRevert: (id: string) => void;
  onOpenReview?: (id: string) => void;
}) {
  const [confirmApprove, setConfirmApprove] = useState<MCPProposal | null>(null);

  const pending = proposals.filter((p) => p.status === "pending");
  const others = proposals.filter((p) => p.status !== "pending");

  return (
    <div className="neu-surface-base neu-surface-raised rounded-[var(--neu-radius-lg)] p-5 shadow-[var(--neu-shadow-float)]">
      <div className="flex items-center gap-3">
        <div className="flex size-10 items-center justify-center rounded-[var(--neu-radius-md)] bg-warning/12 text-warning">
          <Inbox className="size-5" />
        </div>
        <div>
          <h3 className="text-base font-bold tracking-tight text-[var(--neu-text-strong)]">
            Config proposals
          </h3>
          <p className="text-xs text-[var(--neu-text-muted)]">
            The agent proposes; you approve. Nothing touches live trading without your sign-off.
          </p>
        </div>
        {pending.length > 0 ? (
          <Badge variant="default" className="ml-auto">
            {pending.length} pending
          </Badge>
        ) : null}
      </div>

      <div className="mt-4 space-y-3">
        {isLoading ? (
          <div className="flex items-center justify-center py-10 text-[var(--neu-text-muted)]">
            <Loader2 className="size-5 animate-spin" />
          </div>
        ) : isError ? (
          <div className="flex flex-col items-center justify-center gap-2 rounded-[var(--neu-radius-md)] border border-dashed border-destructive/30 py-8 text-center">
            <ShieldAlert className="size-6 text-destructive" />
            <p className="text-sm font-medium text-[var(--neu-text-strong)]">Couldn't load proposals</p>
            <p className="max-w-xs text-[11px] text-[var(--neu-text-muted)]">
              The approval queue is temporarily unavailable. It will retry automatically.
            </p>
          </div>
        ) : proposals.length === 0 ? (
          <EmptyState />
        ) : (
          <>
            {pending.map((p) => (
              <ProposalCard
                key={p.id}
                proposal={p}
                busy={busyId === p.id}
                onApprove={() => setConfirmApprove(p)}
                onReject={() => onReject(p.id)}
                onRevert={() => onRevert(p.id)}
                onOpenReview={onOpenReview}
              />
            ))}
            {others.length > 0 ? (
              <details className="mt-2">
                <summary className="cursor-pointer text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--neu-text-muted)]">
                  History ({others.length})
                </summary>
                <div className="mt-2 space-y-2">
                  {others.map((p) => (
                    <ProposalCard
                      key={p.id}
                      proposal={p}
                      busy={busyId === p.id}
                      onApprove={() => undefined}
                      onReject={() => undefined}
                      onRevert={() => onRevert(p.id)}
                    />
                  ))}
                </div>
              </details>
            ) : null}
          </>
        )}
      </div>

      <Dialog open={!!confirmApprove} onOpenChange={(o) => !o && setConfirmApprove(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <ShieldAlert className="size-5 text-warning" />
              Apply this config to live trading?
            </DialogTitle>
            <DialogDescription className="pt-1 text-left">
              This writes the proposed auto-trade configuration to the live schedule. It is
              applied atomically and re-checked against the current config first; if the live
              config has drifted since the proposal, the apply is rejected. You can revert
              afterwards from this list.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setConfirmApprove(null)}>
              Cancel
            </Button>
            <Button
              variant="default"
              onClick={() => {
                if (confirmApprove) onApprove(confirmApprove.id);
                setConfirmApprove(null);
              }}
            >
              Approve & apply
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-[var(--neu-radius-md)] border border-dashed border-[var(--neu-stroke-soft)] py-10 text-center">
      <Inbox className="size-7 text-[var(--neu-text-muted)]" />
      <p className="text-sm font-medium text-[var(--neu-text-strong)]">No proposals</p>
      <p className="max-w-xs text-[11px] text-[var(--neu-text-muted)]">
        When the agent runs an optimization sweep and finds a better config, it will appear
        here for your approval.
      </p>
    </div>
  );
}

const STATUS_VARIANT: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  pending: "default",
  approved: "secondary",
  applied: "secondary",
  rejected: "destructive",
  expired: "outline",
  reverted: "outline",
};

function ProposalCard({
  proposal,
  busy,
  onApprove,
  onReject,
  onRevert,
  onOpenReview,
}: {
  proposal: MCPProposal;
  busy: boolean;
  onApprove: () => void;
  onReject: () => void;
  onRevert: () => void;
  onOpenReview?: (id: string) => void;
}) {
  const isPending = proposal.status === "pending";
  const isApplied = proposal.status === "applied";
  // diff envelope: { before: fullPriorConfig, fields: { name: {from,to} } }.
  // Render the per-field `fields` map; fall back to the raw diff for older rows.
  const diffRaw = (proposal.diff ?? {}) as Record<string, unknown>;
  const diff = (diffRaw.fields && typeof diffRaw.fields === "object"
    ? diffRaw.fields
    : // legacy/no-fields: hide the bare `before` snapshot, show nothing rather
      // than dumping the whole config
      (("before" in diffRaw) ? {} : diffRaw)) as Record<string, unknown>;
  const verdict = (proposal.risk_verdict ?? {}) as Record<string, unknown>;
  const robustness = typeof verdict.robustness === "string" ? verdict.robustness : null;
  const uplift = verdict.uplift as Record<string, unknown> | undefined;

  return (
    <div
      className={cn(
        "rounded-[var(--neu-radius-md)] border bg-[var(--neu-surface-flat)] p-3.5",
        isPending ? "border-warning/30" : "border-[var(--neu-stroke-soft)]",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <Badge variant={STATUS_VARIANT[proposal.status] ?? "secondary"} className="h-5 px-1.5 text-[10px] uppercase">
              {proposal.status}
            </Badge>
            {robustness ? (
              <span
                className={cn(
                  "inline-flex items-center gap-1 text-[10px] font-bold uppercase tracking-[0.12em]",
                  robustness === "robust" ? "text-[var(--neu-accent)]" : "text-warning",
                )}
              >
                {robustness === "robust" ? <ShieldCheck className="size-3" /> : <ShieldAlert className="size-3" />}
                {robustness}
              </span>
            ) : null}
          </div>
          <div className="mt-1 font-mono text-[11px] text-[var(--neu-text-muted)]">
            {proposal.target_schedule_id ? (
              <>schedule {String(proposal.target_schedule_id).slice(0, 8)}… · config #{proposal.target_config_index ?? 0}</>
            ) : (
              <>proposal {proposal.id.slice(0, 8)}…</>
            )}
          </div>
        </div>
        {proposal.expires_at && isPending ? (
          <span className="flex shrink-0 items-center gap-1 text-[10px] text-[var(--neu-text-muted)]">
            <Clock className="size-3" />
            {formatExpiry(proposal.expires_at)}
          </span>
        ) : null}
      </div>

      <DiffTable diff={diff} />

      {uplift ? (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {Object.entries(uplift).map(([k, v]) => (
            <span
              key={k}
              className="rounded-full bg-[var(--neu-surface-inset)] px-2 py-0.5 text-[10px] font-medium text-[var(--neu-text-strong)]"
            >
              {k}: {formatNum(v)}
            </span>
          ))}
        </div>
      ) : null}

      <div className="mt-3 flex items-center gap-2">
        {isPending ? (
          <>
            <Button variant="default" size="sm" onClick={onApprove} disabled={busy}>
              {busy ? <Loader2 className="size-4 animate-spin" /> : <Check className="size-4" />}
              Approve
            </Button>
            <Button variant="outline" size="sm" onClick={onReject} disabled={busy}>
              <X className="size-4" />
              Reject
            </Button>
            {onOpenReview ? (
              <button
                onClick={() => onOpenReview(proposal.id)}
                className="ml-auto text-[11px] font-semibold text-[var(--neu-accent)] hover:underline"
              >
                Full review →
              </button>
            ) : null}
          </>
        ) : isApplied ? (
          <Button variant="outline" size="sm" onClick={onRevert} disabled={busy}>
            {busy ? <Loader2 className="size-4 animate-spin" /> : <Undo2 className="size-4" />}
            Revert
          </Button>
        ) : null}
      </div>
    </div>
  );
}

function DiffTable({ diff }: { diff: Record<string, unknown> }) {
  const entries = Object.entries(diff);
  if (entries.length === 0) {
    return <p className="mt-2 text-[11px] text-[var(--neu-text-muted)]">No field changes recorded.</p>;
  }
  return (
    <div className="mt-2.5 space-y-1">
      {entries.map(([field, change]) => {
        const { from, to } = readChange(change);
        return (
          <div key={field} className="flex items-center gap-2 text-[11px]">
            <span className="w-40 shrink-0 truncate font-mono font-semibold text-[var(--neu-text-strong)]">{field}</span>
            <span className="font-mono text-[var(--neu-text-muted)] line-through">{formatNum(from)}</span>
            <ArrowRight className="size-3 shrink-0 text-[var(--neu-text-muted)]" />
            <span className="font-mono font-semibold text-[var(--neu-accent)]">{formatNum(to)}</span>
          </div>
        );
      })}
    </div>
  );
}

/** Diff entries may be {from,to}, [from,to], or a bare new value. */
function readChange(change: unknown): { from: unknown; to: unknown } {
  if (Array.isArray(change) && change.length === 2) return { from: change[0], to: change[1] };
  if (change && typeof change === "object") {
    const o = change as Record<string, unknown>;
    if ("from" in o || "to" in o) return { from: o.from, to: o.to };
    if ("old" in o || "new" in o) return { from: o.old, to: o.new };
  }
  return { from: "—", to: change };
}

function formatNum(v: unknown): string {
  if (v == null) return "—";
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toFixed(4).replace(/0+$/, "").replace(/\.$/, "");
  if (typeof v === "boolean") return v ? "true" : "false";
  return String(v);
}

function formatExpiry(iso: string): string {
  const ms = new Date(iso).getTime() - Date.now();
  if (Number.isNaN(ms)) return "";
  if (ms <= 0) return "expired";
  const h = Math.floor(ms / 3_600_000);
  if (h >= 1) return `${h}h left`;
  return `${Math.max(1, Math.floor(ms / 60_000))}m left`;
}
