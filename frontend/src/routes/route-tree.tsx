import {
  createRootRoute,
  createRoute,
  createRouter,
  Outlet,
  Link,
} from "@tanstack/react-router";

const rootRoute = createRootRoute({
  component: RootLayout,
  notFoundComponent: NotFound,
});

function RootLayout() {
  return (
    <div className="flex h-screen">
      <nav className="w-56 border-r bg-sidebar p-4 flex flex-col gap-2">
        <h1 className="text-lg font-bold mb-4">TradingAgents</h1>
        <Link to="/" className="block px-2 py-1 rounded hover:bg-accent">
          Home
        </Link>
        <Link
          to="/analysis/new"
          className="block px-2 py-1 rounded hover:bg-accent"
        >
          New Analysis
        </Link>
        <Link
          to="/history"
          className="block px-2 py-1 rounded hover:bg-accent"
        >
          History
        </Link>
        <Link to="/config" className="block px-2 py-1 rounded hover:bg-accent">
          Config
        </Link>
        <Link to="/memory" className="block px-2 py-1 rounded hover:bg-accent">
          Memory
        </Link>
      </nav>
      <main className="flex-1 overflow-auto p-6">
        <Outlet />
      </main>
    </div>
  );
}

function NotFound() {
  return (
    <div className="flex items-center justify-center h-full">
      <div className="text-center">
        <h2 className="text-2xl font-bold">Page Not Found</h2>
        <p className="text-muted-foreground mt-2">
          The page you're looking for doesn't exist.
        </p>
        <Link to="/" className="text-primary underline mt-4 inline-block">
          Go home
        </Link>
      </div>
    </div>
  );
}

const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: () => (
    <div>
      <h2 className="text-xl font-bold">TradingAgents Dashboard</h2>
      <p className="text-muted-foreground mt-2">Welcome to TradingAgents.</p>
    </div>
  ),
});

const analysisNewRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/analysis/new",
  component: () => (
    <div>
      <h2 className="text-xl font-bold">New Analysis</h2>
    </div>
  ),
});

const analysisRunRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/analysis/$runId",
  component: () => (
    <div>
      <h2 className="text-xl font-bold">Analysis Run</h2>
    </div>
  ),
});

const historyRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/history",
  component: () => (
    <div>
      <h2 className="text-xl font-bold">History</h2>
    </div>
  ),
});

const configRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/config",
  component: () => (
    <div>
      <h2 className="text-xl font-bold">Configuration</h2>
    </div>
  ),
});

const memoryRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/memory",
  component: () => (
    <div>
      <h2 className="text-xl font-bold">Memory</h2>
    </div>
  ),
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
