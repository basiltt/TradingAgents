import { useState, useCallback } from "react";
import { useNavigate } from "@tanstack/react-router";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Combobox } from "@/components/ui/combobox";
import { useWatchlists } from "@/hooks/useWatchlists";
import { useSymbols } from "@/hooks/useSymbols";
import { apiClient, type StartAnalysisRequest } from "@/api/client";

export interface BatchConfig {
  asset_type: "stock" | "crypto";
  analysis_date: string;
  provider: string;
  llm_api_key: string;
  deep_think_llm: string;
  quick_think_llm: string;
  backend_url: string;
  analysts: string[];
  research_depth: number;
  output_language: string;
  interval: string;
  data_vendors?: Record<string, string>;
}

interface WatchlistPanelProps {
  config: BatchConfig;
}

export function WatchlistPanel({ config }: WatchlistPanelProps) {
  const navigate = useNavigate();
  const { watchlists, create, remove, addTicker, removeTicker } = useWatchlists();
  const { data: symbols = [], isLoading: symbolsLoading } = useSymbols(config.asset_type);

  const [newName, setNewName] = useState("");
  const [addingTo, setAddingTo] = useState<string | null>(null);
  const [tickerInput, setTickerInput] = useState("");
  const [batchState, setBatchState] = useState<{ id: string; done: number; total: number; errors: string[] } | null>(null);

  const handleCreate = () => {
    const name = newName.trim();
    if (!name) return;
    create(name);
    setNewName("");
  };

  const handleAddTicker = (watchlistId: string) => {
    if (!tickerInput.trim()) return;
    addTicker(watchlistId, tickerInput.trim().toUpperCase());
    setTickerInput("");
    setAddingTo(null);
  };

  const handleAnalyzeAll = useCallback(
    async (watchlistId: string, tickers: string[]) => {
      if (tickers.length === 0) return;
      setBatchState({ id: watchlistId, done: 0, total: tickers.length, errors: [] });

      const results = await Promise.allSettled(
        tickers.map(async (ticker) => {
          const body: StartAnalysisRequest = {
            ticker,
            analysis_date: config.analysis_date,
            provider: config.provider || undefined,
            llm_api_key: config.llm_api_key || undefined,
            deep_think_llm: config.deep_think_llm || undefined,
            quick_think_llm: config.quick_think_llm || undefined,
            backend_url: config.backend_url || undefined,
            analysts: config.analysts,
            research_depth: config.research_depth,
            output_language: config.output_language || undefined,
            asset_type: config.asset_type,
            interval: config.asset_type === "crypto" ? (config.interval as "15" | "60" | "240" | "D") : undefined,
            data_vendors: config.data_vendors,
          };
          const res = await apiClient.startAnalysis(body);
          setBatchState((prev) =>
            prev ? { ...prev, done: prev.done + 1 } : prev,
          );
          return res;
        }),
      );

      const errors = results
        .map((r, i) => (r.status === "rejected" ? tickers[i] : null))
        .filter((t): t is string => t != null);

      setBatchState((prev) => (prev ? { ...prev, errors } : prev));

      setTimeout(() => {
        setBatchState(null);
        navigate({ to: "/history" });
      }, 1500);
    },
    [config, navigate],
  );

  return (
    <Card>
      <CardHeader className="pb-4">
        <CardTitle className="text-base flex items-center gap-2">
          <svg className="w-4 h-4 text-muted-foreground" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.784-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z" />
          </svg>
          Watchlists
          {watchlists.length > 0 && (
            <Badge variant="secondary" className="ml-auto text-xs">{watchlists.length}</Badge>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Create new watchlist */}
        <div className="flex gap-2">
          <Input
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="New watchlist name..."
            className="flex-1"
            onKeyDown={(e) => e.key === "Enter" && handleCreate()}
          />
          <Button onClick={handleCreate} disabled={!newName.trim()} size="sm">
            Create
          </Button>
        </div>

        {watchlists.length === 0 && (
          <p className="text-sm text-muted-foreground text-center py-4">
            No watchlists yet. Create one to group your favorite tickers.
          </p>
        )}

        {/* Watchlist items */}
        {watchlists.map((wl) => {
          const isBatching = batchState?.id === wl.id;
          return (
            <div key={wl.id} className="rounded-lg border border-border/50 p-4 space-y-3">
              {/* Header */}
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <h4 className="font-semibold text-sm">{wl.name}</h4>
                  <Badge variant="outline" className="text-xs">{wl.tickers.length}/10</Badge>
                </div>
                <div className="flex items-center gap-1.5">
                  <Button
                    size="sm"
                    variant="default"
                    disabled={wl.tickers.length === 0 || !!batchState}
                    onClick={() => handleAnalyzeAll(wl.id, wl.tickers)}
                    className="text-xs h-7 px-3"
                  >
                    {isBatching
                      ? `${batchState!.done}/${batchState!.total}...`
                      : `Analyze All (${wl.tickers.length})`}
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => remove(wl.id)}
                    className="text-xs h-7 px-2 text-destructive hover:text-destructive"
                  >
                    <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                    </svg>
                  </Button>
                </div>
              </div>

              {/* Batch errors */}
              {isBatching && batchState!.errors.length > 0 && (
                <p className="text-xs text-destructive">
                  Failed: {batchState!.errors.join(", ")}
                </p>
              )}

              {/* Ticker chips */}
              {wl.tickers.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {wl.tickers.map((t) => (
                    <Badge key={t} variant="secondary" className="text-xs gap-1 pr-1">
                      {t}
                      <button
                        type="button"
                        onClick={() => removeTicker(wl.id, t)}
                        className="ml-0.5 rounded-full hover:bg-destructive/20 p-0.5"
                      >
                        <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                        </svg>
                      </button>
                    </Badge>
                  ))}
                </div>
              )}

              {/* Add ticker */}
              {wl.tickers.length < 10 && (
                addingTo === wl.id ? (
                  <div className="flex gap-2">
                    {config.asset_type === "crypto" ? (
                      <Combobox
                        options={symbols}
                        value={tickerInput}
                        onChange={setTickerInput}
                        placeholder="Search symbol..."
                        loading={symbolsLoading}
                        className="flex-1"
                      />
                    ) : (
                      <Input
                        value={tickerInput}
                        onChange={(e) => setTickerInput(e.target.value.toUpperCase())}
                        placeholder="Ticker..."
                        className="flex-1"
                        onKeyDown={(e) => e.key === "Enter" && handleAddTicker(wl.id)}
                      />
                    )}
                    <Button size="sm" onClick={() => handleAddTicker(wl.id)} disabled={!tickerInput.trim()}>
                      Add
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => { setAddingTo(null); setTickerInput(""); }}>
                      Cancel
                    </Button>
                  </div>
                ) : (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => { setAddingTo(wl.id); setTickerInput(""); }}
                    className="text-xs h-7"
                  >
                    <svg className="w-3.5 h-3.5 mr-1" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
                    </svg>
                    Add Ticker
                  </Button>
                )
              )}
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}
