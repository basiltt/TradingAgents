import {
  createRootRoute,
  createRoute,
  createRouter,
  useParams,
} from "@tanstack/react-router";
import { RootLayout, NotFound } from "@/components/layout/RootLayout";
import { ConfigForm } from "@/components/analysis/ConfigForm";
import { AnalysisDashboard } from "@/components/analysis/AnalysisDashboard";
import { HomeDashboard } from "@/components/dashboard/HomeDashboard";
import { HistoryList } from "@/components/dashboard/HistoryList";
import { ConfigPage as ConfigPageComponent } from "@/components/config/ConfigPage";
import { MemoryPage as MemoryPageComponent } from "@/components/config/MemoryPage";

const rootRoute = createRootRoute({
  component: RootLayout,
  notFoundComponent: NotFound,
});

function HomePage() {
  return <HomeDashboard />;
}

function AnalysisNewPage() {
  return (
    <div className="max-w-2xl mx-auto py-4">
      <ConfigForm />
    </div>
  );
}

function AnalysisRunPage() {
  const { runId } = useParams({ from: "/analysis/$runId" });
  return <AnalysisDashboard runId={runId} />;
}

function HistoryPage() {
  return <HistoryList />;
}

function ConfigPage() {
  return <ConfigPageComponent />;
}

function MemoryPage() {
  return <MemoryPageComponent />;
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

export const routeTree = rootRoute.addChildren([
  indexRoute,
  analysisNewRoute,
  analysisRunRoute,
  historyRoute,
  configRoute,
  memoryRoute,
]);

export function createAppRouter() {
  return createRouter({ routeTree });
}
