import { useEffect, useState } from "react";
import { useNavigate } from "@tanstack/react-router";
import { ErrorBoundary } from "react-error-boundary";
import { useAppSelector, useAppDispatch } from "@/store";
import { setActiveTab } from "@/store/trades-slice";
import { selectActiveTradesList } from "@/components/trades/selectors";
import { fetchAllActiveTrades } from "@/components/trades/hooks/useTradePolling";
import { useTradePolling } from "@/components/trades/hooks/useTradePolling";
import { useTradeFilters } from "@/components/trades/hooks/useTradeFilters";
import { useTradeHistory } from "@/components/trades/hooks/useTradeHistory";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { TradesTable } from "@/components/trades/TradesTable";
import { TradeStats } from "@/components/trades/TradeStats";
import { TradeFilters } from "@/components/trades/TradeFilters";
import { CloseTradeModal } from "@/components/trades/CloseTradeModal";
import { CloseAllConfirmation } from "@/components/trades/CloseAllConfirmation";
import { TradeDetailPanel } from "@/components/trades/TradeDetailPanel";
import { WsDisconnectBanner } from "@/components/trades/WsDisconnectBanner";
import { ACTIVE_STATUSES } from "@/components/trades/types";

function TableSkeleton() {
  return (
    <div className="space-y-1">
      {Array.from({ length: 6 }, (_, i) => (
        <Skeleton key={i} className="h-10 w-full rounded" />
      ))}
    </div>
  );
}

function TableError({ resetErrorBoundary }: { resetErrorBoundary?: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-muted-foreground">
      <p className="text-sm font-medium">Failed to load trades</p>
      {resetErrorBoundary && (
        <Button variant="outline" size="sm" className="mt-3 text-xs" onClick={resetErrorBoundary}>Retry</Button>
      )}
    </div>
  );
}

function FullPageError({ resetErrorBoundary }: { resetErrorBoundary?: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center h-[60vh] text-muted-foreground">
      <p className="text-base font-medium">Something went wrong</p>
      {resetErrorBoundary && (
        <Button variant="outline" className="mt-4 text-xs" onClick={resetErrorBoundary}>Reload</Button>
      )}
    </div>
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
    <div className="space-y-2">
      {hasActiveTrades && accountId && (
        <div className="flex justify-end">
          <Button
            variant="ghost"
            size="sm"
            className="h-7 text-[10px] font-bold uppercase tracking-wider text-destructive hover:bg-destructive/10 rounded-xl cursor-pointer"
            onClick={() => setCloseAllOpen(true)}
          >
            Close All ({accountActiveCount})
          </Button>
        </div>
      )}
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
  const { data, isLoading, error, hasNextPage, fetchNextPage, isFetchingNextPage, refetch } = useTradeHistory(filters, true);

  const allTrades = data?.pages.flatMap((p) => p.items) ?? [];

  if (isLoading) return <TableSkeleton />;

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-sm text-muted-foreground">
        <p className="text-xs font-semibold uppercase tracking-wider">Failed to load trade history.</p>
        <Button variant="outline" size="sm" className="mt-3 text-xs rounded-xl cursor-pointer" onClick={() => refetch()}>Retry</Button>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <TradesTable trades={allTrades} />
      {hasNextPage && (
        <div className="flex justify-center pt-2">
          <Button variant="ghost" size="sm" className="text-xs text-muted-foreground rounded-xl cursor-pointer" onClick={() => fetchNextPage()} disabled={isFetchingNextPage}>
            {isFetchingNextPage ? "Loading..." : "Load more"}
          </Button>
        </div>
      )}
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


  useTradePolling(wsConnected);
  useTradeFilters();

  useEffect(() => {
    fetchAllActiveTrades(dispatch);
  }, [dispatch]);

  // Mobile is now supported - no blocking gate

  if (accounts.length === 0 && accountsStatus !== "idle" && accountsStatus !== "loading") {
    return (
      <div className="flex flex-col items-center justify-center h-[60vh] text-muted-foreground">
        <p className="text-sm font-medium">No accounts connected</p>
        <p className="text-xs mt-1.5">Connect a trading account to get started.</p>
        <Button variant="outline" size="sm" className="mt-4 text-xs rounded-xl cursor-pointer" onClick={() => navigate({ to: "/accounts" })}>
          Go to Accounts
        </Button>
      </div>
    );
  }

  return (
    <ErrorBoundary FallbackComponent={FullPageError}>
      <div className="space-y-6 max-w-5xl mx-auto py-4 px-4 md:px-6">
        {!wsConnected && <WsDisconnectBanner lastUpdated={lastUpdated} />}

        {/* Header */}
        <div className="flex items-center justify-between border-b border-border/20 pb-3">
          <div>
            <h1 className="text-xl font-black tracking-tight flex items-center gap-2">
              <svg className="w-5.5 h-5.5 text-primary shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 002 2h2a2 2 0 002-2z" />
              </svg>
              Positions &amp; Orders
            </h1>
            <p className="text-[10px] text-muted-foreground mt-0.5 font-bold uppercase tracking-wider">
              Monitor and manage trade executions
            </p>
          </div>
          <div className="flex items-center gap-2">
            {wsConnected && (
              <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/20">
                <div className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                <span className="text-[9px] font-black uppercase tracking-wider text-emerald-400">Live</span>
              </div>
            )}
          </div>
        </div>

        <TradeStats />

        <Tabs value={activeTab} onValueChange={(tab) => dispatch(setActiveTab(tab as "active" | "history"))}>
          <div className="flex items-center justify-between border-b border-border/30 pb-0">
            <TabsList className="bg-transparent p-0 h-auto gap-0">
              <TabsTrigger
                value="active"
                className="text-[10px] font-bold uppercase tracking-wider px-3 py-2 rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:text-foreground text-muted-foreground/70 data-[state=active]:shadow-none cursor-pointer"
              >
                Active
              </TabsTrigger>
              <TabsTrigger
                value="history"
                className="text-[10px] font-bold uppercase tracking-wider px-3 py-2 rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:text-foreground text-muted-foreground/70 data-[state=active]:shadow-none cursor-pointer"
              >
                History
              </TabsTrigger>
            </TabsList>
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
        </Tabs>
        <CloseTradeModal />
        <TradeDetailPanel />
      </div>
    </ErrorBoundary>
  );
}
