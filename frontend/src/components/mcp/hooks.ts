/**
 * Shared TanStack Query hooks for the MCP operator console.
 *
 * Centralizes the query keys, fetchers, and mutations so the page sections
 * (status header, budget manager, connection panel, proposal queue) stay in
 * sync — a mutation in one section invalidates the queries the others read.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { mcpApi, ApiError } from "@/api/client";
import type { MCPConfig } from "./types";

const KEYS = {
  config: ["mcp", "config"] as const,
  status: ["mcp", "status"] as const,
  registry: ["mcp", "registry"] as const,
  proposals: (status?: string) => ["mcp", "proposals", status ?? "all"] as const,
};

/** Human message for the 503 "module absent" case vs other failures. */
export function mcpErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 503) return "The MCP module is not available in this build.";
    if (err.status === 409) return "Config changed in another tab — refresh and retry.";
    // The backend returns structured 422 details (preflight/preset/objective);
    // ApiError stringifies them — translate the known shapes to a sentence.
    const d = err.detail || "";
    if (d.includes("preflight_failed")) {
      const m = d.match(/preflight_failed["':\s]+([a-z_]+)/i);
      return `Can't enable: preflight check failed${m ? ` (${m[1]})` : ""}.`;
    }
    if (d.includes("unknown_preset")) return "That preset is not recognized.";
    if (d.includes("unsupported_objective")) return "That objective metric is not supported.";
    return d || err.message;
  }
  return err instanceof Error ? err.message : String(err);
}

export function useMCPConfig() {
  return useQuery({
    queryKey: KEYS.config,
    queryFn: ({ signal }) => mcpApi.getConfig(signal),
    staleTime: 10_000,
    retry: (count, err) => !(err instanceof ApiError && err.status === 503) && count < 1,
  });
}

export function useMCPStatus() {
  return useQuery({
    queryKey: KEYS.status,
    queryFn: ({ signal }) => mcpApi.getStatus(signal),
    // Poll while the page is open, but STOP polling when the module is absent
    // (503) — the retry guard only stops retries, not the interval, so without
    // this a module-off page hammers the endpoint forever.
    refetchInterval: (q) => (q.state.error instanceof ApiError && q.state.error.status === 503 ? false : 8_000),
    staleTime: 4_000,
    retry: (count, err) => !(err instanceof ApiError && err.status === 503) && count < 1,
  });
}

export function useMCPRegistry() {
  return useQuery({
    queryKey: KEYS.registry,
    queryFn: ({ signal }) => mcpApi.getRegistry(signal),
    staleTime: 10_000,
    retry: (count, err) => !(err instanceof ApiError && err.status === 503) && count < 1,
  });
}

export function useMCPProposals(status?: string) {
  return useQuery({
    queryKey: KEYS.proposals(status),
    queryFn: ({ signal }) => mcpApi.listProposals(status, signal),
    // Poll so a proposal the agent creates in the background appears without a
    // manual refresh — keeps this list in sync with the polled pending count.
    // Stop polling on 503 (module absent) so it doesn't hammer forever.
    refetchInterval: (q) => (q.state.error instanceof ApiError && q.state.error.status === 503 ? false : 8_000),
    staleTime: 4_000,
    retry: (count, err) => !(err instanceof ApiError && err.status === 503) && count < 1,
  });
}

/** Invalidate every MCP query — used after any mutation that changes server state. */
export function useInvalidateMCP() {
  const qc = useQueryClient();
  return () => {
    qc.invalidateQueries({ queryKey: ["mcp"] });
  };
}

/** Enable / disable the server (master toggle). */
export function useToggleMCP() {
  const invalidate = useInvalidateMCP();
  return useMutation({
    mutationFn: async (next: boolean) => (next ? mcpApi.enable() : mcpApi.disable(false)),
    onSuccess: (_data, next) => {
      toast.success(next ? "MCP server enabled" : "MCP server disabled");
      invalidate();
    },
    onError: (err) => toast.error(mcpErrorMessage(err)),
  });
}

/** Patch the persisted config with optimistic-concurrency (row_version). */
export function usePatchMCPConfig() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: {
      patch: Partial<Pick<MCPConfig, "enabled" | "capability_tier" | "enabled_groups" | "enabled_tools">>;
      rowVersion: number;
    }) => mcpApi.patchConfig(vars.patch, vars.rowVersion),
    // Seed the returned config (with the bumped row_version) synchronously so a
    // rapid follow-up toggle uses the fresh version and does NOT self-inflict a
    // 409 in the post-settle / pre-refetch window. Then invalidate to refresh
    // the registry's derived enabled/selected state.
    onSuccess: (data) => {
      qc.setQueryData(KEYS.config, data);
      qc.invalidateQueries({ queryKey: KEYS.registry });
      qc.invalidateQueries({ queryKey: KEYS.status });
    },
    onError: (err) => toast.error(mcpErrorMessage(err)),
  });
}

/** Apply a named preset (writes per-tool overrides + raises tier). */
export function useApplyPreset() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { preset: string; rowVersion: number }) =>
      mcpApi.applyPreset(vars.preset, vars.rowVersion),
    onSuccess: (registry) => {
      // The preset endpoint returns the fresh registry (with the bumped
      // row_version). Seed the registry AND patch config's row_version
      // synchronously so a follow-up tool toggle uses the fresh version and
      // does NOT self-inflict a 409 before the config refetch lands.
      qc.setQueryData(KEYS.registry, registry);
      qc.setQueryData(KEYS.config, (old: MCPConfig | undefined) =>
        old ? { ...old, row_version: registry.row_version, capability_tier: registry.capability_tier } : old,
      );
      qc.invalidateQueries({ queryKey: KEYS.config });
      toast.success("Preset applied");
    },
    onError: (err) => toast.error(mcpErrorMessage(err)),
  });
}
