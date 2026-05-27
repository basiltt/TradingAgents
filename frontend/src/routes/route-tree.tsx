/* eslint-disable react-refresh/only-export-components */
import { Suspense, lazy, type ReactNode } from "react";
import {
  createRootRoute,
  createRoute,
  createRouter,
  useParams,
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

function RouteLoading() {
  return (
    <div className="space-y-4 pb-7">
      <Skeleton className="h-40 rounded-[calc(var(--radius)*1.8)]" />
      <Skeleton className="h-60 rounded-[calc(var(--radius)*1.6)]" />
    </div>
  );
}

function RouteErrorFallback({ error, resetErrorBoundary }: FallbackProps) {
  return (
    <div className="flex flex-col items-center justify-center py-20 px-6 text-center">
      <div className="neu-surface-base neu-surface-raised rounded-[var(--neu-radius-lg)] p-8 max-w-md w-full shadow-[var(--neu-shadow-float)]">
        <h2 className="text-lg font-bold text-[var(--neu-text-strong)] mb-2">Something went wrong</h2>
        <p className="text-sm text-[var(--neu-text-muted)] mb-4">{error.message}</p>
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
]);

export function createAppRouter() {
  return createRouter({ routeTree });
}
