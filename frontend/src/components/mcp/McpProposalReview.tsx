/**
 * McpProposalReview — the full approval screen for a single config proposal
 * (FR-024 / AC-009). Unlike the inline card, this dedicated review requires
 * deliberate human sign-off for any high-risk change:
 *  - a SERVER-computed risk verdict (robustness/uplift from the sweep ranker),
 *  - a segregated "agent-generated, unverified" rationale panel (clearly fenced
 *    so an agent's prose is never mistaken for a system assessment),
 *  - a field-level live→proposed diff with high-risk fields flagged,
 *  - a per-high-risk-field acknowledgment checkbox,
 *  - a typed-confirm ("APPLY") that gates the apply button,
 *  - applied-config version history with one-click revert.
 */
import { useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  Bot,
  Check,
  ShieldCheck,
  ShieldAlert,
  Undo2,
  Loader2,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { HIGH_RISK_FIELDS, robustnessTone } from "./types";
import type { MCPProposal } from "./types";

const TYPED_CONFIRM_WORD = "APPLY";

interface DiffField {
  field: string;
  from: unknown;
  to: unknown;
  highRisk: boolean;
}

export function McpProposalReview({
  proposal,
  busy,
  onApprove,
  onReject,
  onRevert,
  onBack,
}: {
  proposal: MCPProposal;
  busy: boolean;
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
  onRevert: (id: string) => void;
  onBack: () => void;
}) {
  const fields = useMemo(() => extractFields(proposal), [proposal]);
  const highRiskFields = fields.filter((f) => f.highRisk);

  const [acked, setAcked] = useState<Record<string, boolean>>({});
  const [typed, setTyped] = useState("");

  const allAcked = highRiskFields.every((f) => acked[f.field]);
  const typedOk = typed.trim().toUpperCase() === TYPED_CONFIRM_WORD;
  const canApply = proposal.status === "pending" && allAcked && (highRiskFields.length === 0 || typedOk);

  const verdict = (proposal.risk_verdict ?? {}) as Record<string, unknown>;
  const robustness = typeof verdict.robustness === "string" ? verdict.robustness : null;
  const rationale = typeof verdict.rationale === "string" ? verdict.rationale : null;
  const uplift = (verdict.uplift && typeof verdict.uplift === "object" ? verdict.uplift : null) as
    | Record<string, unknown>
    | null;

  return (
    <div className="space-y-5 pb-7">
      <button onClick={onBack} className="text-xs font-medium text-[var(--neu-text-muted)] hover:underline">
        ← Back to console
      </button>

      {/* Header + server verdict */}
      <div className="neu-surface-base neu-surface-raised rounded-[var(--neu-radius-lg)] p-5 shadow-[var(--neu-shadow-float)]">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-bold tracking-tight text-[var(--neu-text-strong)]">
              Review config proposal
            </h2>
            <p className="mt-0.5 font-mono text-[11px] text-[var(--neu-text-muted)]">
              {proposal.target_schedule_id
                ? `schedule ${String(proposal.target_schedule_id).slice(0, 8)}… · config #${proposal.target_config_index ?? 0}`
                : `proposal ${proposal.id.slice(0, 8)}…`}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant={proposal.status === "pending" ? "default" : "secondary"} className="uppercase">
              {proposal.status}
            </Badge>
            {robustness ? (
              <span
                className={cn(
                  "inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[11px] font-bold uppercase tracking-[0.12em]",
                  robustness === "robust"
                    ? "bg-[var(--neu-accent)]/12 text-[var(--neu-accent)]"
                    : robustness === "fragile"
                      ? "bg-destructive/12 text-destructive"
                      : "bg-warning/12 text-warning",
                )}
              >
                {robustnessTone(robustness).good ? <ShieldCheck className="size-3.5" /> : <ShieldAlert className="size-3.5" />}
                Server verdict: {robustness}
              </span>
            ) : null}
          </div>
        </div>
      </div>

      <div className="grid gap-5 lg:grid-cols-[1.3fr_0.7fr]">
        {/* Diff + acknowledgments */}
        <div className="neu-surface-base neu-surface-raised rounded-[var(--neu-radius-lg)] p-5 shadow-[var(--neu-shadow-float)]">
          <h3 className="text-sm font-bold text-[var(--neu-text-strong)]">Live → proposed changes</h3>
          {fields.length === 0 ? (
            <p className="mt-2 text-xs text-[var(--neu-text-muted)]">No field changes recorded.</p>
          ) : (
            <div className="mt-3 space-y-2">
              {fields.map((f) => (
                <div
                  key={f.field}
                  className={cn(
                    "rounded-[var(--neu-radius-md)] border px-3.5 py-2.5",
                    f.highRisk ? "border-destructive/30 bg-destructive/6" : "border-[var(--neu-stroke-soft)]",
                  )}
                >
                  <div className="flex items-center justify-between gap-3">
                    <div className="flex items-center gap-2 text-xs">
                      <code className="font-mono font-semibold text-[var(--neu-text-strong)]">{f.field}</code>
                      {f.highRisk ? (
                        <span className="inline-flex items-center gap-1 rounded-full bg-destructive/12 px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wide text-destructive">
                          <AlertTriangle className="size-2.5" />
                          High risk
                        </span>
                      ) : null}
                    </div>
                    <div className="flex items-center gap-2 font-mono text-xs">
                      <span className="text-[var(--neu-text-muted)] line-through">{fmt(f.from)}</span>
                      <ArrowRight className="size-3 text-[var(--neu-text-muted)]" />
                      <span className="font-semibold text-[var(--neu-accent)]">{fmt(f.to)}</span>
                    </div>
                  </div>
                  {f.highRisk && proposal.status === "pending" ? (
                    <label className="mt-2 flex cursor-pointer items-center gap-2 text-[11px] text-[var(--neu-text-muted)]">
                      <input
                        type="checkbox"
                        checked={!!acked[f.field]}
                        onChange={(e) => setAcked((a) => ({ ...a, [f.field]: e.target.checked }))}
                        className="size-3.5 accent-[var(--neu-accent)]"
                      />
                      I understand the risk of changing <strong>{HIGH_RISK_FIELDS[f.field] ?? f.field}</strong>.
                    </label>
                  ) : null}
                </div>
              ))}
            </div>
          )}

          {/* typed-confirm + actions */}
          {proposal.status === "pending" ? (
            <div className="mt-4 space-y-3 border-t border-[var(--neu-stroke-soft)] pt-4">
              {highRiskFields.length > 0 ? (
                <div>
                  <label className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--neu-text-muted)]">
                    Type <code className="font-mono text-[var(--neu-text-strong)]">{TYPED_CONFIRM_WORD}</code> to confirm
                  </label>
                  <input
                    value={typed}
                    onChange={(e) => setTyped(e.target.value)}
                    placeholder={TYPED_CONFIRM_WORD}
                    className="mt-1 w-40 rounded-[var(--neu-radius-sm)] bg-[var(--neu-surface-inset)] px-2.5 py-1.5 font-mono text-sm text-[var(--neu-text-strong)] neu-focus-ring"
                  />
                </div>
              ) : null}
              <div className="flex items-center gap-2">
                <Button variant="default" size="sm" disabled={!canApply || busy} onClick={() => onApprove(proposal.id)}>
                  {busy ? <Loader2 className="size-4 animate-spin" /> : <Check className="size-4" />}
                  Approve & apply
                </Button>
                <Button variant="outline" size="sm" disabled={busy} onClick={() => onReject(proposal.id)}>
                  Reject
                </Button>
                {!canApply ? (
                  <span className="text-[11px] text-[var(--neu-text-muted)]">
                    {highRiskFields.length > 0 && !allAcked
                      ? "Acknowledge each high-risk field"
                      : highRiskFields.length > 0 && !typedOk
                        ? `Type ${TYPED_CONFIRM_WORD} to enable`
                        : ""}
                  </span>
                ) : null}
              </div>
            </div>
          ) : proposal.status === "applied" ? (
            <div className="mt-4 border-t border-[var(--neu-stroke-soft)] pt-4">
              <Button variant="outline" size="sm" disabled={busy} onClick={() => onRevert(proposal.id)}>
                {busy ? <Loader2 className="size-4 animate-spin" /> : <Undo2 className="size-4" />}
                Revert to prior config
              </Button>
            </div>
          ) : null}
        </div>

        {/* Segregated agent rationale + version history */}
        <div className="space-y-5">
          <div className="rounded-[var(--neu-radius-lg)] border border-dashed border-warning/40 bg-warning/6 p-4">
            <div className="flex items-center gap-2 text-warning">
              <Bot className="size-4" />
              <span className="text-[11px] font-bold uppercase tracking-[0.14em]">
                {rationale ? "Agent-generated · unverified" : "No agent rationale"}
              </span>
            </div>
            <p className="mt-2 text-xs leading-relaxed text-[var(--neu-text-muted)]">
              {rationale ??
                "The agent provided no written rationale. Judge this change on the server-computed verdict and the diff — not on agent prose."}
            </p>
            {uplift && Object.keys(uplift).length > 0 ? (
              <div className="mt-2.5 flex flex-wrap gap-1.5">
                {Object.entries(uplift).map(([k, v]) => (
                  <span key={k} className="rounded-full bg-[var(--neu-surface-inset)] px-2 py-0.5 text-[10px] font-medium text-[var(--neu-text-strong)]">
                    {k}: {fmt(v)}
                  </span>
                ))}
              </div>
            ) : null}
          </div>

          <div className="neu-surface-base neu-surface-raised rounded-[var(--neu-radius-lg)] p-4 shadow-[var(--neu-shadow-float)]">
            <h3 className="text-sm font-bold text-[var(--neu-text-strong)]">Version history</h3>
            <div className="mt-2 space-y-1.5 text-[11px] text-[var(--neu-text-muted)]">
              <HistoryRow label="Proposed" at={proposal.created_at} />
              {proposal.applied_config_version ? (
                <HistoryRow label="Applied" at={proposal.applied_config_version} />
              ) : null}
              <HistoryRow label={`Status: ${proposal.status}`} at={null} />
              {proposal.expires_at ? <HistoryRow label="Expires" at={proposal.expires_at} /> : null}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function HistoryRow({ label, at }: { label: string; at?: string | null }) {
  return (
    <div className="flex items-center justify-between">
      <span>{label}</span>
      {at ? <span className="font-mono">{safeDate(at)}</span> : null}
    </div>
  );
}

/** Extract the per-field diff from the {before, fields} envelope (or legacy). */
function extractFields(proposal: MCPProposal): DiffField[] {
  const diff = (proposal.diff ?? {}) as Record<string, unknown>;
  const raw = (diff.fields && typeof diff.fields === "object" ? diff.fields : {}) as Record<string, unknown>;
  return Object.entries(raw).map(([field, change]) => {
    const c = (change ?? {}) as Record<string, unknown>;
    return {
      field,
      from: "from" in c ? c.from : undefined,
      to: "to" in c ? c.to : undefined,
      highRisk: field in HIGH_RISK_FIELDS,
    };
  });
}

function fmt(v: unknown): string {
  if (v == null) return "—";
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toFixed(4).replace(/0+$/, "").replace(/\.$/, "");
  if (typeof v === "boolean") return v ? "true" : "false";
  return String(v);
}

function safeDate(s: string): string {
  const d = new Date(s);
  return Number.isNaN(d.getTime()) ? s : d.toLocaleString();
}
