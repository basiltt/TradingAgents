/* eslint-disable react-refresh/only-export-components */
import { Suspense, lazy, type ReactNode } from "react";
import {
  createRootRoute,
  createRoute,
  createRouter,
  useParams,
  useNavigate,
  useSearch,
} from "@tanstack/react-router";
import { ErrorBoundary, type FallbackProps } from "react-error-boundary";
import { RootLayout, NotFound } from "@/components/layout/RootLayout";
import { Skeleton } from "@/components/ui/skeleton";

const ConfigForm = lazy(() =>
  import("@/components/analysis/ConfigForm").then((module) => ({
    default: module.ConfigForm,
  })),
);
const AnalysisDashboard = lazy(() =>
  import("@/components/analysis/AnalysisDashboard").then((module) => ({
    default: module.AnalysisDashboard,
  })),
);
const HomeDashboard = lazy(() =>
  import("@/components/dashboard/HomeDashboard").then((module) => ({
    default: module.HomeDashboard,
  })),
);
const HistoryList = lazy(() =>
  import("@/components/dashboard/HistoryList").then((module) => ({
    default: module.HistoryList,
  })),
);
const ConfigPageComponent = lazy(() =>
  import("@/components/config/ConfigPage").then((module) => ({
    default: module.ConfigPage,
  })),
);
const MemoryPageComponent = lazy(() =>
  import("@/components/config/MemoryPage").then((module) => ({
    default: module.MemoryPage,
  })),
);
const ScannerPageComponent = lazy(() =>
  import("@/components/scanner/ScannerPage").then((module) => ({
    default: module.ScannerPage,
  })),
);
const ScanHistoryPage = lazy(() =>
  import("@/components/scanner/ScanHistoryPage").then((module) => ({
    default: module.ScanHistoryPage,
  })),
);
const ScanDetailPage = lazy(() =>
  import("@/components/scanner/ScanDetailPage").then((module) => ({
    default: module.ScanDetailPage,
  })),
);
const ScheduledScansPageComponent = lazy(() =>
  import("@/components/scanner/ScheduledScansPage").then((module) => ({
    default: module.ScheduledScansPage,
  })),
);
const AccountsDashboard = lazy(() =>
  import("@/components/accounts/AccountsDashboard").then((module) => ({
    default: module.AccountsDashboard,
  })),
);
const AccountDetailView = lazy(() =>
  import("@/components/accounts/AccountDetailView").then((module) => ({
    default: module.AccountDetailView,
  })),
);
const AnalyticsDashboard = lazy(() =>
  import("@/components/analytics/AnalyticsDashboard").then((module) => ({
    default: module.AnalyticsDashboard,
  })),
);
const StrategiesPageComponent = lazy(() =>
  import("@/components/strategies/StrategiesPage").then((module) => ({
    default: module.StrategiesPage,
  })),
);
const CycleListPage = lazy(() =>
  import("@/components/cycles/CycleListPage").then((module) => ({
    default: module.CycleListPage,
  })),
);
const CycleDetailPage = lazy(() =>
  import("@/components/cycles/CycleDetailPage").then((module) => ({
    default: module.CycleDetailPage,
  })),
);
const TradesPageComponent = lazy(() => import("@/components/trades/TradesPage"));
const SignalAnalyticsPageComponent = lazy(() =>
  import("@/components/signal-analytics/SignalAnalyticsPage").then((module) => ({
    default: module.SignalAnalyticsPage,
  })),
);
const BacktestListPageComponent = lazy(() =>
  import("@/components/backtest/BacktestListPage").then((module) => ({
    default: module.BacktestListPage,
  })),
);
const BacktestNewForm = lazy(() =>
  import("@/components/backtest/BacktestNewForm").then((module) => ({
    default: module.BacktestNewForm,
  })),
);
const BacktestResultsPageComponent = lazy(() =>
  import("@/components/backtest/BacktestResultsPage").then((module) => ({
    default: module.BacktestResultsPage,
  })),
);
const BacktestComparePageComponent = lazy(() =>
  import("@/components/backtest/BacktestComparePage").then((module) => ({
    default: module.BacktestComparePage,
  })),
);
const MCPPageComponent = lazy(() =>
  import("@/components/mcp/MCPPage").then((module) => ({
    default: module.MCPPage,
  })),
);
const MCPProposalReviewPageComponent = lazy(() =>
  import("@/components/mcp/MCPProposalReviewPage").then((module) => ({
    default: module.MCPProposalReviewPage,
  })),
);

function RouteLoading() {
  return (
    <div className="space-y-4 pb-7">
      <Skeleton className="h-40 rounded-[calc(var(--radius)*1.8)]" />
      <Skeleton className="h-60 rounded-[calc(var(--radius)*1.6)]" />
    </div>
  );
}

function RouteErrorFallback({ error, resetErrorBoundary }: FallbackProps) {
  const isChunkError = error instanceof Error && (
    error.message.includes("Failed to fetch dynamically imported module") ||
    error.message.includes("Loading chunk") ||
    error.name === "ChunkLoadError"
  );

  if (isChunkError) {
    window.location.reload();
    return null;
  }

  return (
    <div className="flex flex-col items-center justify-center py-20 px-6 text-center">
      <div className="neu-surface-base neu-surface-raised rounded-[var(--neu-radius-lg)] p-8 max-w-md w-full shadow-[var(--neu-shadow-float)]">
        <h2 className="text-lg font-bold text-[var(--neu-text-strong)] mb-2">Something went wrong</h2>
        <p className="text-sm text-[var(--neu-text-muted)] mb-4">{error instanceof Error ? error.message : String(error)}</p>
        <button
          onClick={resetErrorBoundary}
          className="px-4 py-2 text-sm font-medium rounded-[var(--neu-radius-md)] bg-[var(--neu-accent)] text-white hover:opacity-90 transition-opacity"
        >
          Try again
        </button>
      </div>
    </div>
  );
}

function RouteSuspense({ children }: { children: ReactNode }) {
  return (
    <ErrorBoundary FallbackComponent={RouteErrorFallback}>
      <Suspense fallback={<RouteLoading />}>{children}</Suspense>
    </ErrorBoundary>
  );
}

const rootRoute = createRootRoute({
  component: RootLayout,
  notFoundComponent: NotFound,
});

function HomePage() {
  return (
    <RouteSuspense>
      <HomeDashboard />
    </RouteSuspense>
  );
}

function AnalysisNewPage() {
  return (
    <RouteSuspense>
      <div className="mx-auto w-full py-2 sm:py-4">
        <ConfigForm />
      </div>
    </RouteSuspense>
  );
}

function AnalysisRunPage() {
  const { runId } = useParams({ from: "/analysis/$runId" });
  return (
    <RouteSuspense>
      <AnalysisDashboard runId={runId} />
    </RouteSuspense>
  );
}

function HistoryPage() {
  return (
    <RouteSuspense>
      <HistoryList />
    </RouteSuspense>
  );
}

function ConfigPage() {
  return (
    <RouteSuspense>
      <ConfigPageComponent />
    </RouteSuspense>
  );
}

function MemoryPage() {
  return (
    <RouteSuspense>
      <MemoryPageComponent />
    </RouteSuspense>
  );
}

function ScannerPage() {
  return (
    <RouteSuspense>
      <ScannerPageComponent />
    </RouteSuspense>
  );
}

function ScannerHistoryPage() {
  return (
    <RouteSuspense>
      <ScanHistoryPage />
    </RouteSuspense>
  );
}

function ScheduledScansPage() {
  return (
    <RouteSuspense>
      <ScheduledScansPageComponent />
    </RouteSuspense>
  );
}

function ScannerDetailPage() {
  const { scanId } = useParams({ from: "/scanner/$scanId" });
  return (
    <RouteSuspense>
      <ScanDetailPage scanId={scanId} />
    </RouteSuspense>
  );
}

function AccountsPage() {
  return (
    <RouteSuspense>
      <AccountsDashboard />
    </RouteSuspense>
  );
}

function AccountDetailPage() {
  const { accountId } = useParams({ from: "/accounts/$accountId" });
  return (
    <RouteSuspense>
      <AccountDetailView accountId={accountId} />
    </RouteSuspense>
  );
}

function PerformancePage() {
  return (
    <RouteSuspense>
      <AnalyticsDashboard />
    </RouteSuspense>
  );
}

function StrategiesPage() {
  return (
    <RouteSuspense>
      <StrategiesPageComponent />
    </RouteSuspense>
  );
}

function CyclesPage() {
  return (
    <RouteSuspense>
      <CycleListPage />
    </RouteSuspense>
  );
}

function CyclesDetailPage() {
  const { cycleId } = useParams({ from: "/cycles/$cycleId" });
  return (
    <RouteSuspense>
      <CycleDetailPage cycleId={cycleId} />
    </RouteSuspense>
  );
}

function TradesPage() {
  return (
    <RouteSuspense>
      <TradesPageComponent />
    </RouteSuspense>
  );
}

function SignalAnalyticsPageWrapper() {
  return (
    <RouteSuspense>
      <SignalAnalyticsPageComponent />
    </RouteSuspense>
  );
}

function BacktestListRoutePage() {
  const navigate = useNavigate();
  return (
    <RouteSuspense>
      <BacktestListPageComponent
        onOpen={(runId) => navigate({ to: "/backtest/$runId", params: { runId } })}
        onCreate={() => navigate({ to: "/backtest/new" })}
        onCompare={(runIds) =>
          navigate({ to: "/backtest/compare", search: { runs: runIds.join(",") } })
        }
      />
    </RouteSuspense>
  );
}

function BacktestNewRoutePage() {
  const navigate = useNavigate();
  const search = useSearch({ from: "/backtest/new" }) as { seed?: string };
  // A "Retry"/"Backtest these settings" entry may carry a JSON-encoded seed config.
  let seed: Record<string, unknown> | undefined;
  if (search.seed) {
    try {
      seed = JSON.parse(search.seed);
    } catch {
      seed = undefined;
    }
  }
  return (
    <RouteSuspense>
      <div className="mx-auto w-full max-w-5xl py-2 sm:py-4">
        <BacktestNewForm
          seed={seed}
          onCreated={(runId) => navigate({ to: "/backtest/$runId", params: { runId } })}
        />
      </div>
    </RouteSuspense>
  );
}

function BacktestRunRoutePage() {
  const { runId } = useParams({ from: "/backtest/$runId" });
  const navigate = useNavigate();
  return (
    <RouteSuspense>
      <BacktestResultsPageComponent
        runId={runId}
        onBack={() => navigate({ to: "/backtest" })}
        onCompare={(runIds) =>
          navigate({ to: "/backtest/compare", search: { runs: runIds.join(",") } })
        }
        onRetry={(config) => navigate({ to: "/backtest/new", search: { seed: JSON.stringify(config) } })}
      />
    </RouteSuspense>
  );
}

function BacktestCompareRoutePage() {
  const navigate = useNavigate();
  const search = useSearch({ from: "/backtest/compare" }) as { runs?: string };
  const runIds = (search.runs ?? "").split(",").filter(Boolean);
  return (
    <RouteSuspense>
      <BacktestComparePageComponent runIds={runIds} onBack={() => navigate({ to: "/backtest" })} />
    </RouteSuspense>
  );
}

function MCPRoutePage() {
  const navigate = useNavigate();
  return (
    <RouteSuspense>
      <MCPPageComponent
        onOpenProposal={(proposalId) =>
          navigate({ to: "/mcp/proposals/$proposalId", params: { proposalId } })
        }
      />
    </RouteSuspense>
  );
}

function MCPProposalRoutePage() {
  const { proposalId } = useParams({ from: "/mcp/proposals/$proposalId" });
  const navigate = useNavigate();
  return (
    <RouteSuspense>
      <MCPProposalReviewPageComponent
        proposalId={proposalId}
        onBack={() => navigate({ to: "/mcp" })}
      />
    </RouteSuspense>
  );
}


const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: HomePage,
});

const analysisNewRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/analysis/new",
  component: AnalysisNewPage,
});

const analysisRunRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/analysis/$runId",
  component: AnalysisRunPage,
});

const historyRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/history",
  component: HistoryPage,
});

const configRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/config",
  component: ConfigPage,
});

const memoryRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/memory",
  component: MemoryPage,
});

const scannerRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/scanner",
  component: ScannerPage,
});

const scannerHistoryRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/scanner/history",
  component: ScannerHistoryPage,
});

const scheduledScansRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/scanner/schedules",
  component: ScheduledScansPage,
});

const scannerDetailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/scanner/$scanId",
  component: ScannerDetailPage,
});

const accountsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/accounts",
  component: AccountsPage,
});

const accountDetailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/accounts/$accountId",
  component: AccountDetailPage,
});

const performanceRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/analytics",
  component: PerformancePage,
});

const strategiesRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/strategies",
  component: StrategiesPage,
});

const cyclesRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/cycles",
  component: CyclesPage,
});

const cycleDetailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/cycles/$cycleId",
  component: CyclesDetailPage,
});

const tradesRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/trades",
  component: TradesPage,
});

const signalAnalyticsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/signal-analytics",
  component: SignalAnalyticsPageWrapper,
});

const backtestListRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/backtest",
  component: BacktestListRoutePage,
});

const backtestNewRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/backtest/new",
  component: BacktestNewRoutePage,
  validateSearch: (search: Record<string, unknown>): { seed?: string } => ({
    seed: typeof search.seed === "string" ? search.seed : undefined,
  }),
});

const backtestCompareRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/backtest/compare",
  component: BacktestCompareRoutePage,
  validateSearch: (search: Record<string, unknown>): { runs?: string } => ({
    runs: typeof search.runs === "string" ? search.runs : undefined,
  }),
});

const backtestRunRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/backtest/$runId",
  component: BacktestRunRoutePage,
});


const mcpRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/mcp",
  component: MCPRoutePage,
});


const mcpProposalRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/mcp/proposals/$proposalId",
  component: MCPProposalRoutePage,
});


export const routeTree = rootRoute.addChildren([
  indexRoute,
  analysisNewRoute,
  analysisRunRoute,
  historyRoute,
  configRoute,
  memoryRoute,
  scannerHistoryRoute,
  scheduledScansRoute,
  scannerDetailRoute,
  scannerRoute,
  accountsRoute,
  accountDetailRoute,
  performanceRoute,
  strategiesRoute,
  cyclesRoute,
  cycleDetailRoute,
  tradesRoute,
  signalAnalyticsRoute,
  backtestNewRoute,
  backtestCompareRoute,
  backtestRunRoute,
  backtestListRoute,
  mcpRoute,
  mcpProposalRoute,
]);

export function createAppRouter() {
  return createRouter({ routeTree });
}
