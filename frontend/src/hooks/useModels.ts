import { useQuery } from "@tanstack/react-query";

export interface ModelInfo {
  id: string;
  name?: string;
}

interface OpenAIModelsResponse {
  data: Array<{ id: string; name?: string }>;
}

async function fetchModels(modelsUrl: string): Promise<ModelInfo[]> {
  const url = modelsUrl.replace(/\/+$/, "");
  const endpoint = url.endsWith("/v1/models") ? url : `${url}/v1/models`;
  const res = await fetch(endpoint, {
    signal: AbortSignal.timeout(5_000),
    headers: { Authorization: "Bearer dummy" },
  });
  if (!res.ok) throw new Error(`${res.status}`);
  const json: OpenAIModelsResponse = await res.json();
  return (json.data ?? []).map((m) => ({ id: m.id, name: m.name }));
}

export function useModels(modelsUrl: string | undefined) {
  return useQuery({
    queryKey: ["proxy-models", modelsUrl],
    queryFn: () => fetchModels(modelsUrl!),
    enabled: !!modelsUrl?.trim(),
    staleTime: 120_000,
    retry: 1,
  });
}
