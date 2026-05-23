import type { ConnStatus } from "@/hooks/useConnectivityCheck";

function badgeClassName() {
  return "neu-badge-animate inline-flex items-center gap-1.5 rounded-[var(--neu-radius-pill)] px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] ml-auto";
}

export function ConnBadge({
  status,
  latency,
  error,
  label = "Connected",
}: {
  status: ConnStatus;
  latency: number | null;
  error: string | null;
  label?: string;
}) {
  if (status === "idle") return null;

  if (status === "checking") {
    return (
      <span className={`${badgeClassName()} neu-surface-base neu-surface-inset text-[var(--neu-text-muted)]`}>
        <svg className="size-3 neu-spin" fill="none" viewBox="0 0 24 24">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
        Checking
      </span>
    );
  }

  if (status === "ok") {
    return (
      <span className={`${badgeClassName()} neu-surface-base neu-surface-raised text-[var(--neu-success)]`}>
        <svg className="size-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
        </svg>
        {label}
        {latency != null ? ` ${latency}ms` : null}
      </span>
    );
  }

  return (
    <span className={`${badgeClassName()} neu-surface-base neu-surface-raised text-[var(--neu-danger)]`}>
      <svg className="size-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
      </svg>
      {error || "Unreachable"}
    </span>
  );
}
