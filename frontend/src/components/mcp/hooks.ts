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
    return err.detail || err.message;
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
    // Poll while the page is open so pending-proposal count + running state stay live.
    refetchInterval: 8_000,
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
    staleTime: 5_000,
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
  const invalidate = useInvalidateMCP();
  return useMutation({
    mutationFn: (vars: {
      patch: Partial<Pick<MCPConfig, "enabled" | "capability_tier" | "enabled_groups" | "enabled_tools">>;
      rowVersion: number;
    }) => mcpApi.patchConfig(vars.patch, vars.rowVersion),
    onSuccess: () => invalidate(),
    onError: (err) => toast.error(mcpErrorMessage(err)),
  });
}

/** Apply a named preset (writes per-tool overrides + raises tier). */
export function useApplyPreset() {
  const invalidate = useInvalidateMCP();
  return useMutation({
    mutationFn: (vars: { preset: string; rowVersion: number }) =>
      mcpApi.applyPreset(vars.preset, vars.rowVersion),
    onSuccess: () => {
      toast.success("Preset applied");
      invalidate();
    },
    onError: (err) => toast.error(mcpErrorMessage(err)),
  });
}
