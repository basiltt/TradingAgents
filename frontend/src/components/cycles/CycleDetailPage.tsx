import { useState } from "react";
import { Link } from "@tanstack/react-router";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ArrowLeft, ShieldAlert, Sparkles, TriangleAlert } from "lucide-react";
import { cyclesApi, ApiError } from "@/api/client";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { PageHeader } from "@/components/layout/PageHeader";
import { formatDate, isActive } from "./utils";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

const STATUS_VARIANT: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  pending: "outline",
  placing_trades: "default",
  running: "default",
  stopping: "secondary",
  completed: "secondary",
  stopped: "outline",
  failed: "destructive",
};

const TRADE_STATUS_VARIANT: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  pending: "outline",
  submitted: "default",
  filled: "secondary",
  failed: "destructive",
  cancelled: "outline",
};

function StatCard({ label, value, tone = "neutral", helper }: { label: string; value: string; tone?: "accent" | "success" | "warning" | "danger" | "neutral"; helper?: string }) {
  const toneClass = {
    accent: "page-header-stat text-primary",
    success: "page-header-stat text-[var(--success)]",
    warning: "page-header-stat text-[color:color-mix(in_oklch,var(--warning)_76%,var(--foreground))]",
    danger: "page-header-stat text-destructive",
    neutral: "page-header-stat text-foreground",
  }[tone];

  return (
    <div data-tone={tone} className={`surface-lift rounded-[calc(var(--radius)*1.35)] border p-4 ${toneClass}`}>
      <div className="space-y-2 pl-2">
        <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">{label}</p>
        <div className="text-xl font-semibold tracking-[-0.05em] text-foreground sm:text-2xl">{value}</div>
        {helper ? <p className="text-xs leading-5 text-muted-foreground">{helper}</p> : null}
      </div>
    </div>
  );
}

function DetailCell({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[calc(var(--radius)*1.1)] border border-border/55 bg-card/55 p-3.5 shadow-[var(--shadow-soft)]">
      <span className="text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">{label}</span>
      <p className="mt-1 text-sm font-semibold text-foreground">{value}</p>
    </div>
  );
}

export function CycleDetailPage({ cycleId }: { cycleId: string }) {
  const id = Number(cycleId);
  const queryClient = useQueryClient();
  const [confirmStop, setConfirmStop] = useState(false);

  const { data: cycle, isLoading, error, refetch } = useQuery({
    queryKey: ["cycles", id],
    queryFn: ({ signal }) => cyclesApi.get(id, signal),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status && isActive(status) ? 5000 : false;
    },
  });

  const stopMutation = useMutation({
    mutationFn: () => cyclesApi.stop(id),
    onSuccess: () => {
      toast.success("Cycle stop requested");
      queryClient.invalidateQueries({ queryKey: ["cycles"] });
      setConfirmStop(false);
    },
    onError: (err: Error) => {
      toast.error(err instanceof ApiError ? err.detail : err.message);
    },
  });

  if (isLoading) {
    return (
      <div className="space-y-5">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-48 w-full rounded-xl" />
        <Skeleton className="h-64 w-full rounded-xl" />
      </div>
    );
  }

  if (error || !cycle) {
    return (
      <div className="space-y-5">
        <Link to="/cycles" className="inline-flex items-center gap-2 text-sm text-primary hover:underline">
          <ArrowLeft className="size-4" />
          Back to cycles
        </Link>
        <Card>
          <CardContent className="py-6 text-center text-destructive">
            <p>Cycle not found or failed to load.</p>
            <button onClick={() => refetch()} className="mt-2 text-sm text-primary hover:underline">Retry</button>
          </CardContent>
        </Card>
      </div>
    );
  }

  const canStop = isActive(cycle.status) && cycle.status !== "stopping";
  const statusTone = cycle.status === "failed"
    ? "danger"
    : cycle.status === "running"
      ? "success"
      : cycle.status === "stopping"
        ? "warning"
        : cycle.status === "placing_trades"
          ? "accent"
          : "neutral";

  return (
    <div className="space-y-5 pb-8">
      <PageHeader
        eyebrow="Cycles"
        title={`Cycle #${cycle.id}`}
        description=""
        actions={
          <div className="flex flex-wrap gap-2">
            <Link to="/cycles">
              <Button variant="outline">
                <ArrowLeft className="size-4" />
                Back to cycles
              </Button>
            </Link>
            {canStop ? (
              <Button variant="destructive" onClick={() => setConfirmStop(true)}>
                <ShieldAlert className="size-4" />
                Stop Cycle
              </Button>
            ) : null}
          </div>
        }
        stats={[
          { label: "Status", value: cycle.status.replace("_", " "), tone: statusTone },
          { label: "Trades placed", value: String(cycle.trades_placed), tone: cycle.trades_placed > 0 ? "success" : "neutral" },
          { label: "Trades failed", value: String(cycle.trades_failed), tone: cycle.trades_failed > 0 ? "danger" : "neutral" },
          { label: "PnL", value: cycle.final_pnl != null ? `${cycle.final_pnl >= 0 ? "+" : ""}$${cycle.final_pnl.toFixed(2)}` : "Pending", tone: cycle.final_pnl == null ? "neutral" : cycle.final_pnl >= 0 ? "success" : "danger" },
        ]}
      >
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={STATUS_VARIANT[cycle.status] ?? "outline"}>{cycle.status.replace("_", " ")}</Badge>
          {cycle.stop_reason ? <Badge variant="outline">Stop reason recorded</Badge> : null}
        </div>
      </PageHeader>

      <section className="grid gap-4 xl:grid-cols-[1.15fr_0.85fr]">
        <Card>
          <CardContent className="space-y-4 p-5">
            <div className="flex items-start gap-3">
              <span className="gradient-primary inline-flex size-11 items-center justify-center rounded-[calc(var(--radius)*1.1)] text-primary-foreground shadow-[var(--shadow-accent)]">
                <Sparkles className="size-5" />
              </span>
              <div>
                <p className="section-eyebrow">Execution configuration</p>
                <h2 className="mt-1 text-lg font-semibold tracking-[-0.04em] text-foreground">Cycle parameters</h2>
                <p className="mt-1 text-sm leading-6 text-muted-foreground">
                  These values represent the original automation rules used when the cycle was launched.
                </p>
              </div>
            </div>
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              <DetailCell label="Direction" value={cycle.trade_direction} />
              <DetailCell label="Leverage" value={`${cycle.leverage}x`} />
              <DetailCell label="Capital %" value={`${cycle.capital_pct}%`} />
              <DetailCell label="Max trades" value={String(cycle.max_trades)} />
              <DetailCell label="Target" value={cycle.target_type === "percentage" ? `${cycle.target_value}%` : `$${cycle.target_value}`} />
              <DetailCell label="Max drawdown" value={`${cycle.max_drawdown_pct}%`} />
              <DetailCell label="Min score" value={String(cycle.min_score)} />
              <DetailCell label="Min confidence" value={cycle.min_confidence} />
              {cycle.take_profit_pct != null ? <DetailCell label="Take profit" value={`${cycle.take_profit_pct}%`} /> : null}
              {cycle.stop_loss_pct != null ? <DetailCell label="Stop loss" value={`${cycle.stop_loss_pct}%`} /> : null}
            </div>
          </CardContent>
        </Card>

        <div className="space-y-4">
          <StatCard label="Lifecycle" value={formatDate(cycle.created_at)} helper="Cycle creation timestamp" tone="accent" />
          {cycle.started_at ? <StatCard label="Started" value={formatDate(cycle.started_at)} helper="Execution engine began trade routing" tone="success" /> : null}
          {cycle.completed_at ? <StatCard label="Completed" value={formatDate(cycle.completed_at)} helper="Cycle is no longer active" /> : null}
          {cycle.initial_equity != null ? <StatCard label="Initial equity" value={`$${cycle.initial_equity.toFixed(2)}`} helper="Captured at launch" /> : null}
          {cycle.stop_reason ? (
            <div className="surface-lift rounded-[calc(var(--radius)*1.35)] border p-4 text-sm shadow-[var(--shadow-soft)]">
              <div className="flex items-start gap-3">
                <span className="inline-flex size-10 items-center justify-center rounded-full bg-[color:color-mix(in_oklch,var(--warning)_14%,transparent)] text-[color:color-mix(in_oklch,var(--warning)_78%,var(--foreground))]">
                  <TriangleAlert className="size-5" />
                </span>
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">Stop reason</p>
                  <p className="mt-1 leading-6 text-foreground">{cycle.stop_reason}</p>
                </div>
              </div>
            </div>
          ) : null}
        </div>
      </section>

      {cycle.trades && cycle.trades.length > 0 ? (
        <Card>
          <CardContent className="space-y-4 p-5">
            <div className="flex flex-wrap items-end justify-between gap-3">
              <div>
                <p className="section-eyebrow">Trade ledger</p>
                <h2 className="mt-1 text-lg font-semibold tracking-[-0.04em] text-foreground">Trades ({cycle.trades.length})</h2>
                <p className="mt-1 text-sm leading-6 text-muted-foreground">
                  Trade-level submission status, side, quantity, entry price, and broker errors.
                </p>
              </div>
            </div>

            <div className="hidden sm:block overflow-x-auto custom-scrollbar">
              <table className="w-full min-w-[56rem] text-sm" aria-label="Cycle trades">
                <thead>
                  <tr className="border-b border-border/50 bg-muted/18 text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                    <th className="px-3 py-3 text-left">Symbol</th>
                    <th className="px-3 py-3 text-left">Side</th>
                    <th className="px-3 py-3 text-right">Qty</th>
                    <th className="px-3 py-3 text-right">Entry Price</th>
                    <th className="px-3 py-3 text-left">Status</th>
                    <th className="px-3 py-3 text-left">Error</th>
                  </tr>
                </thead>
                <tbody>
                  {cycle.trades.map((t) => (
                    <tr key={t.id} className="border-b border-border/30 transition-colors last:border-b-0 hover:bg-muted/20">
                      <td className="px-3 py-3 font-mono font-semibold text-foreground">{t.symbol}</td>
                      <td className="px-3 py-3">
                        <span className={t.side === "Buy" ? "text-[var(--success)]" : "text-destructive"}>
                          {t.side}
                        </span>
                      </td>
                      <td className="px-3 py-3 text-right font-mono text-foreground">{t.qty ?? "—"}</td>
                      <td className="px-3 py-3 text-right font-mono text-foreground">
                        {t.entry_price != null ? `$${t.entry_price}` : "—"}
                      </td>
                      <td className="px-3 py-3">
                        <Badge variant={TRADE_STATUS_VARIANT[t.status] ?? "outline"}>
                          {t.status}
                        </Badge>
                      </td>
                      <td className="px-3 py-3 text-xs text-muted-foreground">
                        <div className="max-w-64 leading-5 text-destructive/90">{t.error_msg ?? "—"}</div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Mobile Trade List */}
            <div className="grid grid-cols-1 gap-3 sm:hidden">
              {cycle.trades.map((t) => (
                <div
                  key={t.id}
                  className="rounded-[calc(var(--radius)*1.15)] border border-border/40 bg-card p-4 space-y-3"
                >
                  <div className="flex items-center justify-between">
                    <span className="font-mono font-bold text-foreground text-sm">{t.symbol}</span>
                    <Badge variant={TRADE_STATUS_VARIANT[t.status] ?? "outline"}>
                      {t.status}
                    </Badge>
                  </div>
                  <div className="grid grid-cols-3 gap-2 text-xs">
                    <div>
                      <p className="text-muted-foreground/60">Side</p>
                      <p className={`font-semibold mt-0.5 ${t.side === "Buy" ? "text-[var(--success)]" : "text-destructive"}`}>
                        {t.side}
                      </p>
                    </div>
                    <div>
                      <p className="text-muted-foreground/60 font-medium">Qty</p>
                      <p className="font-semibold text-foreground font-mono mt-0.5">{t.qty ?? "—"}</p>
                    </div>
                    <div>
                      <p className="text-muted-foreground/60 font-medium">Entry Price</p>
                      <p className="font-semibold text-foreground font-mono mt-0.5">
                        {t.entry_price != null ? `$${t.entry_price}` : "—"}
                      </p>
                    </div>
                  </div>
                  {t.error_msg && (
                    <div className="border-t border-border/30 pt-2 text-xs text-destructive">
                      <span className="font-semibold">Error:</span> {t.error_msg}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      ) : null}

      <Dialog open={confirmStop} onOpenChange={(open) => {
        if (!stopMutation.isPending) setConfirmStop(open);
      }}>
        <DialogContent showCloseButton={!stopMutation.isPending} className="max-w-sm">
          <DialogHeader>
            <div className="w-10 h-10 rounded-[calc(var(--radius)*1.2)] bg-red-500/10 flex items-center justify-center mb-2">
              <TriangleAlert className="w-5 h-5 text-red-500" />
            </div>
            <DialogTitle>Stop trading cycle?</DialogTitle>
            <DialogDescription>
              This cancels pending trades and closes any positions opened by the cycle. Use only when you intend to exit the batch immediately.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setConfirmStop(false)}
              disabled={stopMutation.isPending}
              className="flex-1 sm:flex-initial"
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={() => stopMutation.mutate()}
              disabled={stopMutation.isPending}
              className="flex-1 sm:flex-initial flex items-center justify-center gap-2"
            >
              {stopMutation.isPending && <div className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />}
              Stop Cycle
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
