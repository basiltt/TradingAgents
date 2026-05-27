import { focusManager } from "@tanstack/react-query";
import { PersistQueryClientProvider } from "@tanstack/react-query-persist-client";
import { createSyncStoragePersister } from "@tanstack/query-sync-storage-persister";
import { QueryClient } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { Provider as ReduxProvider } from "react-redux";
import { ErrorBoundary } from "react-error-boundary";
import { NeuThemeScope } from "@/design-system/neumorphism";
import { Toaster } from "@/components/ui/sonner";
import { useThemeEffect } from "@/hooks/useThemeEffect";
import { store } from "./store";
import { useAppSelector } from "./store";
import { createAppRouter } from "./routes/route-tree";

// Disable React Query's built-in focus/visibility listener entirely.
// On mobile, switching away and back triggers this and causes all queries
// to refetch, making every page appear to reload.
focusManager.setEventListener(() => () => {});

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30 * 60_000,  // 30 min
      gcTime: 60 * 60_000,     // 1 hr — must be >= maxAge for persister to be useful
      retry: 1,
      refetchOnWindowFocus: false,
      refetchOnReconnect: false,
    },
  },
});

// Persist the query cache to sessionStorage so Android Chrome tab discard
// (which destroys JS memory after a few minutes in background) doesn't wipe it.
const persister = createSyncStoragePersister({
  storage: window.sessionStorage,
  key: "rq-cache",
  throttleTime: 2000,
});

const router = createAppRouter();

function ErrorFallback({ error, resetErrorBoundary }: { error: Error; resetErrorBoundary: () => void }) {
  return (
    <div className="flex min-h-screen items-center justify-center p-8">
      <div className="max-w-md text-center">
        <h1 className="text-2xl font-bold mb-4">Something went wrong</h1>
        <p className="text-muted-foreground mb-4">{error.message}</p>
        <button
          onClick={resetErrorBoundary}
          className="px-4 py-2 bg-primary text-primary-foreground rounded-md"
        >
          Reload
        </button>
      </div>
    </div>
  );
}

function AppFrame() {
  const mode = useAppSelector((state) => state.neuUi.mode);
  const accent = useAppSelector((state) => state.neuUi.accent);
  const contrast = useAppSelector((state) => state.neuUi.contrast);

  useThemeEffect();

  return (
    <NeuThemeScope
      mode={mode}
      accent={accent}
      contrast={contrast}
      className="min-h-screen"
    >
      <ErrorBoundary FallbackComponent={ErrorFallback} onReset={() => window.location.reload()}>
        <RouterProvider router={router} />
      </ErrorBoundary>
      <Toaster />
    </NeuThemeScope>
  );
}

function App() {
  return (
    <ReduxProvider store={store}>
      <PersistQueryClientProvider
        client={queryClient}
        persistOptions={{
          persister,
          maxAge: 60 * 60_000, // 1 hr — matches gcTime
          buster: "",          // change this string to invalidate old caches after deploys
        }}
      >
        <AppFrame />
      </PersistQueryClientProvider>
    </ReduxProvider>
  );
}

export default App;
