import { useEffect, useState } from "react";
import { useNavigate } from "@tanstack/react-router";
import { ErrorBoundary } from "react-error-boundary";
import { History, RadioTower, Waves, WifiOff } from "lucide-react";
import { useAppSelector, useAppDispatch } from "@/store";
import { setActiveTab } from "@/store/trades-slice";
import { selectActiveTradesList } from "@/components/trades/selectors";
import { fetchAllActiveTrades } from "@/components/trades/hooks/useTradePolling";
import { useTradePolling } from "@/components/trades/hooks/useTradePolling";
import { useTradeFilters } from "@/components/trades/hooks/useTradeFilters";
import { useTradeHistory } from "@/components/trades/hooks/useTradeHistory";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { TradesTable } from "@/components/trades/TradesTable";
import { TradeStats } from "@/components/trades/TradeStats";
import { TradeFilters } from "@/components/trades/TradeFilters";
import { CloseTradeModal } from "@/components/trades/CloseTradeModal";
import { CloseAllConfirmation } from "@/components/trades/CloseAllConfirmation";
import { TradeDetailPanel } from "@/components/trades/TradeDetailPanel";
import { WsDisconnectBanner } from "@/components/trades/WsDisconnectBanner";
import { ACTIVE_STATUSES } from "@/components/trades/types";
import { PageHeader } from "@/components/layout/PageHeader";
import { cn } from "@/lib/utils";

function TableSkeleton() {
  return (
    <div className="grid gap-3">
      {Array.from({ length: 6 }, (_, i) => (
        <Skeleton key={i} className="h-12 rounded-[calc(var(--radius)*1.25)]" />
      ))}
    </div>
  );
}

function TableError({ resetErrorBoundary }: { resetErrorBoundary?: () => void }) {
  return (
    <Card className="border-dashed">
      <CardContent className="flex flex-col items-center justify-center gap-3 p-6 text-center">
        <p className="section-eyebrow">Trade feed</p>
        <h3 className="text-xl font-semibold tracking-tight">Failed to load trades</h3>
        <p className="max-w-xl text-sm text-muted-foreground">
          The trading stream could not be rendered. Retry the table without leaving the current workspace.
        </p>
        {resetErrorBoundary ? (
          <Button variant="outline" size="sm" onClick={resetErrorBoundary}>
            Retry
          </Button>
        ) : null}
      </CardContent>
    </Card>
  );
}

function FullPageError({ resetErrorBoundary }: { resetErrorBoundary?: () => void }) {
  return (
    <Card className="border-dashed">
      <CardContent className="flex min-h-[50vh] flex-col items-center justify-center gap-3 p-6 text-center">
        <p className="section-eyebrow">Execution workspace</p>
        <h2 className="text-xl font-semibold tracking-tight">Something went wrong</h2>
        <p className="max-w-xl text-sm text-muted-foreground">
          The trade desk hit an unexpected error while rendering. Reload the page surface to recover.
        </p>
        {resetErrorBoundary ? (
          <Button variant="outline" onClick={resetErrorBoundary}>
            Reload
          </Button>
        ) : null}
      </CardContent>
    </Card>
  );
}

function ActiveTradesView() {
  const trades = useAppSelector(selectActiveTradesList);
  const filters = useAppSelector((s) => s.trades.filters);
  const [closeAllOpen, setCloseAllOpen] = useState(false);

  const accountId = filters.account_ids?.[0];
  const activeTrades = trades.filter((t) => ACTIVE_STATUSES.includes(t.status));
  const hasActiveTrades = activeTrades.length > 0;
  const accountActiveCount = activeTrades.filter((t) => t.account_id === accountId).length;

  return (
    <div className="space-y-4">
      {hasActiveTrades && accountId ? (
        <div className="flex justify-end">
          <Button
            variant="destructive"
            size="sm"
            className="w-full sm:w-auto"
            onClick={() => setCloseAllOpen(true)}
          >
            Close all ({accountActiveCount})
          </Button>
        </div>
      ) : null}
      <TradesTable trades={activeTrades} />
      <CloseAllConfirmation
        accountId={accountId}
        open={closeAllOpen}
        onClose={() => setCloseAllOpen(false)}
      />
    </div>
  );
}

function HistoryTradesView() {
  const filters = useAppSelector((s) => s.trades.filters);
  const { data, isLoading, error, hasNextPage, fetchNextPage, isFetchingNextPage, refetch } =
    useTradeHistory(filters, true);

  const allTrades = data?.pages.flatMap((p) => p.items) ?? [];

  if (isLoading) return <TableSkeleton />;

  if (error) {
    return (
      <Card className="border-dashed">
        <CardContent className="flex flex-col items-center justify-center gap-3 p-6 text-center">
          <p className="section-eyebrow">History stream</p>
          <h3 className="text-xl font-semibold tracking-tight">Trade history is unavailable</h3>
          <p className="max-w-xl text-sm text-muted-foreground">
            Historical trades could not be loaded for the current filter set.
          </p>
          <Button variant="outline" size="sm" onClick={() => refetch()}>
            Retry
          </Button>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      <TradesTable trades={allTrades} />
      {hasNextPage ? (
        <div className="flex justify-center pt-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => fetchNextPage()}
            disabled={isFetchingNextPage}
          >
            {isFetchingNextPage ? "Loading..." : "Load more"}
          </Button>
        </div>
      ) : null}
    </div>
  );
}

export default function TradesPage() {
  const dispatch = useAppDispatch();
  const navigate = useNavigate();
  const activeTab = useAppSelector((s) => s.trades.activeTab);
  const wsConnected = useAppSelector((s) => s.trades.wsConnected);
  const isFetching = useAppSelector((s) => s.trades.isFetchingActiveTrades);
  const lastUpdated = useAppSelector((s) => s.trades.lastUpdated);
  const accounts = useAppSelector((s) => s.accounts.dashboard);
  const accountsStatus = useAppSelector((s) => s.accounts.status);
  const activeTrades = useAppSelector(selectActiveTradesList);

  useTradePolling(wsConnected);
  useTradeFilters();

  useEffect(() => {
    // AI-CONTEXT: .catch to avoid an unhandled promise rejection if the initial
    // fetch fails (network down / API 500 on first load). Polling + WS recovery will
    // refill state; the error is swallowed here to match the other call sites.
    fetchAllActiveTrades(dispatch).catch(() => {});
  }, [dispatch]);

  const openPositions = activeTrades.filter((trade) =>
    ACTIVE_STATUSES.includes(trade.status),
  ).length;

  if (accounts.length === 0 && accountsStatus !== "idle" && accountsStatus !== "loading") {
    return (
      <Card className="border-dashed">
        <CardContent className="flex min-h-[50vh] flex-col items-center justify-center gap-4 p-6 text-center">
          <p className="section-eyebrow">Execution workspace</p>
          <h2 className="text-xl font-semibold tracking-tight">No accounts connected</h2>
          <p className="max-w-xl text-sm text-muted-foreground">
            Connect a trading account before opening the trade desk so positions, orders, and
            close actions have a live execution target.
          </p>
          <Button variant="outline" onClick={() => navigate({ to: "/accounts" })}>
            Go to accounts
          </Button>
        </CardContent>
      </Card>
    );
  }

  return (
    <ErrorBoundary FallbackComponent={FullPageError}>
      <div className="space-y-3 sm:space-y-5 pb-7">
        {!wsConnected ? <WsDisconnectBanner lastUpdated={lastUpdated} /> : null}

        <PageHeader
          eyebrow="Trades"
          title="Trades"
          description=""
          stats={[
            {
              label: "Open positions",
              value: String(openPositions),
              tone: openPositions > 0 ? "accent" : "neutral",
            },
            {
              label: "Stream",
              value: wsConnected ? "Live" : "Reconnect",
              tone: wsConnected ? "success" : "warning",
            },
            {
              label: "Connected accounts",
              value: String(accounts.length),
              tone: "neutral",
            },
            {
              label: "Visible mode",
              value: activeTab === "active" ? "Active book" : "History",
              tone: "accent",
            },
          ]}
        >
          <div className="flex flex-wrap gap-2">
            <Badge variant="outline">{activeTab === "active" ? "Live book" : "History"}</Badge>
          </div>
        </PageHeader>

        <TradeStats />

        <Tabs
          value={activeTab}
          onValueChange={(tab) => dispatch(setActiveTab(tab as "active" | "history"))}
        >
          <Card className="overflow-visible">
            <CardContent className="space-y-5 p-4 sm:p-5">
              <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
                <h2 className="text-lg font-semibold">Positions</h2>

                <div className="flex flex-wrap items-center gap-3">
                  <span
                    className={cn(
                      "inline-flex items-center gap-2 rounded-full border px-3 py-2 text-[11px] font-semibold uppercase tracking-[0.18em]",
                      wsConnected
                        ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-500"
                        : "border-amber-500/20 bg-amber-500/10 text-amber-500",
                    )}
                  >
                    {wsConnected ? (
                      <RadioTower className="size-3.5" />
                    ) : (
                      <WifiOff className="size-3.5" />
                    )}
                    {wsConnected ? "Live feed" : "Reconnecting"}
                  </span>

                  <TabsList className="min-w-[15rem] sm:w-auto">
                    <TabsTrigger value="active">
                      <Waves className="size-3.5" />
                      Active
                    </TabsTrigger>
                    <TabsTrigger value="history">
                      <History className="size-3.5" />
                      History
                    </TabsTrigger>
                  </TabsList>
                </div>
              </div>

              <TradeFilters />

              <TabsContent value="active" className="mt-0">
                <ErrorBoundary FallbackComponent={TableError}>
                  {isFetching ? <TableSkeleton /> : <ActiveTradesView />}
                </ErrorBoundary>
              </TabsContent>

              <TabsContent value="history" className="mt-0">
                <ErrorBoundary FallbackComponent={TableError}>
                  <HistoryTradesView />
                </ErrorBoundary>
              </TabsContent>
            </CardContent>
          </Card>
        </Tabs>

        <CloseTradeModal />
        <TradeDetailPanel />
      </div>
    </ErrorBoundary>
  );
}
