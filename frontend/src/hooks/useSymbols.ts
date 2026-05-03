import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/api/client";

export function useSymbols(assetType: string) {
  return useQuery({
    queryKey: ["symbols", assetType],
    queryFn: ({ signal }) => apiClient.getSymbols(assetType, signal),
    staleTime: 60 * 60 * 1000,
    gcTime: 2 * 60 * 60 * 1000,
    enabled: assetType === "crypto",
    select: (data) => data.symbols,
  });
}
