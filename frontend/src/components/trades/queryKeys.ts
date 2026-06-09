/**
 * @module queryKeys
 *
 * Centralized React Query cache keys for the trades domain.
 *
 * Architectural role: a single source of truth for the `["trades", ...]` key
 * arrays that were previously hand-written as string literals across five call
 * sites (useTradeActions, useTradeHistory, useTradeStats, useTradeEvents, and the
 * account WebSocket hook). A typo in any of those literals silently breaks cache
 * invalidation with no error — exactly the failure this module prevents.
 *
 * Boundary: pure key factories, no React/Query imports. TanStack Query matches by
 * key PREFIX, so the partial keys (e.g. `tradeQueryKeys.history()`) invalidate every
 * query whose key starts with them (including the filtered list keys).
 */

/**
 * Factory for trades-domain React Query keys.
 *
 * Partial keys (no args) are used for `invalidateQueries` — they match all queries
 * sharing the prefix. The `*List`/`*For` variants build the full keys used when
 * registering a `useQuery`/`useInfiniteQuery`.
 *
 * @example
 * useInfiniteQuery({ queryKey: tradeQueryKeys.historyList(filters), ... });
 * queryClient.invalidateQueries({ queryKey: tradeQueryKeys.history() }); // invalidates all history pages
 */
export const tradeQueryKeys = {
  /** Root key for the entire trades domain. */
  all: ["trades"] as const,
  /** Prefix key for trade-history queries (invalidates every filtered history list). */
  history: () => ["trades", "history"] as const,
  /** Full key for a specific filtered history list. */
  historyList: (filters: unknown) => ["trades", "history", filters] as const,
  /** Prefix key for trade-stats queries. */
  stats: () => ["trades", "stats"] as const,
  /** Full key for stats scoped to a specific (sorted) account-id set. */
  statsFor: (accountIds: string[]) => ["trades", "stats", [...accountIds].sort()] as const,
  /** Prefix key for the active-trades query. */
  active: () => ["trades", "active"] as const,
  /** Full key for a single trade's audit events. */
  events: (tradeId: string) => ["trades", "events", tradeId] as const,
} as const;
