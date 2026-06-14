import * as React from "react";

import { cn } from "@/lib/utils";
import type { AutoTradeResult, AutoTradeSummary } from "@/api/client";
import type {
  ScanStep,
  ScanAccountRow,
  ScanOrderRow,
} from "@/hooks/useScanAutoTradeProgressWS";

const SECTION = "neu-surface-base neu-surface-raised rounded-[var(--neu-radius-lg)] border-none shadow-[var(--shadow-card)]";

/** Ordered post-scan pipeline stages. Keys MUST match the backend orchestrator's
 *  emit stages (auto_trade_service.run_post_scan_tail / _TAIL_STAGE_DONE_PCT):
 *  execute_batch -> fill -> post_scan_recheck -> cleanup -> summaries. init_balances
 *  runs pre-tail (no live stage emit) but is shown for shape; a missing stage stays
 *  "pending" which is correct for it.
 *
 *  CONTRACT: the backend's canonical stage keys are pinned by
 *  test_post_scan_orchestrator.py::test_stage_keys_contract and the FE side by
 *  PostScanExecutionPanel.test.tsx — both reference POST_SCAN_STAGE_KEYS so a backend
 *  stage rename/addition that isn't mirrored here fails a test instead of silently
 *  showing a stuck-pending step. Keep the two lists in sync. */
export const POST_SCAN_STAGE_KEYS = [
  "execute_batch",
  "fill",
  "post_scan_recheck",
  "cleanup",
  "summaries",
] as const;

const STAGE_ORDER: { key: string; label: string }[] = [
  { key: "execute_batch", label: "Placing batch orders" },
  { key: "fill", label: "Filling remaining slots" },
  { key: "post_scan_recheck", label: "Re-checking accounts" },
  { key: "cleanup", label: "Cleaning up rules" },
  { key: "summaries", label: "Finalizing summaries" },
];

type StepStatus = "pending" | "active" | "done" | "failed" | "skipped";

function stepStatus(steps: ScanStep[], key: string): StepStatus {
  const s = steps.find((x) => x.stage === key);
  if (!s) return "pending";
  if (s.status === "done") return "done";
  if (s.status === "failed") return "failed";
  if (s.status === "skipped") return "skipped";
  return "active";
}

const STATUS_DOT: Record<StepStatus, string> = {
  pending: "bg-[var(--neu-text-muted)]/40",
  active: "bg-[var(--neu-accent)] animate-pulse",
  done: "bg-[var(--neu-success)]",
  failed: "bg-[var(--neu-danger)]",
  skipped: "bg-[var(--neu-warning)]",
};

function StepRow({ label, status }: { label: string; status: StepStatus }) {
  return (
    <div className="flex items-center gap-3 py-1.5">
      <span className={cn("size-2.5 shrink-0 rounded-full", STATUS_DOT[status])} aria-hidden />
      <span
        className={cn(
          "text-xs font-medium",
          status === "pending" ? "text-[var(--neu-text-muted)]" : "text-[var(--neu-text-strong)]",
        )}
      >
        {label}
      </span>
      <span className="ml-auto text-[10px] font-semibold uppercase tracking-[0.16em] text-[var(--neu-text-muted)]">
        {status}
      </span>
    </div>
  );
}

const SIDE_TONE: Record<string, string> = {
  buy: "text-[var(--neu-success)]",
  sell: "text-[var(--neu-danger)]",
};

function ConnectionBadge({ connected, terminal, done }: { connected: boolean; terminal: boolean; done: boolean }) {
  const [label, dot] = (terminal || done)
    ? ["Done", "bg-[var(--neu-text-muted)]"]
    : connected
      ? ["Live", "bg-[var(--neu-accent)] animate-pulse"]
      : ["Polling", "bg-[var(--neu-warning)]"];
  return (
    <span
      role="status"
      className="inline-flex items-center gap-1.5 rounded-full border border-border/60 bg-background/55 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground"
    >
      <span className={cn("size-2 rounded-full", dot)} aria-hidden />
      {label}
    </span>
  );
}

export interface PostScanExecutionPanelProps {
  /** Live state from useScanAutoTradeProgressWS. */
  steps: ScanStep[];
  accounts: ScanAccountRow[];
  orders: ScanOrderRow[];
  pct: number | null;
  connected: boolean;
  terminal: boolean;
  /** Authoritative "the tail is finished" signal from the 3s poll (status terminal
   *  AND summaries landed). Independent of the WS, so a cold-loaded / WS-down /
   *  finished scan renders the persisted view + a "Done" badge instead of a
   *  permanent all-pending stepper. */
  done: boolean;
  cooloffUntil: number | null;
  /** Authoritative persisted results from the 3s poll (source of truth on terminal). */
  results?: AutoTradeResult[];
  summaries?: AutoTradeSummary[];
  /** Map account id -> human label (for the persisted/terminal view only). */
  accountLabel?: (id: string) => string;
}

/**
 * Live post-scan auto-trade execution panel (Phase 1).
 *
 * While the tail runs, renders the WS-driven stepper + per-account rows + order
 * feed. When the tail is finished (poll-derived `done`) or no live events have
 * arrived (cold-load / WS-down), it renders the authoritative persisted view — so
 * the panel converges correctly whether reached live or cold.
 */
export function PostScanExecutionPanel({
  steps,
  accounts,
  orders,
  pct,
  connected,
  terminal,
  done,
  cooloffUntil,
  results,
  summaries,
  accountLabel,
}: PostScanExecutionPanelProps) {
  const hasLive = steps.length > 0 || accounts.length > 0 || orders.length > 0;
  const persisted = results ?? [];
  // The tail is finished if the poll says so OR a WS terminal arrived.
  const finished = done || terminal;
  // Show the authoritative persisted view once finished (or whenever there's no
  // live stream but persisted results exist). Show the live stepper/feed only
  // while the tail is actively streaming and not yet finished.
  const showPersisted = (finished || !hasLive) && persisted.length > 0;
  const showLive = hasLive && !finished;
  // Stepper only while genuinely streaming — never alongside the persisted grid
  // (which would show a grey all-pending pipeline over real results on a
  // cold-load where the poll returned results before summaries).
  const showStepper = !finished && !showPersisted && (hasLive || (connected && !done));
  // The "no trades placed" message is gated on the POLL-authoritative `done`
  // (not the WS `terminal`), so a scan that DID trade can't briefly flash
  // "No trades placed" in the window between the WS terminal and the refetch.
  const showEmptyFinished = done && !showPersisted && !showLive;

  // Cooloff countdown (a confirmed IP-ban pause, distinct from a micro-throttle).
  const [now, setNow] = React.useState(() => Date.now());
  React.useEffect(() => {
    if (!cooloffUntil || cooloffUntil * 1000 <= Date.now()) return;
    const id = setInterval(() => {
      // Self-stop once the cooloff elapses so we don't re-render every second
      // forever. Commit a final `now` PAST the deadline first, so cooloffSecs
      // resolves to 0 and the banner hides (otherwise it can freeze at "~1m").
      if (!cooloffUntil || cooloffUntil * 1000 <= Date.now()) {
        setNow(Date.now());
        clearInterval(id);
        return;
      }
      setNow(Date.now());
    }, 1000);
    return () => clearInterval(id);
  }, [cooloffUntil]);
  const cooloffSecs = cooloffUntil ? Math.max(0, Math.round(cooloffUntil - now / 1000)) : 0;

  return (
    <div className={cn(SECTION, "space-y-4 p-4")}>
      <div className="flex items-center justify-between gap-3">
        <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[var(--neu-text-muted)]">
          Auto-trade execution
        </p>
        <div className="flex items-center gap-2">
          {typeof pct === "number" && !finished ? (
            <span className="text-[11px] font-mono tabular-nums text-[var(--neu-text-muted)]">{pct}%</span>
          ) : null}
          <ConnectionBadge connected={connected} terminal={terminal} done={done} />
        </div>
      </div>

      {cooloffUntil && cooloffSecs > 0 ? (
        <div className="rounded-[var(--neu-radius-md)] border border-[color-mix(in_oklch,var(--neu-warning)_25%,var(--neu-stroke-soft))] bg-[color-mix(in_oklch,var(--neu-warning)_8%,var(--neu-surface-base))] px-3.5 py-2.5 text-[var(--neu-warning)]">
          <p className="text-xs font-semibold">
            Trading paused ~{Math.ceil(cooloffSecs / 60)}m — rate-limit cooloff
          </p>
          <p className="mt-0.5 text-[11px] opacity-80">
            Respecting Bybit's API limits. Orders are queued, not stuck.
          </p>
        </div>
      ) : null}

      {/* Live stepper — only while actively streaming (hidden once finished). */}
      {showStepper ? (
        <div className="space-y-0.5">
          {STAGE_ORDER.map((s) => (
            <StepRow key={s.key} label={s.label} status={stepStatus(steps, s.key)} />
          ))}
        </div>
      ) : null}

      {/* Per-account live rows (only while streaming). */}
      {showLive && accounts.length > 0 ? (
        <div className="space-y-2 border-t border-[color:var(--neu-stroke-soft)] pt-3">
          {accounts.map((a) => (
            <div
              key={a.acctOrdinal}
              className="flex flex-wrap items-center gap-2 text-xs"
            >
              <span className="font-mono font-semibold text-[var(--neu-text-strong)]">
                acct#{a.acctOrdinal}
              </span>
              {a.dryRun === true ? (
                <span className="rounded-full border border-border/60 px-2 py-0.5 text-[9px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                  dry-run
                </span>
              ) : a.dryRun === false ? (
                <span className="rounded-full border border-[color-mix(in_oklch,var(--neu-success)_30%,var(--neu-stroke-soft))] px-2 py-0.5 text-[9px] font-semibold uppercase tracking-[0.14em] text-[var(--neu-success)]">
                  live
                </span>
              ) : (
                <span className="rounded-full border border-border/40 px-2 py-0.5 text-[9px] font-semibold uppercase tracking-[0.14em] text-muted-foreground/60">
                  —
                </span>
              )}
              <span className="text-[var(--neu-success)]">{a.tradesExecuted}✓</span>
              <span className="text-[var(--neu-danger)]">{a.tradesFailed}✗</span>
              <span className="text-[var(--neu-text-muted)]">{a.tradesSkipped}⏭</span>
              {a.substatus === "rate_wait" ? (
                // DEFERRED (TASK-3.5): the near-ban "rate_wait" substatus is not yet
                // emitted by the backend — the gate instrumentation hook is pending. This
                // per-account micro-throttle pill is wired and ready; until that emit
                // lands the live ban signal is the GLOBAL cooloff banner above. Keep so
                // the UI lights up the moment the backend emits substatus.
                <span className="inline-flex items-center gap-1 rounded-full bg-[color-mix(in_oklch,var(--neu-accent)_10%,transparent)] px-2 py-0.5 text-[9px] font-medium uppercase tracking-[0.12em] text-[var(--neu-accent)]">
                  <span className="size-1.5 animate-pulse rounded-full bg-[var(--neu-accent)]" aria-hidden />
                  rate limit
                </span>
              ) : a.substatus === "ban" ? (
                // DEFERRED (TASK-3.5): the backend currently emits the ban at STAGE level
                // (global cooloff banner), not per-account, so this badge is ready but
                // not yet driven. See the cooloff banner above for the live ban signal.
                <span className="rounded-full bg-[color-mix(in_oklch,var(--neu-warning)_12%,transparent)] px-2 py-0.5 text-[9px] font-semibold uppercase tracking-[0.12em] text-[var(--neu-warning)]">
                  paused
                </span>
              ) : null}
              {a.stoppedReason ? (
                <span className="ml-auto text-[10px] uppercase tracking-[0.12em] text-[var(--neu-warning)]">
                  {a.stoppedReason.replace(/_/g, " ")}
                </span>
              ) : null}
            </div>
          ))}
        </div>
      ) : null}

      {/* Live order feed (newest first, bounded) — only while streaming. */}
      {showLive && orders.length > 0 ? (
        <div className="custom-scrollbar max-h-40 space-y-1.5 overflow-y-auto border-t border-[color:var(--neu-stroke-soft)] pt-3 pr-1">
          {orders.map((o) => (
            <div key={o.seq} className="flex items-center gap-2 text-xs">
              <span className="font-mono font-semibold text-[var(--neu-text-strong)]">{o.symbol}</span>
              {o.side ? <span className={cn("uppercase", SIDE_TONE[o.side])}>{o.side}</span> : null}
              <span className="text-[10px] text-[var(--neu-text-muted)]">acct#{o.acctOrdinal}</span>
              <span className="ml-auto">
                {o.status === "placed" || o.status === "done" ? (
                  <span className="text-[var(--neu-success)]">✓</span>
                ) : o.status === "failed" ? (
                  <span className="text-[var(--neu-danger)]">✗</span>
                ) : o.reasonCode ? (
                  <span className="text-[10px] text-[var(--neu-warning)]">{o.reasonCode.replace(/_/g, " ")}</span>
                ) : null}
              </span>
            </div>
          ))}
        </div>
      ) : null}

      {/* Persisted / terminal view: authoritative results from the poll. */}
      {showPersisted ? (
        <div className="space-y-2">
          <div className="grid grid-cols-2 gap-3">
            <div className={cn(SECTION, "p-3 text-center")}>
              <p className="text-xl font-semibold text-[var(--neu-success)]">
                {persisted.filter((r) => r.status === "success").length}
              </p>
              <p className="mt-1 text-[10px] uppercase tracking-[0.16em] text-muted-foreground">Executed</p>
            </div>
            <div className={cn(SECTION, "p-3 text-center")}>
              <p className="text-xl font-semibold text-[var(--neu-danger)]">
                {persisted.filter((r) => r.status === "failed").length}
              </p>
              <p className="mt-1 text-[10px] uppercase tracking-[0.16em] text-muted-foreground">Failed</p>
            </div>
          </div>
          <div className="custom-scrollbar max-h-40 space-y-1.5 overflow-y-auto pr-1">
            {persisted.map((r, i) => (
              <div key={i} className="flex items-center gap-2 text-xs" title={r.error || undefined}>
                <span className="font-mono font-semibold text-[var(--neu-text-strong)]">{r.symbol}</span>
                {r.side ? <span className={cn("uppercase", SIDE_TONE[r.side])}>{r.side}</span> : null}
                <span className="truncate text-[10px] text-[var(--neu-text-muted)]">
                  {accountLabel ? accountLabel(r.account_id) : r.account_id.slice(0, 8)}
                </span>
                <span className="ml-auto">
                  {r.status === "success" ? (
                    <span className="text-[var(--neu-success)]">✓</span>
                  ) : (
                    <span className="text-[var(--neu-danger)]">✗</span>
                  )}
                </span>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {/* Empty finished state: configured but no trades placed (poll-authoritative). */}
      {showEmptyFinished ? (
        <p className="py-2 text-center text-[11px] text-[var(--neu-text-muted)]">
          No trades placed (see account status for reasons).
        </p>
      ) : null}

      {/* Account-status warnings — rendered from the persisted summaries when
          finished, else from the live rows above. Avoids double-rendering by
          only showing here when NOT in the live phase. */}
      {!showLive && (summaries ?? []).some((s) => s.stopped_reason) ? (
        <div className="space-y-1.5 border-t border-[color:var(--neu-stroke-soft)] pt-3">
          {(summaries ?? [])
            .filter((s) => s.stopped_reason)
            .map((s, i) => (
              <div key={i} className="flex items-center gap-2 text-xs text-[var(--neu-warning)]">
                <span className="font-semibold text-foreground">
                  {accountLabel ? accountLabel(s.account_id) : s.account_id?.slice(0, 8)}
                </span>
                <span className="ml-auto text-[10px] uppercase tracking-[0.12em]">
                  {s.stopped_reason?.replace(/_/g, " ")}
                </span>
              </div>
            ))}
        </div>
      ) : null}
    </div>
  );
}
