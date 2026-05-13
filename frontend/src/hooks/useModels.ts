import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/api/client";

export interface ModelInfo {
  id: string;
  name?: string;
}

function normalizeUrl(raw: string | undefined): string | undefined {
  const trimmed = raw?.trim();
  if (!trimmed) return undefined;
  return trimmed.replace(/\/+$/, "");
}

export function useModels(modelsUrl: string | undefined, apiKey?: string) {
  const url = normalizeUrl(modelsUrl);
  return useQuery({
    queryKey: ["proxy-models", url, apiKey],
    queryFn: async (): Promise<ModelInfo[]> => {
      const resp = await apiClient.fetchRemoteModels(url!, apiKey);
      return resp.models ?? [];
    },
    enabled: !!url,
    staleTime: 120_000,
    retry: 1,
  });
}
