import { useState, useCallback } from "react";
import { useNavigate } from "@tanstack/react-router";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
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
  agent_model_overrides?: Record<string, string>;
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
            agent_model_overrides: config.agent_model_overrides,
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
    <div className="glass-card border border-border/50 bg-card/65 rounded-2xl shadow-sm overflow-hidden p-6 space-y-5">
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center border border-primary/20">
            <svg className="w-4 h-4 text-primary" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.784-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z" />
            </svg>
          </div>
          <div>
            <h4 className="text-xs font-bold uppercase tracking-wider text-foreground">Custom Watchlists</h4>
            <p className="text-[10px] text-muted-foreground font-medium uppercase tracking-wider mt-0.5">Manage portfolios and batch analyze</p>
          </div>
        </div>
        {watchlists.length > 0 && (
          <span className="text-[9px] font-black uppercase tracking-wider px-2 py-0.5 rounded-full border border-border/30 bg-muted/40 text-muted-foreground">
            {watchlists.length} lists
          </span>
        )}
      </div>

      <div className="space-y-4">
        {/* Create new watchlist */}
        <div className="flex gap-2">
          <Input
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="New watchlist name..."
            className="flex-1 bg-background/50 border-border/40 focus:border-primary/50 text-xs rounded-xl h-9"
            onKeyDown={(e) => e.key === "Enter" && handleCreate()}
          />
          <Button
            onClick={handleCreate}
            disabled={!newName.trim()}
            size="sm"
            className="h-9 px-4 rounded-xl text-xs font-black uppercase tracking-wider transition-all active:scale-95 cursor-pointer"
          >
            Create
          </Button>
        </div>

        {watchlists.length === 0 && (
          <div className="text-center py-8 border border-dashed border-border/30 rounded-xl bg-muted/5">
            <p className="text-xs text-muted-foreground/80 font-medium">
              No watchlists yet. Create one to group your target tickers.
            </p>
          </div>
        )}

        {/* Watchlist items */}
        <div className="space-y-3">
          {watchlists.map((wl) => {
            const isBatching = batchState?.id === wl.id;
            return (
              <div key={wl.id} className="rounded-xl border border-border/40 p-4 space-y-3.5 bg-muted/10">
                {/* Header */}
                <div className="flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2">
                    <h5 className="font-bold text-xs text-foreground tracking-tight">{wl.name}</h5>
                    <span className="text-[9px] font-black uppercase tracking-wider px-1.5 py-0.5 rounded bg-muted/80 text-muted-foreground border border-border/20">
                      {wl.tickers.length}/10
                    </span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <Button
                      size="sm"
                      variant="default"
                      disabled={wl.tickers.length === 0 || !!batchState}
                      onClick={() => handleAnalyzeAll(wl.id, wl.tickers)}
                      className="text-[10px] font-black uppercase tracking-wider h-7.5 px-3 rounded-lg active:scale-95 transition-transform cursor-pointer"
                    >
                      {isBatching
                        ? `${batchState!.done}/${batchState!.total}...`
                        : `Analyze (${wl.tickers.length})`}
                    </Button>
                    <button
                      onClick={() => remove(wl.id)}
                      className="w-7.5 h-7.5 flex items-center justify-center rounded-lg hover:bg-destructive/10 text-muted-foreground hover:text-destructive transition-colors shrink-0 cursor-pointer border border-transparent hover:border-destructive/20"
                    >
                      <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                      </svg>
                    </button>
                  </div>
                </div>

                {/* Batch errors */}
                {isBatching && batchState!.errors.length > 0 && (
                  <p className="text-[10px] font-bold text-destructive">
                    Failed tickers: {batchState!.errors.join(", ")}
                  </p>
                )}

                {/* Ticker chips */}
                {wl.tickers.length > 0 && (
                  <div className="flex flex-wrap gap-1.5">
                    {wl.tickers.map((t) => (
                      <span
                        key={t}
                        className="text-[10px] font-bold font-mono tracking-tight bg-background border border-border/40 text-foreground px-2 py-0.5 rounded-lg flex items-center gap-1 shadow-sm transition-colors hover:border-border/60 hover:bg-muted/30"
                      >
                        {t}
                        <button
                          type="button"
                          onClick={() => removeTicker(wl.id, t)}
                          className="ml-0.5 rounded-full hover:bg-destructive/20 text-muted-foreground hover:text-destructive p-0.5 transition-colors cursor-pointer"
                        >
                          <svg className="w-2.5 h-2.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                            <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                          </svg>
                        </button>
                      </span>
                    ))}
                  </div>
                )}

                {/* Add ticker */}
                {wl.tickers.length < 10 && (
                  addingTo === wl.id ? (
                    <div className="flex gap-2 items-center">
                      {config.asset_type === "crypto" ? (
                        <div className="flex-1 min-w-0">
                          <Combobox
                            options={symbols}
                            value={tickerInput}
                            onChange={setTickerInput}
                            placeholder="Search asset..."
                            loading={symbolsLoading}
                            className="w-full bg-background border-border/40 focus:border-primary/50 text-xs rounded-xl h-8.5"
                          />
                        </div>
                      ) : (
                        <Input
                          value={tickerInput}
                          onChange={(e) => setTickerInput(e.target.value.toUpperCase())}
                          placeholder="Ticker..."
                          className="flex-1 bg-background border-border/40 focus:border-primary/50 text-xs rounded-xl h-8.5"
                          onKeyDown={(e) => e.key === "Enter" && handleAddTicker(wl.id)}
                        />
                      )}
                      <Button
                        size="sm"
                        onClick={() => handleAddTicker(wl.id)}
                        disabled={!tickerInput.trim()}
                        className="h-8.5 px-3 rounded-xl text-[10px] font-black uppercase tracking-wider cursor-pointer"
                      >
                        Add
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => { setAddingTo(null); setTickerInput(""); }}
                        className="h-8.5 px-3 rounded-xl text-[10px] font-black uppercase tracking-wider cursor-pointer hover:bg-muted"
                      >
                        Cancel
                      </Button>
                    </div>
                  ) : (
                    <button
                      onClick={() => { setAddingTo(wl.id); setTickerInput(""); }}
                      className="text-[10px] font-black uppercase tracking-wider h-8 w-full border border-dashed border-border/40 rounded-xl hover:border-border/60 hover:bg-muted/15 flex items-center justify-center gap-1.5 transition-colors cursor-pointer text-muted-foreground/80 hover:text-foreground"
                    >
                      <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
                      </svg>
                      Add Ticker to {wl.name}
                    </button>
                  )
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
