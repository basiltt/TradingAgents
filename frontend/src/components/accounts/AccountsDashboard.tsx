/**
 * @module AccountsDashboard
 * @description Top-level accounts overview page. Fetches and polls the account
 * dashboard cards, provides live/demo filtering, multi-column sortable grid, aggregate
 * portfolio stats (equity, today PnL, margin, unrealised PnL), and bulk-action dialogs
 * for master close-all positions and demo balance reset.
 */

import { useState, useCallback, useEffect, useMemo } from "react";
import { accountsApi } from "@/api/client";
import type { DashboardCard } from "@/api/client";
import { useAppDispatch, useAppSelector } from "@/store";
import { setDashboard, setFilterType, setLoading, setError } from "@/store/accounts-slice";
import { useAccountPolling } from "@/hooks/useAccountPolling";
import { AccountCard } from "./AccountCard";
import { AddAccountDialog } from "./AddAccountDialog";
import { KillSwitchDialog } from "./KillSwitchDialog";
import { DemoResetDialog } from "./DemoResetDialog";
import { PageHeader } from "@/components/layout/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ArrowUp, ArrowDown } from "lucide-react";

const SORT_STORAGE_KEY = "tradingagents_accounts_sort";

type SortField = "name" | "equity" | "today_pnl" | "unrealised_pnl" | "positions" | "last_connected" | "status";
type SortDirection = "asc" | "desc";

interface SortConfig {
  field: SortField;
  direction: SortDirection;
}

const SORT_OPTIONS: Array<{ field: SortField; label: string }> = [
  { field: "name", label: "Name" },
  { field: "equity", label: "Equity" },
  { field: "today_pnl", label: "Today PnL" },
  { field: "unrealised_pnl", label: "Unreal. PnL" },
  { field: "positions", label: "Positions" },
  { field: "last_connected", label: "Last Connected" },
  { field: "status", label: "Status" },
];

function loadSortConfig(): SortConfig {
  try {
    const raw = localStorage.getItem(SORT_STORAGE_KEY);
    if (raw) return JSON.parse(raw);
  } catch { /* ignore */ }
  return { field: "name", direction: "asc" };
}

function saveSortConfig(config: SortConfig) {
  localStorage.setItem(SORT_STORAGE_KEY, JSON.stringify(config));
}

function sortAccounts(accounts: DashboardCard[], config: SortConfig): DashboardCard[] {
  const { field, direction } = config;
  const mult = direction === "asc" ? 1 : -1;

  return [...accounts].sort((a, b) => {
    let cmp = 0;
    switch (field) {
      case "name":
        cmp = a.label.localeCompare(b.label);
        break;
      case "equity":
        cmp = parseFloat(a.total_equity || "0") - parseFloat(b.total_equity || "0");
        break;
      case "today_pnl":
        cmp = parseFloat(a.today_pnl || "0") - parseFloat(b.today_pnl || "0");
        break;
      case "unrealised_pnl":
        cmp = parseFloat(a.total_perp_upl || "0") - parseFloat(b.total_perp_upl || "0");
        break;
      case "positions":
        cmp = (a.positions_count || 0) - (b.positions_count || 0);
        break;
      case "last_connected":
        cmp = (a.last_connected_at || "").localeCompare(b.last_connected_at || "");
        break;
      case "status": {
        const order = { active: 0, stale: 1, error: 2, disabled: 3 };
        cmp = (order[a.status] ?? 4) - (order[b.status] ?? 4);
        break;
      }
    }
    return cmp * mult;
  });
}

/**
 * Top-level accounts overview dashboard.
 *
 * Fetches dashboard cards via `accountsApi.getDashboard` and keeps them live through
 * `useAccountPolling`. Renders aggregate portfolio stats (total equity, today PnL,
 * margin usage, unrealised PnL), a sortable/filterable grid of `AccountCard` tiles,
 * and an `AddAccountDialog`. Includes bulk-action drawers for master close-all
 * (live positions across all accounts) and demo-balance reset with real-time SSE
 * progress streaming. Sort state is persisted to `localStorage`.
 *
 * @returns The accounts dashboard page.
 *
 * @example
 * ```tsx
 * // Rendered by the /accounts route
 * <AccountsDashboard />
 * ```
 */
export function AccountsDashboard() {
  const dispatch = useAppDispatch();
  const { dashboard, filterType, status, error } = useAppSelector((s) => s.accounts);
  const [addOpen, setAddOpen] = useState(false);
  const [killOpen, setKillOpen] = useState(false);
  const [resetOpen, setResetOpen] = useState(false);
  const [sortConfig, setSortConfig] = useState<SortConfig>(loadSortConfig);
  useAccountPolling();

  /** Fetch dashboard cards; if silent, skips loading state to avoid UI flicker during polling. */
  const fetchDashboard = useCallback(async (silent = false) => {
    if (!silent) dispatch(setLoading());
    try {
      const cards = await accountsApi.getDashboard();
      dispatch(setDashboard(cards));
    } catch (e: unknown) {
      const msg = (e as { message?: string }).message || "Failed to load accounts";
      if (!silent) dispatch(setError(msg));
      else console.warn("[AccountsDashboard] silent fetch failed:", msg);
    }
  }, [dispatch]);

  useEffect(() => {
    fetchDashboard();
  }, [fetchDashboard]);

  const filtered = useMemo(() => {
    const byType = dashboard.filter((card) => {
      if (filterType === "all") return true;
      return card.account_type === filterType;
    });
    return sortAccounts(byType, sortConfig);
  }, [dashboard, filterType, sortConfig]);

  /** Sum a numeric field across filtered dashboard cards.
   * @param field - Key of DashboardCard to sum.
   * @returns Numeric total of the field across all filtered cards.
   */
  const sumField = (field: keyof typeof filtered[number]) =>
    filtered.reduce((sum, c) => {
      const v = parseFloat(String(c[field] ?? "0"));
      return sum + (isNaN(v) ? 0 : v);
    }, 0);

  const totalEquity = sumField("total_equity");
  const totalPnl = sumField("total_perp_upl");
  const totalTodayPnl = sumField("today_pnl");
  const activeCount = filtered.filter((c) => c.status === "active").length;
  const totalPositions = filtered.reduce((sum, c) => sum + (c.positions_count || 0), 0);
  const allPositionsCount = dashboard.reduce((sum, c) => sum + (c.positions_count || 0), 0);
  const allActiveCount = dashboard.filter((c) => c.status === "active").length;
  const hasDemoAccounts = dashboard.some((c) => c.account_type === "demo");
  const demoAccountIds = dashboard
    .filter((c) => c.account_type === "demo" && c.is_active)
    .map((c) => c.id);

  if (status === "loading" && dashboard.length === 0) {
    return (
      <div className="space-y-5 pb-7">
        <Skeleton className="h-48 rounded-[calc(var(--radius)*2)]" />
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          {Array.from({ length: 4 }).map((_, index) => (
            <Skeleton key={index} className="h-28 rounded-[calc(var(--radius)*1.6)]" />
          ))}
        </div>
        <div className="grid gap-4 xl:grid-cols-2 2xl:grid-cols-3">
          {Array.from({ length: 6 }).map((_, index) => (
            <Skeleton key={index} className="h-72 rounded-[calc(var(--radius)*1.7)]" />
          ))}
        </div>
      </div>
    );
  }

  if (status === "error" && dashboard.length === 0) {
    return (
      <div className="space-y-5 pb-7">
        <PageHeader
          eyebrow="Accounts"
          title="Accounts"
          description={error || ""}
          actions={
            <Button variant="outline" onClick={() => fetchDashboard()}>
              Retry
            </Button>
          }
        />
      </div>
    );
  }

  return (
    <div className="space-y-5 pb-7">
      <PageHeader
        eyebrow="Accounts"
        title="Accounts"
        description=""
        actions={
          <div className="flex flex-wrap gap-2 w-full sm:w-auto sm:justify-end">
            {hasDemoAccounts ? (
              <Button
                variant="outline"
                onClick={() => setResetOpen(true)}
                className="border-amber-500/25 bg-amber-500/10 text-amber-500 hover:bg-amber-500/15 hover:text-amber-500"
              >
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v12m-3-2.818l.879.659c1.171.879 3.07.879 4.242 0 1.172-.879 1.172-2.303 0-3.182C13.536 12.219 12.768 12 12 12c-.725 0-1.45-.22-2.003-.659-1.106-.879-1.106-2.303 0-3.182s2.9-.879 4.006 0l.415.33M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                Reset balance
              </Button>
            ) : null}
            {allPositionsCount > 0 ? (
              <Button
                variant="destructive"
                onClick={() => setKillOpen(true)}
                className="border-red-500/25 bg-red-500/10 text-red-500 hover:bg-red-500/15 hover:text-red-500"
              >
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
                Close all
              </Button>
            ) : null}
            <Button onClick={() => setAddOpen(true)}>
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
              </svg>
              Add account
            </Button>
          </div>
        }
        stats={[
          {
            label: "Equity",
            value: `$${totalEquity.toFixed(2)}`,
            tone: "neutral",
          },
          {
            label: "Today's PnL",
            value: `$${totalTodayPnl.toFixed(2)}`,
            tone: totalTodayPnl >= 0 ? "success" : "danger",
          },
          {
            label: "Unrealised PnL",
            value: `$${totalPnl.toFixed(2)}`,
            tone: totalPnl >= 0 ? "success" : "danger",
          },
          { label: "Open positions", value: String(totalPositions), tone: "neutral" },
        ]}
      >
        <div className="flex flex-wrap gap-2">
          <Badge variant="outline">{dashboard.length} linked accounts</Badge>
          <Badge variant="outline">{activeCount} active in scope</Badge>
          <Badge variant="outline">{allActiveCount} active feeds</Badge>
        </div>
      </PageHeader>

      <Card className="!transform-none !shadow-[var(--neu-shadow-raised)] hover:!shadow-[var(--neu-shadow-raised)]">
        <CardContent className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex flex-wrap items-center gap-2">
            {(["all", "demo", "live"] as const).map((type) => (
              <Button
                key={type}
                variant={filterType === type ? "default" : "outline"}
                size="sm"
                onClick={() => dispatch(setFilterType(type))}
              >
                {type.charAt(0).toUpperCase() + type.slice(1)}
              </Button>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="mr-1 text-xs font-medium text-[var(--neu-text-muted)]">Sort:</span>
            {SORT_OPTIONS.map((opt) => {
              const isActive = sortConfig.field === opt.field;
              return (
                <Button
                  key={opt.field}
                  variant={isActive ? "default" : "ghost"}
                  size="sm"
                  onClick={() => {
                    const next: SortConfig = isActive
                      ? { field: opt.field, direction: sortConfig.direction === "asc" ? "desc" : "asc" }
                      : { field: opt.field, direction: "desc" };
                    setSortConfig(next);
                    saveSortConfig(next);
                  }}
                  className="h-7 gap-1 px-2 text-xs"
                >
                  {opt.label}
                  {isActive && (sortConfig.direction === "asc" ? <ArrowUp className="size-3" /> : <ArrowDown className="size-3" />)}
                </Button>
              );
            })}
          </div>
        </CardContent>
      </Card>

      {/* Empty state */}
      {filtered.length === 0 && status !== "loading" && (
        <Card className="border-dashed">
          <CardContent className="flex flex-col items-center justify-center gap-4 p-6 text-center sm:p-8">
            <div className="gradient-primary flex size-12 items-center justify-center rounded-[calc(var(--radius)*1.45)] text-primary-foreground shadow-[var(--shadow-accent)]">
              <svg className="w-5.5 h-5.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M3 10h18M7 15h1m4 0h1m-7 4h12a3 3 0 003-3V8a3 3 0 00-3-3H6a3 3 0 00-3 3v8a3 3 0 003 3z" />
              </svg>
            </div>
            <div className="space-y-2">
              <p className="section-eyebrow">Ready state</p>
              <h2 className="text-xl font-semibold tracking-tight">
                {dashboard.length ? "No accounts match the current filter" : "No accounts connected"}
              </h2>
              <p className="max-w-xl text-sm text-muted-foreground">
                {dashboard.length
                  ? "Change the dashboard scope to reveal a different cohort of accounts."
                  : "Connect your Bybit trading account to start monitoring equity, exposure, and execution controls in real time."}
              </p>
            </div>
            <Button onClick={() => setAddOpen(true)}>
              Connect account
            </Button>
          </CardContent>
        </Card>
      )}

      {/* Account Cards */}
      {filtered.length > 0 && (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2 2xl:grid-cols-3 neu-stagger">
          {filtered.map((card) => (
            <AccountCard key={card.id} card={card} onRefresh={fetchDashboard} />
          ))}
        </div>
      )}

      <AddAccountDialog open={addOpen} onOpenChange={setAddOpen} onCreated={fetchDashboard} />

      <KillSwitchDialog
        open={killOpen}
        onClose={() => setKillOpen(false)}
        onComplete={() => fetchDashboard(true)}
        allActiveCount={allActiveCount}
        allPositionsCount={allPositionsCount}
      />

      <DemoResetDialog
        open={resetOpen}
        onClose={() => setResetOpen(false)}
        onComplete={() => fetchDashboard(true)}
        dashboard={dashboard}
        initialSelectedIds={demoAccountIds}
      />
    </div>
  );
}
