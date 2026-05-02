import {
  createRootRoute,
  createRoute,
  createRouter,
} from "@tanstack/react-router";
import { RootLayout, NotFound } from "@/components/layout/RootLayout";

const rootRoute = createRootRoute({
  component: RootLayout,
  notFoundComponent: NotFound,
});

function HomePage() {
  return (
    <div>
      <h2 className="text-xl font-bold">TradingAgents Dashboard</h2>
      <p className="text-muted-foreground mt-2">Welcome to TradingAgents.</p>
    </div>
  );
}

function AnalysisNewPage() {
  return (
    <div>
      <h2 className="text-xl font-bold">New Analysis</h2>
    </div>
  );
}

function AnalysisRunPage() {
  return (
    <div>
      <h2 className="text-xl font-bold">Analysis Run</h2>
    </div>
  );
}

function HistoryPage() {
  return (
    <div>
      <h2 className="text-xl font-bold">History</h2>
    </div>
  );
}

function ConfigPage() {
  return (
    <div>
      <h2 className="text-xl font-bold">Configuration</h2>
    </div>
  );
}

function MemoryPage() {
  return (
    <div>
      <h2 className="text-xl font-bold">Memory</h2>
    </div>
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
