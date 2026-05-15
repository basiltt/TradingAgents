import { useEffect, useState } from "react";
import { ErrorBoundary } from "react-error-boundary";
import { useAppSelector, useAppDispatch } from "@/store";
import { setActiveTab } from "@/store/trades-slice";
import { selectActiveTradesList } from "@/components/trades/selectors";
import { fetchAllActiveTrades } from "@/components/trades/hooks/useTradePolling";
import { useTradePolling } from "@/components/trades/hooks/useTradePolling";
import { useTradeFilters } from "@/components/trades/hooks/useTradeFilters";
import { useTradeHistory } from "@/components/trades/hooks/useTradeHistory";
import { useMediaQuery } from "@/hooks/useMediaQuery";
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
    <div className="space-y-2">
      {Array.from({ length: 5 }, (_, i) => (
        <Skeleton key={i} className="h-12 w-full" />
      ))}
    </div>
  );
}

function TableError({ resetErrorBoundary }: { resetErrorBoundary?: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-muted-foreground">
      <p className="text-lg font-medium">Something went wrong loading trades.</p>
      {resetErrorBoundary && (
        <Button variant="outline" size="sm" className="mt-3" onClick={resetErrorBoundary}>
          Retry
        </Button>
      )}
    </div>
  );
}

function FullPageError({ resetErrorBoundary }: { resetErrorBoundary?: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center h-[60vh] text-muted-foreground">
      <p className="text-xl font-medium">Something went wrong.</p>
      {resetErrorBoundary && (
        <Button variant="outline" className="mt-4" onClick={resetErrorBoundary}>
          Reload page
        </Button>
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

  return (
    <div className="space-y-3">
      {hasActiveTrades && accountId && (
        <div className="flex justify-end">
          <Button
            variant="destructive"
            size="sm"
            onClick={() => setCloseAllOpen(true)}
          >
            Close All ({activeTrades.filter((t) => t.account_id === accountId).length})
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
        <p>Failed to load trade history.</p>
        <Button variant="outline" size="sm" className="mt-3" onClick={() => refetch()}>
          Retry
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <TradesTable trades={allTrades} />
      {hasNextPage && (
        <div className="flex justify-center pt-2">
          <Button variant="outline" size="sm" onClick={() => fetchNextPage()} disabled={isFetchingNextPage}>
            {isFetchingNextPage ? "Loading..." : "Load More"}
          </Button>
        </div>
      )}
    </div>
  );
}

export default function TradesPage() {
  const dispatch = useAppDispatch();
  const activeTab = useAppSelector((s) => s.trades.activeTab);
  const wsConnected = useAppSelector((s) => s.trades.wsConnected);
  const isFetching = useAppSelector((s) => s.trades.isFetchingActiveTrades);
  const lastUpdated = useAppSelector((s) => s.trades.lastUpdated);
  const accounts = useAppSelector((s) => s.accounts.dashboard);
  const accountsStatus = useAppSelector((s) => s.accounts.status);
  const isMobile = useMediaQuery("(max-width: 767px)");

  useTradePolling(wsConnected);
  useTradeFilters();

  useEffect(() => {
    fetchAllActiveTrades(dispatch);
  }, [dispatch]);

  if (isMobile) {
    return (
      <div className="p-4 text-center text-gray-400">
        <p className="text-lg font-medium">Trades dashboard is optimized for desktop.</p>
        <p className="text-sm mt-2">Please use a wider screen for the full experience.</p>
      </div>
    );
  }

  if (accounts.length === 0 && accountsStatus !== "idle" && accountsStatus !== "loading") {
    return (
      <div className="flex flex-col items-center justify-center h-[60vh] text-muted-foreground">
        <p className="text-lg font-medium">No accounts connected</p>
        <p className="text-sm mt-2">Add a trading account to start viewing trades.</p>
        <Button variant="outline" className="mt-4" onClick={() => window.location.href = "/accounts"}>
          Go to Accounts
        </Button>
      </div>
    );
  }

  return (
    <ErrorBoundary FallbackComponent={FullPageError}>
      <div className="space-y-6">
        {!wsConnected && <WsDisconnectBanner lastUpdated={lastUpdated} />}
        <TradeStats />
        <Tabs value={activeTab} onValueChange={(tab) => dispatch(setActiveTab(tab as "active" | "history"))}>
          <TabsList>
            <TabsTrigger value="active">Active Trades</TabsTrigger>
            <TabsTrigger value="history">Trade History</TabsTrigger>
          </TabsList>
          <TradeFilters />
          <TabsContent value="active">
            <ErrorBoundary FallbackComponent={TableError}>
              {isFetching ? <TableSkeleton /> : <ActiveTradesView />}
            </ErrorBoundary>
          </TabsContent>
          <TabsContent value="history">
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
