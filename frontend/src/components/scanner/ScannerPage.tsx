import { useState, useEffect } from "react";
import { Link } from "@tanstack/react-router";
import { useQuery, useMutation } from "@tanstack/react-query";
import { apiClient, type ScanRequest, type ScanStatus, type ScanResultItem, type CryptoInterval } from "@/api/client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

const PROVIDERS = ["openai", "anthropic", "google", "deepseek", "xai", "qwen", "glm", "openrouter", "azure", "ollama"] as const;
const CRYPTO_ANALYSTS = ["crypto_technical", "crypto_derivatives", "crypto_news", "crypto_fundamentals", "crypto_social"] as const;
const CRYPTO_INTERVALS: { value: CryptoInterval; label: string }[] = [
  { value: "15", label: "15 min" },
  { value: "60", label: "1 hour" },
  { value: "240", label: "4 hours" },
  { value: "D", label: "1 day" },
];

const STORAGE_KEY = "tradingagents_settings";

function getToday(): string {
  return new Date().toISOString().slice(0, 10);
}

function loadSavedSettings(): Record<string, string> {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "{}");
  } catch {
    return {};
  }
}

const DIRECTION_CONFIG: Record<string, { label: string; color: string; bg: string }> = {
  buy: { label: "BUY", color: "text-emerald-400", bg: "bg-emerald-500/10" },
  sell: { label: "SELL", color: "text-red-400", bg: "bg-red-500/10" },
  hold: { label: "HOLD", color: "text-amber-400", bg: "bg-amber-500/10" },
  unknown: { label: "—", color: "text-muted-foreground", bg: "bg-muted" },
};

function ScoreBar({ score }: { score: number }) {
  const abs = Math.min(Math.abs(score), 3);
  const pct = (abs / 3) * 100;
  const color = score > 0 ? "bg-emerald-500" : score < 0 ? "bg-red-500" : "bg-muted-foreground";
  return (
    <div className="flex items-center gap-2 w-24">
      <div className="flex-1 h-2 rounded-full bg-muted overflow-hidden">
        <div className={cn("h-full rounded-full transition-all", color)} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs font-mono w-6 text-right">{score > 0 ? "+" : ""}{score}</span>
    </div>
  );
}

export function ScannerPage() {
  const [saved] = useState(loadSavedSettings);
  const [analysisDate, setAnalysisDate] = useState(getToday());
  const [provider, setProvider] = useState(saved.provider ?? "openai");
  const [deepModel, setDeepModel] = useState(saved.deep_think_llm ?? "");
  const [quickModel, setQuickModel] = useState(saved.quick_think_llm ?? "");
  const [interval, setInterval] = useState<CryptoInterval>("D");
  const [analysts, setAnalysts] = useState<string[]>([...CRYPTO_ANALYSTS]);
  const [activeScanId, setActiveScanId] = useState<string | null>(null);

  const startMutation = useMutation({
    mutationFn: (body: ScanRequest) => apiClient.startScan(body),
    onSuccess: (data) => setActiveScanId(data.scan_id),
  });

  const cancelMutation = useMutation({
    mutationFn: (scanId: string) => apiClient.cancelScan(scanId),
  });

  const scanQuery = useQuery({
    queryKey: ["scan", activeScanId],
    queryFn: ({ signal }) => apiClient.getScan(activeScanId!, signal),
    enabled: !!activeScanId,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "running" ? 3000 : false;
    },
  });

  const scan: ScanStatus | undefined = scanQuery.data;
  const isRunning = scan?.status === "running";
  const isDone = scan?.status === "completed" || scan?.status === "cancelled" || scan?.status === "failed";

  const handleStart = () => {
    const body: ScanRequest = {
      analysis_date: analysisDate,
      asset_type: "crypto",
      interval,
      provider: provider || undefined,
      deep_think_llm: deepModel || undefined,
      quick_think_llm: quickModel || undefined,
      analysts,
      research_depth: 1,
    };
    startMutation.mutate(body);
  };

  const toggleAnalyst = (a: string) => {
    setAnalysts((prev) => prev.includes(a) ? prev.filter((x) => x !== a) : [...prev, a]);
  };

  const buyResults = (scan?.results ?? []).filter((r) => r.direction === "buy").sort((a, b) => b.score - a.score);
  const sellResults = (scan?.results ?? []).filter((r) => r.direction === "sell").sort((a, b) => a.score - b.score);
  const holdResults = (scan?.results ?? []).filter((r) => r.direction === "hold" || r.direction === "unknown");

  return (
    <div className="space-y-6 max-w-5xl mx-auto py-4">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Market Scanner</h1>
        <p className="text-muted-foreground mt-1">
          Scan all available Bybit USDT perpetual futures in batches of 10 and find the best trading opportunities.
        </p>
      </div>

      {/* Config */}
      {!activeScanId && (
        <Card>
          <CardHeader className="pb-4">
            <CardTitle className="text-base">Scan Configuration</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-1.5">
                <Label className="text-xs">Analysis Date</Label>
                <Input type="date" value={analysisDate} onChange={(e) => setAnalysisDate(e.target.value)} />
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs">Interval</Label>
                <Select value={interval} onValueChange={(v) => setInterval(v as CryptoInterval)}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {CRYPTO_INTERVALS.map((i) => (
                      <SelectItem key={i.value} value={i.value}>{i.label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs">LLM Provider</Label>
                <Select value={provider} onValueChange={setProvider}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {PROVIDERS.map((p) => (
                      <SelectItem key={p} value={p}>{p}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs">Deep Think Model</Label>
                <Input value={deepModel} onChange={(e) => setDeepModel(e.target.value)} placeholder="e.g. gpt-4o" />
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs">Quick Think Model</Label>
                <Input value={quickModel} onChange={(e) => setQuickModel(e.target.value)} placeholder="e.g. gpt-4o-mini" />
              </div>
            </div>

            <div className="space-y-1.5">
              <Label className="text-xs">Analysts</Label>
              <div className="flex flex-wrap gap-2">
                {CRYPTO_ANALYSTS.map((a) => (
                  <button
                    key={a}
                    type="button"
                    onClick={() => toggleAnalyst(a)}
                    className={cn(
                      "px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors",
                      analysts.includes(a)
                        ? "bg-primary text-primary-foreground border-primary"
                        : "bg-muted text-muted-foreground border-border hover:border-primary/50",
                    )}
                  >
                    {a.replace("crypto_", "").replace("_", " ")}
                  </button>
                ))}
              </div>
            </div>

            <Button onClick={handleStart} disabled={startMutation.isPending || analysts.length === 0} className="w-full">
              {startMutation.isPending ? "Starting..." : "Start Full Market Scan"}
            </Button>
            {startMutation.isError && (
              <p className="text-xs text-destructive">
                Failed to start scan: {(startMutation.error as Error).message}
              </p>
            )}
          </CardContent>
        </Card>
      )}

      {/* Progress */}
      {scan && (
        <Card>
          <CardContent className="py-5 space-y-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <h3 className="font-semibold">
                  {isRunning ? "Scanning..." : scan.status === "completed" ? "Scan Complete" : "Scan Cancelled"}
                </h3>
                <Badge variant={isRunning ? "default" : scan.status === "completed" ? "secondary" : "outline"}>
                  {scan.status}
                </Badge>
              </div>
              <div className="flex items-center gap-2">
                {isRunning && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => cancelMutation.mutate(scan.scan_id)}
                    disabled={cancelMutation.isPending}
                    className="text-xs"
                  >
                    Cancel Scan
                  </Button>
                )}
                {isDone && (
                  <Button size="sm" variant="outline" onClick={() => setActiveScanId(null)} className="text-xs">
                    New Scan
                  </Button>
                )}
              </div>
            </div>

            {/* Progress bar */}
            <div className="space-y-2">
              <div className="flex justify-between text-xs text-muted-foreground">
                <span>Batch {scan.current_batch} of {scan.total_batches}</span>
                <span>{scan.completed + scan.failed} / {scan.total} symbols</span>
              </div>
              <div className="h-3 rounded-full bg-muted overflow-hidden">
                <div
                  className="h-full rounded-full bg-primary transition-all duration-500"
                  style={{ width: `${scan.total > 0 ? ((scan.completed + scan.failed) / scan.total) * 100 : 0}%` }}
                />
              </div>
              <div className="flex gap-4 text-xs">
                <span className="text-emerald-500">{scan.completed} completed</span>
                {scan.failed > 0 && <span className="text-destructive">{scan.failed} failed</span>}
              </div>
            </div>

            {/* Current batch tickers */}
            {isRunning && scan.current_tickers.length > 0 && (
              <div className="space-y-1.5">
                <p className="text-xs text-muted-foreground">Currently analyzing:</p>
                <div className="flex flex-wrap gap-1.5">
                  {scan.current_tickers.map((t) => (
                    <Badge key={t} variant="outline" className="text-xs font-mono gap-1">
                      <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
                      {t}
                    </Badge>
                  ))}
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Results */}
      {scan && scan.results.length > 0 && (
        <>
          {/* Buy signals */}
          {buyResults.length > 0 && (
            <Card className="border-emerald-500/20">
              <CardHeader className="pb-3">
                <CardTitle className="text-base flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-emerald-500" />
                  Buy Signals ({buyResults.length})
                </CardTitle>
              </CardHeader>
              <CardContent className="p-0">
                <ResultsTable results={buyResults} />
              </CardContent>
            </Card>
          )}

          {/* Sell signals */}
          {sellResults.length > 0 && (
            <Card className="border-red-500/20">
              <CardHeader className="pb-3">
                <CardTitle className="text-base flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-red-500" />
                  Sell Signals ({sellResults.length})
                </CardTitle>
              </CardHeader>
              <CardContent className="p-0">
                <ResultsTable results={sellResults} />
              </CardContent>
            </Card>
          )}

          {/* Hold / Unknown */}
          {holdResults.length > 0 && (
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-amber-500" />
                  Hold / Neutral ({holdResults.length})
                </CardTitle>
              </CardHeader>
              <CardContent className="p-0">
                <ResultsTable results={holdResults} />
              </CardContent>
            </Card>
          )}
        </>
      )}
    </div>
  );
}

function ResultsTable({ results }: { results: ScanResultItem[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border/50 text-xs text-muted-foreground">
            <th className="text-left px-4 py-2.5 font-medium">#</th>
            <th className="text-left px-4 py-2.5 font-medium">Symbol</th>
            <th className="text-left px-4 py-2.5 font-medium">Signal</th>
            <th className="text-left px-4 py-2.5 font-medium">Confidence</th>
            <th className="text-left px-4 py-2.5 font-medium">Strength</th>
            <th className="text-left px-4 py-2.5 font-medium">Status</th>
            <th className="text-right px-4 py-2.5 font-medium"></th>
          </tr>
        </thead>
        <tbody>
          {results.map((r, i) => {
            const dir = DIRECTION_CONFIG[r.direction] ?? DIRECTION_CONFIG.unknown;
            return (
              <tr key={r.ticker} className="border-b border-border/30 hover:bg-muted/30 transition-colors">
                <td className="px-4 py-3 text-muted-foreground font-mono text-xs">{i + 1}</td>
                <td className="px-4 py-3 font-mono font-semibold">{r.ticker}</td>
                <td className="px-4 py-3">
                  <span className={cn("px-2 py-0.5 rounded text-xs font-bold", dir.bg, dir.color)}>
                    {dir.label}
                  </span>
                </td>
                <td className="px-4 py-3 text-xs capitalize">{r.confidence}</td>
                <td className="px-4 py-3"><ScoreBar score={r.score} /></td>
                <td className="px-4 py-3">
                  <Badge variant={r.status === "completed" ? "secondary" : "destructive"} className="text-xs">
                    {r.status}
                  </Badge>
                </td>
                <td className="px-4 py-3 text-right">
                  {r.run_id && (
                    <Link
                      to="/analysis/$runId"
                      params={{ runId: r.run_id }}
                      className="text-xs text-primary hover:underline"
                    >
                      View
                    </Link>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
