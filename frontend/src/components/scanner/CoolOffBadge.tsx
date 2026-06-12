import { useEffect, useRef, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { accountsApi, type CooloffStatus } from "@/api/client";
import type { CooloffReason } from "./cooloffTiers";

const REASON_LABEL: Record<CooloffReason, string> = {
  success: "after a win",
  failure: "after a loss",
  double_success: "after 2 wins",
  double_failure: "after 2 losses",
};

function formatRemaining(seconds: number): string {
  if (seconds <= 0) return "0m";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m`;
  return `${seconds}s`;
}

interface Props {
  accountId: string;
  /** When true, poll faster as a baseline so a newly-armed cool-off surfaces quickly.
   * Polling itself is NOT gated on this — an account already cooling server-side must
   * stay visible even if the user toggles every tier off in the unsaved draft. */
  tiersEnabled: boolean;
}

/**
 * Live "Cooling off" badge for an account. Renders nothing when the account is not
 * cooling. Reason + a client-ticked countdown anchored on the server's
 * cooloff_remaining_seconds; a Resume-now button calls the clear endpoint (FR-022).
 * Rendered ONLY by AutoTradeSection when an account_id is present — never inside
 * CoolOffFields (which the backtest form reuses without an account).
 */
export function CoolOffBadge({ accountId, tiersEnabled }: Props) {
  const queryClient = useQueryClient();
  const { data } = useQuery<CooloffStatus>({
    queryKey: ["account-cooloff", accountId],
    queryFn: () => accountsApi.getCooloffStatus(accountId),
    // Poll whenever we have an account: faster while actively cooling, a touch
    // faster as a baseline when a tier is enabled (so a background-armed cool-off
    // appears), and a slow baseline otherwise so an already-active pause that the
    // user can't see in the draft is never silently dropped.
    refetchInterval: (q) => {
      const s = q.state.data as CooloffStatus | undefined;
      if (s?.cooling) return 15_000;
      return tiersEnabled ? 45_000 : 120_000;
    },
    refetchOnWindowFocus: true,
    enabled: !!accountId,
    staleTime: 10_000,
  });

  // Client-side countdown derived purely from the server's absolute cooloff_until
  // deadline minus a 1 Hz `nowMs` clock. The backend guarantees cooling===true IFF
  // cooloff_until is set (read_status: cooling iff cooloff_until && now < it), so we
  // never need a remaining-seconds fallback. Render stays pure; the clock advances
  // only inside the interval callback (the one place setState is allowed) — no
  // synchronous setState in an effect body, no ref-in-render, no busy-loop at zero.
  const cooling = !!data?.cooling;
  const untilMs = cooling && data?.cooloff_until ? Date.parse(data.cooloff_until) : NaN;
  const deadlineMs = Number.isNaN(untilMs) ? null : untilMs;

  const [nowMs, setNowMs] = useState(() => Date.now());
  useEffect(() => {
    if (!cooling) return;
    const id = setInterval(() => setNowMs(Date.now()), 1000);
    return () => clearInterval(id);
  }, [cooling]);

  // Live deadline math, but clamped to the server's remaining-seconds UPPER BOUND.
  // `nowMs` only advances while cooling; on a not-cooling→cooling transition it can be
  // stale (frozen from before the pause), which would momentarily OVERSTATE the
  // deadline-derived value. The server's cooloff_remaining_seconds (captured at fetch)
  // is a hard ceiling, so min() of the two keeps the display honest until the next
  // 1 Hz tick re-anchors nowMs. Falls back to remaining-seconds if cooloff_until is
  // unparseable (defensive — backend guarantees it when cooling).
  const serverRemaining = cooling
    ? Math.max(0, Math.floor(Number(data!.cooloff_remaining_seconds) || 0))
    : 0;
  const remaining =
    cooling && deadlineMs != null
      ? Math.min(serverRemaining, Math.max(0, Math.round((deadlineMs - nowMs) / 1000)))
      : serverRemaining;

  // When the countdown reaches zero, refetch ONCE to flip the badge to not-cooling.
  // A fresh still-cooling anchor (clock skew) advances the deadline and re-arms.
  const zeroFiredRef = useRef(false);
  useEffect(() => {
    if (!cooling || remaining > 0) {
      zeroFiredRef.current = false;
      return;
    }
    if (!zeroFiredRef.current) {
      zeroFiredRef.current = true;
      queryClient.invalidateQueries({ queryKey: ["account-cooloff", accountId] });
    }
  }, [cooling, remaining, accountId, queryClient]);

  const resume = useMutation({
    mutationFn: () => accountsApi.clearCooloff(accountId, false),
    // Optimistically flip the cached status to not-cooling so the badge clears
    // immediately (and stops ticking) instead of counting down a phantom pause
    // until the refetch lands.
    onMutate: () => {
      queryClient.setQueryData<CooloffStatus>(["account-cooloff", accountId], (prev) =>
        prev
          ? { ...prev, cooling: false, cooloff_until: null, cooloff_remaining_seconds: 0 }
          : prev,
      );
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["account-cooloff", accountId] });
      queryClient.invalidateQueries({ queryKey: ["accounts"] });
    },
  });

  // Render only when we have status saying the account is cooling. We deliberately
  // do NOT gate on the query's isError: a COLD error leaves data undefined →
  // !data?.cooling → null (fail-open, correct). But a WARM refetch error (a transient
  // poll blip after a successful cooling:true) keeps the last-good data while flipping
  // isError true — gating on isError there would silently hide an ACTIVE pause + its
  // Resume-now button for ~15s (violates the never-hide-an-active-cooldown invariant).
  // The countdown is anchored to the absolute cooloff_until, so the retained badge
  // stays honest until the next successful poll.
  if (!data?.cooling) return null;

  const reasonText = data.cooloff_reason ? REASON_LABEL[data.cooloff_reason] ?? data.cooloff_reason : "";
  const untilLabel = data.cooloff_until
    ? new Date(data.cooloff_until).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : "";

  return (
    <div
      className="inline-flex items-center gap-2 rounded-full border border-amber-500/40 bg-amber-500/[0.1] px-3 py-1 text-[11px] text-amber-300"
      role="status"
      aria-live="polite"
      title={untilLabel ? `Resumes ${untilLabel}` : undefined}
    >
      <span aria-hidden>⏸</span>
      {/* Stable, announce-once label for screen readers — excludes the per-second
          countdown so the live region doesn't re-announce every tick. */}
      <span className="sr-only">
        Auto-trading cooling off{reasonText && ` ${reasonText}`}
        {untilLabel && `, resumes ${untilLabel}`}
      </span>
      <span aria-hidden>
        Cooling off {reasonText && `(${reasonText})`} · {formatRemaining(remaining)} left
      </span>
      <button
        type="button"
        onClick={() => {
          if (resume.isPending) return;
          if (window.confirm("Resume auto-trading now for this account? This ends the cool-off early.")) {
            resume.mutate();
          }
        }}
        disabled={resume.isPending}
        className="ml-1 rounded-full border border-amber-500/40 px-2 py-0.5 text-[10px] font-medium hover:bg-amber-500/[0.18] disabled:opacity-50"
      >
        {resume.isPending ? "Resuming…" : "Resume now"}
      </button>
    </div>
  );
}
