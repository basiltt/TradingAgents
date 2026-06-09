import { memo, useMemo, useState } from "react";
import type { TradingAccount } from "../../api/client";
import { type Cohort, computeConcentration } from "./cohortConcentration";

// AI-CONTEXT: Cohort, COHORT_CONCENTRATION_PCT, CohortConcentration, and
// computeConcentration live in ./cohortConcentration so this file exports only the
// component (React Fast Refresh / react-refresh/only-export-components). Re-export
// the Cohort type because FleetCohortPanel imports it from this module; a type-only
// re-export does not trip the rule (it erases at build time).
export type { Cohort };

interface FleetCohortViewProps {
  accounts: TradingAccount[];
  /**
   * Persist a cohort assignment for the given account ids. May return the count of
   * successful assignments; when it returns 0 (total failure) the selection is kept
   * so the user can retry the same set.
   */
  onAssign: (ids: string[], cohort: Cohort) => Promise<number | void> | number | void;
}

/**
 * Fleet roster with multi-select + bulk "apply cohort to selected" (FR-067, TASK-5.3).
 * Surfaces a concentration warning when a cohort dominates the fleet beyond the
 * decorrelation threshold. Selection → preview → confirm; assignment is delegated so
 * the parent owns partial-failure handling and refetch.
 */
export const FleetCohortView = memo(function FleetCohortView({ accounts, onAssign }: FleetCohortViewProps) {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [pendingCohort, setPendingCohort] = useState<Cohort | null>(null);
  const [busy, setBusy] = useState(false);

  const concentration = useMemo(() => computeConcentration(accounts), [accounts]);

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      // AI-CONTEXT: explicit if/else rather than a ternary-as-statement — Set.delete/add
      // are called for their side effect; a ternary expression-statement trips
      // @typescript-eslint/no-unused-expressions and reads as a returned value.
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }

  function selectAll() {
    setSelected(new Set(accounts.map((a) => a.id)));
  }

  function clearSel() {
    setSelected(new Set());
  }

  async function confirmAssign() {
    if (!pendingCohort || selected.size === 0) return;
    setBusy(true);
    try {
      const ok = await onAssign(Array.from(selected), pendingCohort);
      // Keep the selection on total failure (ok === 0) so the user can retry the
      // same set; clear it when the assignment succeeded (or the handler is void).
      if (ok !== 0) {
        clearSel();
        setPendingCohort(null);
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div data-testid="fleet-cohort-view" className="space-y-3">
      {concentration.warn ? (
        <div
          data-testid="concentration-warning"
          role="alert"
          className="text-xs px-3 py-2 rounded-lg border border-amber-500/30 bg-amber-500/[0.07] text-amber-400"
        >
          {Math.round(concentration.fraction * 100)}% of the fleet is in the{" "}
          <span className="font-semibold capitalize">{concentration.dominant?.replace("_", "-")}</span>{" "}
          cohort. Concentrating one strategy re-correlates drawdowns — consider splitting cohorts to decorrelate.
        </div>
      ) : null}

      <div className="flex items-center gap-2 text-xs">
        <button type="button" onClick={selectAll} className="px-2 py-1 rounded border border-border hover:bg-muted/50">Select all</button>
        <button type="button" onClick={clearSel} className="px-2 py-1 rounded border border-border hover:bg-muted/50">Clear</button>
        <span className="text-muted-foreground" data-testid="selected-count">{selected.size} selected</span>
        <span className="ml-auto text-muted-foreground">
          Trend {concentration.trend} · Mean-Rev {concentration.mean_reversion}
        </span>
      </div>

      <ul className="divide-y divide-border/60 rounded-lg border border-border/60">
        {accounts.map((a) => {
          const cohort: Cohort = a.strategy_cohort === "mean_reversion" ? "mean_reversion" : "trend";
          return (
            <li key={a.id} className="flex items-center gap-3 px-3 py-2 text-sm" data-testid="fleet-row">
              <input
                type="checkbox"
                aria-label={`select ${a.label}`}
                checked={selected.has(a.id)}
                onChange={() => toggle(a.id)}
              />
              <span className="flex-1 truncate">{a.label}</span>
              <span className="text-[10px] uppercase tracking-wider text-muted-foreground" data-testid="fleet-row-cohort">
                {cohort === "mean_reversion" ? "Mean-Rev" : "Trend"}
              </span>
            </li>
          );
        })}
      </ul>

      <div className="flex items-center gap-2">
        <select
          aria-label="cohort to apply"
          value={pendingCohort ?? ""}
          onChange={(e) => setPendingCohort((e.target.value || null) as Cohort | null)}
          className="text-sm bg-background border border-border rounded px-2 py-1"
        >
          <option value="">Apply cohort…</option>
          <option value="trend">Trend</option>
          <option value="mean_reversion">Mean-Reversion</option>
        </select>
        <button
          type="button"
          data-testid="apply-cohort"
          disabled={!pendingCohort || selected.size === 0 || busy}
          onClick={confirmAssign}
          className="text-sm px-3 py-1 rounded bg-primary text-primary-foreground disabled:opacity-40"
        >
          {busy ? "Applying…" : `Apply to ${selected.size}`}
        </button>
      </div>
    </div>
  );
});
