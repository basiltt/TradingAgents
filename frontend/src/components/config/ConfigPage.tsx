import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/api/client";
import { cn } from "@/lib/utils";

export function ConfigPage() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["config"],
    queryFn: ({ signal }) => apiClient.getConfig(signal),
    staleTime: 30_000,
  });

  return (
    <div className="space-y-6 max-w-5xl mx-auto pb-10">
      <div>
        <h1 className="text-2xl sm:text-3xl font-extrabold tracking-tight text-foreground">System Configuration</h1>
        <p className="text-xs text-muted-foreground mt-1.5 font-medium uppercase tracking-wider">
          Active configuration values, credential status, and environment overrides
        </p>
      </div>

      {isLoading ? (
        <div className="space-y-4">
          <div className="h-40 rounded-2xl bg-muted/20 animate-pulse border border-border/30" />
          <div className="h-32 rounded-2xl bg-muted/20 animate-pulse border border-border/30" />
        </div>
      ) : isError || !data ? (
        <div className="glass-card border border-destructive/20 bg-destructive/5 rounded-2xl p-6 flex items-center gap-4">
          <div className="w-11 h-11 rounded-xl bg-destructive/10 flex items-center justify-center shrink-0 border border-destructive/15">
            <svg className="w-5 h-5 text-destructive" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <div>
            <p className="text-xs font-bold uppercase tracking-wider text-destructive">Error: Failed to fetch environment configuration</p>
            <p className="text-[11px] text-muted-foreground mt-0.5">Check connection state to the pipeline engine gateway.</p>
          </div>
        </div>
      ) : (
        <>
          {/* Resolved Config */}
          <div className="glass-card border border-border/50 bg-card/65 rounded-2xl shadow-sm overflow-hidden">
            <div className="px-6 py-4 flex items-center justify-between gap-4 border-b border-border/30 bg-muted/20">
              <div className="flex items-center gap-2.5">
                <svg className="w-4 h-4 text-primary" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                  <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                </svg>
                <div>
                  <h4 className="text-xs font-bold uppercase tracking-wider text-foreground">Resolved Environment</h4>
                  <p className="text-[10px] text-muted-foreground font-medium uppercase tracking-wider mt-0.5">Active variables inside run context</p>
                </div>
              </div>
              <span className="text-[9px] font-black uppercase tracking-wider px-2.5 py-0.75 rounded-full border border-border/30 bg-muted/40 text-muted-foreground">
                {Object.keys(data.resolved).length} Parameters
              </span>
            </div>

            <div className="divide-y divide-border/20 max-h-[500px] overflow-y-auto no-scrollbar">
              {Object.entries(data.resolved).map(([key, value], i) => (
                <div
                  key={key}
                  className={cn(
                    "flex flex-col sm:flex-row sm:items-center gap-1 sm:gap-6 px-6 py-3.5 text-xs transition-colors hover:bg-muted/15",
                    i % 2 === 0 ? "bg-muted/5" : ""
                  )}
                >
                  <span className="font-mono text-muted-foreground/80 sm:w-64 sm:shrink-0 font-bold select-all">{key}</span>
                  <span className="font-mono break-all font-semibold text-foreground/90 flex-1">
                    {String(value) === "***" ? (
                      <span className="text-[10px] font-bold uppercase tracking-wider text-amber-500 bg-amber-500/10 px-2 py-0.5 rounded border border-amber-500/15">Masked Credentials</span>
                    ) : (
                      String(value)
                    )}
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* Bybit Credentials Info */}
          <div className="glass-card border border-border/50 bg-card/65 rounded-2xl shadow-sm overflow-hidden p-6 space-y-4">
            <div className="flex items-center gap-2.5">
              <div className="w-8 h-8 rounded-lg bg-amber-500/10 flex items-center justify-center border border-amber-500/20">
                <svg className="w-4 h-4 text-amber-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
              </div>
              <div>
                <h4 className="text-xs font-bold uppercase tracking-wider text-foreground">Crypto Futures Exchange Integration</h4>
                <p className="text-[10px] text-muted-foreground font-medium uppercase tracking-wider mt-0.5">Bybit connectivity details</p>
              </div>
            </div>

            <div className="text-xs space-y-3 pl-10.5">
              <p className="text-muted-foreground leading-relaxed max-w-2xl font-medium">
                Analysis utilizes the Bybit public endpoints to stream real-time price feeds. Private keys are not mandatory unless live routing of execution actions is requested.
              </p>
              <div className="flex items-center gap-3">
                <span className="font-mono text-xs font-bold text-muted-foreground/80 w-36 select-all">BYBIT_API_KEY</span>
                <span className="text-[9px] font-black uppercase tracking-wider px-2 py-0.5 rounded bg-muted/40 text-muted-foreground border border-border/20">Optional Public Mode</span>
              </div>
              <p className="text-[10px] text-muted-foreground/75 leading-relaxed font-semibold">
                Set <code className="font-mono bg-muted/60 text-foreground px-1.5 py-0.5 rounded border border-border/10">BYBIT_API_KEY</code> and <code className="font-mono bg-muted/60 text-foreground px-1.5 py-0.5 rounded border border-border/10">BYBIT_API_SECRET</code> environment flags to unlock private portfolios.
              </p>
            </div>
          </div>

          {Object.keys(data.overrides).length > 0 && (
            <div className="glass-card border border-border/50 bg-card/65 rounded-2xl shadow-sm overflow-hidden">
              <div className="px-6 py-4 flex items-center justify-between gap-4 border-b border-border/30 bg-muted/20">
                <div className="flex items-center gap-2.5">
                  <svg className="w-4 h-4 text-emerald-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                  </svg>
                  <div>
                    <h4 className="text-xs font-bold uppercase tracking-wider text-foreground">Active Overrides</h4>
                    <p className="text-[10px] text-muted-foreground font-medium uppercase tracking-wider mt-0.5">Parameters shadowing default definitions</p>
                  </div>
                </div>
                <span className="text-[9px] font-black uppercase tracking-wider px-2.5 py-0.75 rounded-full border border-emerald-500/20 bg-emerald-500/10 text-emerald-500 shadow-sm">
                  {Object.keys(data.overrides).length} overrides active
                </span>
              </div>
              <div className="divide-y divide-border/20">
                {Object.entries(data.overrides).map(([key, value], i) => (
                  <div
                    key={key}
                    className={cn(
                      "flex flex-col sm:flex-row sm:items-center gap-1 sm:gap-6 px-6 py-3.5 text-xs transition-colors hover:bg-muted/15",
                      i % 2 === 0 ? "bg-muted/5" : ""
                    )}
                  >
                    <span className="font-mono text-muted-foreground/80 sm:w-64 sm:shrink-0 font-bold select-all">{key}</span>
                    <span className="font-mono break-all font-black text-emerald-500">{String(value)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
