import { useQuery } from "@tanstack/react-query";

export interface ModelInfo {
  id: string;
  name?: string;
}

interface OpenAIModelsResponse {
  data: Array<{ id: string; name?: string }>;
}

async function fetchModels(modelsUrl: string, apiKey?: string): Promise<ModelInfo[]> {
  const url = modelsUrl.replace(/\/+$/, "");
  const endpoint = url.endsWith("/v1/models") ? url : `${url}/v1/models`;
  const res = await fetch(endpoint, {
    signal: AbortSignal.timeout(5_000),
    headers: { Authorization: `Bearer ${apiKey || "dummy"}` },
  });
  if (!res.ok) throw new Error(`${res.status}`);
  const json: OpenAIModelsResponse = await res.json();
  return (json.data ?? []).map((m) => ({ id: m.id, name: m.name }));
}

export function useModels(modelsUrl: string | undefined, apiKey?: string) {
  return useQuery({
    queryKey: ["proxy-models", modelsUrl, apiKey],
    queryFn: () => fetchModels(modelsUrl!, apiKey),
    enabled: !!modelsUrl?.trim(),
    staleTime: 120_000,
    retry: 1,
  });
}
