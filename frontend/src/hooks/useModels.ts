import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/api/client";

export interface ModelInfo {
  id: string;
  name?: string;
}

/** Providers the backend can list models for natively (have an official base URL).
 *  Mirrors PROVIDER_BASE_URLS in backend/routers/models.py. `azure` is excluded
 *  (no fixed base URL — it needs a custom endpoint). */
const NATIVE_FETCH_PROVIDERS = new Set([
  "openai",
  "anthropic",
  "google",
  "deepseek",
  "nvidia",
  "xai",
  "qwen",
  "glm",
  "openrouter",
  "ollama",
]);

function normalizeUrl(raw: string | undefined): string | undefined {
  const trimmed = raw?.trim();
  if (!trimmed) return undefined;
  return trimmed.replace(/\/+$/, "");
}

/**
 * List models for the model pickers.
 *
 * Two modes (a custom proxy URL takes precedence):
 *   - Custom proxy: query `{url}/v1/models`.
 *   - Native provider: when no URL is set, query the provider's official API
 *     (e.g. the real Anthropic catalog) so the dropdowns show live models
 *     instead of the hardcoded fallback list.
 */
export function useModels(
  modelsUrl: string | undefined,
  apiKey?: string,
  provider?: string,
) {
  const url = normalizeUrl(modelsUrl);
  const prov = provider?.trim().toLowerCase() || undefined;
  const nativeProvider = prov && NATIVE_FETCH_PROVIDERS.has(prov) ? prov : undefined;
  // When a proxy URL is set it wins; provider must not affect the cache key
  // (preserves prior proxy behaviour — no refetch on provider switch).
  const keyProvider = url ? undefined : nativeProvider;
  return useQuery({
    queryKey: ["proxy-models", url, apiKey, keyProvider],
    queryFn: async (): Promise<ModelInfo[]> => {
      const resp = await apiClient.fetchRemoteModels(url, apiKey, url ? undefined : nativeProvider);
      return resp.models ?? [];
    },
    enabled: !!url || !!nativeProvider,
    staleTime: 120_000,
    retry: 1,
  });
}
