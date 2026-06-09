/**
 * @module App
 *
 * Root application component for the TradingAgents frontend.
 *
 * Responsibilities:
 * - Bootstraps the global provider hierarchy (Redux, React Query with persistence, theme)
 * - Mounts the TanStack Router
 * - Wraps the rendered tree in a top-level error boundary so any unhandled render
 *   error is caught and surfaced to the user rather than showing a blank screen
 *
 * @remarks
 * The file also performs one-time side-effect configuration at module load time:
 * - Disables React Query's focus/visibility refetch listener to prevent full-page
 *   reloads when a mobile browser tab is backgrounded and restored
 * - Creates a singleton QueryClient and sessionStorage persister so both survive
 *   across the full application lifetime without being recreated on re-renders
 */

import { focusManager } from "@tanstack/react-query";
import { PersistQueryClientProvider } from "@tanstack/react-query-persist-client";
import { createSyncStoragePersister } from "@tanstack/query-sync-storage-persister";
import { QueryClient } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { Provider as ReduxProvider } from "react-redux";
import { ErrorBoundary, type FallbackProps } from "react-error-boundary";
import { NeuThemeScope } from "@/design-system/neumorphism";
import { Toaster } from "@/components/ui/sonner";
import { useThemeEffect } from "@/hooks/useThemeEffect";
import { logger } from "@/lib/logger";
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

// AI-CONTEXT: Error boundary strategy
// The ErrorBoundary from react-error-boundary wraps only the router subtree inside
// AppFrame, intentionally placed *inside* NeuThemeScope so the fallback UI inherits
// the active theme tokens and looks consistent with the rest of the application.
// Toaster is intentionally placed *outside* the boundary so toast notifications
// remain available even while the fallback is rendered (e.g. to show a "reload
// triggered" message). onReset calls window.location.reload() rather than simply
// clearing component state because the most common root cause of a boundary trip is
// a route-level data or chunk-load failure that requires a full navigation cycle.

/**
 * Full-screen error fallback rendered by the top-level ErrorBoundary when an
 * unhandled render exception propagates out of the router subtree.
 *
 * @param props.error - The caught Error instance; its message is surfaced to the user.
 * @param props.resetErrorBoundary - Callback supplied by react-error-boundary; wired
 *   to `window.location.reload()` at the call site so clicking "Reload" performs a
 *   hard navigation rather than re-rendering into a potentially broken state.
 * @returns A centred card containing the error message and a reload button.
 */
function ErrorFallback({ error, resetErrorBoundary }: FallbackProps) {
  return (
    <div className="flex min-h-screen items-center justify-center p-8">
      <div className="max-w-md text-center">
        <h1 className="text-2xl font-bold mb-4">Something went wrong</h1>
        <p className="text-muted-foreground mb-4">{error instanceof Error ? error.message : String(error)}</p>
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

/** Reads theme state from Redux and applies it via NeuThemeScope. Wraps router in ErrorBoundary + Toaster. Lives inside ReduxProvider so it can access neuUi slice. */
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
      <ErrorBoundary
        FallbackComponent={ErrorFallback}
        onError={(error, info) =>
          // AI-CONTEXT: Single observability hook for unhandled render crashes. The
          // fallback UI shows the user a recovery path; this records WHAT crashed
          // (message + component stack) for the error reporter so production
          // failures aren't invisible. Never logs props/state (may contain PII).
          logger.error("AppErrorBoundary", error instanceof Error ? error.message : String(error), {
            componentStack: info.componentStack,
          })
        }
        onReset={() => window.location.reload()}
      >
        <RouterProvider router={router} />
      </ErrorBoundary>
      <Toaster />
    </NeuThemeScope>
  );
}

// AI-CONTEXT: Provider hierarchy (outermost → innermost)
// 1. ReduxProvider         — makes the global Redux store available everywhere; must
//                            be outermost so any child (including query callbacks) can
//                            dispatch actions or read slice state.
// 2. PersistQueryClientProvider — wraps the singleton QueryClient with sessionStorage
//                            persistence so Android Chrome tab-discard survivors can
//                            rehydrate cached server data without a network round-trip.
//                            Must be inside Redux so query side-effects can dispatch.
// 3. AppFrame              — reads Redux state to derive the active neumorphism theme
//                            tokens (mode/accent/contrast) and applies them via
//                            NeuThemeScope; must be inside both providers above.
// 4. NeuThemeScope         — injects CSS custom properties for the active theme into
//                            the subtree; RouterProvider and ErrorBoundary live here.

/**
 * Root application component.
 *
 * Composes the full provider hierarchy required by the application and delegates
 * theme application and routing to {@link AppFrame}.
 *
 * Provider order (see AI-CONTEXT comment above for rationale):
 * `ReduxProvider` → `PersistQueryClientProvider` → `AppFrame`
 *
 * @returns The application tree wrapped in all required context providers.
 *
 * @example
 * // main.tsx
 * import App from "./App";
 * ReactDOM.createRoot(document.getElementById("root")!).render(<App />);
 */
function App() {
  return (
    <ReduxProvider store={store}>
      <PersistQueryClientProvider
        client={queryClient}
        persistOptions={{
          persister,
          maxAge: 60 * 60_000, // 1 hr — matches gcTime
          buster: "",          // change this string to invalidate old caches after deploys
          // AI-CONTEXT: SECURITY — the model-picker query ("proxy-models") embeds the
          // user's LLM provider API key in its queryKey for cache identity. Persisting
          // it would write that plaintext key to sessionStorage ("rq-cache"), a second
          // at-rest copy beyond the documented endpoints.ts case. Exclude it from
          // dehydration so the key is never serialized to storage; it still caches
          // in-memory for the session.
          dehydrateOptions: {
            shouldDehydrateQuery: (query) =>
              query.state.status === "success" && query.queryKey[0] !== "proxy-models",
          },
        }}
      >
        <AppFrame />
      </PersistQueryClientProvider>
    </ReduxProvider>
  );
}

export default App;
