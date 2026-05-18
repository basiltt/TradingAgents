import { useState, useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  cyclesApi,
  accountsApi,
  type CreateCycleRequest,
  type DryRunResponse,
  ApiError,
} from "@/api/client";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  scanId: string;
  scanLabel: string;
  onSuccess?: () => void;
}

const STORAGE_KEY = "tradingagents_cycle_settings";

interface CycleSettings {
  accountId: string;
  direction: "straight" | "reverse";
  leverage: string;
  capitalPct: string;
  tpPct: string;
  slPct: string;
  minScore: string;
  minConfidence: "none" | "low" | "moderate" | "high";
  signalFilter: "buy" | "sell" | "both";
  maxTrades: string;
  targetType: "percentage" | "amount";
  targetValue: string;
  maxDrawdownPct: string;
}

const DEFAULTS: CycleSettings = {
  accountId: "",
  direction: "straight",
  leverage: "10",
  capitalPct: "5",
  tpPct: "",
  slPct: "",
  minScore: "3",
  minConfidence: "moderate",
  signalFilter: "both",
  maxTrades: "5",
  targetType: "percentage",
  targetValue: "10",
  maxDrawdownPct: "5",
};

function loadSettings(): CycleSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return { ...DEFAULTS, ...JSON.parse(raw) };
  } catch {
    // ignored – corrupt localStorage is fine, fall through to defaults
  }
  return { ...DEFAULTS };
}

function saveSettings(s: CycleSettings) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(s));
}

export function TradingCycleDialog({ open, onOpenChange, scanId, scanLabel, onSuccess }: Props) {
  const [settings, setSettings] = useState<CycleSettings>(loadSettings);
  const [step, setStep] = useState<"config" | "confirm">("config");
  const [dryRunResult, setDryRunResult] = useState<DryRunResponse | null>(null);
  const queryClient = useQueryClient();

  const { data: accounts } = useQuery({
    queryKey: ["accounts"],
    queryFn: ({ signal }) => accountsApi.list(undefined, signal),
    enabled: open,
  });

  const { data: preview } = useQuery({
    queryKey: ["filter-preview", scanId, settings.minScore, settings.minConfidence, settings.signalFilter],
    queryFn: ({ signal }) =>
      cyclesApi.filterPreview(scanId, {
        min_score: Number(settings.minScore),
        min_confidence: settings.minConfidence,
        signal_filter: settings.signalFilter,
      }, signal),
    enabled: open && !!scanId,
  });

  const dryRunMutation = useMutation({
    mutationFn: (data: CreateCycleRequest) => cyclesApi.dryRun(data),
    onSuccess: (result) => {
      setDryRunResult(result);
      setStep("confirm");
    },
    onError: (err: Error) => {
      toast.error(err instanceof ApiError ? err.detail : err.message);
    },
  });

  const createMutation = useMutation({
    mutationFn: (data: CreateCycleRequest) => cyclesApi.create(data),
    onSuccess: () => {
      toast.success("Trading cycle started");
      queryClient.invalidateQueries({ queryKey: ["cycles"] });
      onOpenChange(false);
      setStep("config");
      onSuccess?.();
    },
    onError: (err: Error) => {
      toast.error(err instanceof ApiError ? err.detail : err.message);
    },
  });

  const update = useCallback((patch: Partial<CycleSettings>) => {
    setSettings((prev) => {
      const next = { ...prev, ...patch };
      saveSettings(next);
      return next;
    });
  }, []);

  const handleOpenChange = useCallback((next: boolean) => {
    if (next) setStep("config");
    onOpenChange(next);
  }, [onOpenChange]);

  function buildRequest(): CreateCycleRequest {
    return {
      account_id: settings.accountId,
      scan_id: scanId,
      trade_direction: settings.direction,
      leverage: Number(settings.leverage),
      capital_pct: Number(settings.capitalPct),
      take_profit_pct: settings.tpPct ? Number(settings.tpPct) : undefined,
      stop_loss_pct: settings.slPct ? Number(settings.slPct) : undefined,
      min_score: Number(settings.minScore),
      min_confidence: settings.minConfidence,
      signal_filter: settings.signalFilter,
      max_trades: Number(settings.maxTrades),
      target_type: settings.targetType,
      target_value: Number(settings.targetValue),
      max_drawdown_pct: Number(settings.maxDrawdownPct),
    };
  }

  const canSubmit = settings.accountId && Number(settings.leverage) > 0 && Number(settings.targetValue) > 0;

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-w-lg max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {step === "config" ? "Start Trading Cycle" : "Confirm Trading Cycle"}
          </DialogTitle>
        </DialogHeader>

        {step === "config" ? (
          <div className="space-y-4">
            <p className="text-sm text-muted-foreground">Scan: {scanLabel}</p>

            <div className="space-y-2">
              <Label htmlFor="cycle-account">Account</Label>
              <Select value={settings.accountId} onValueChange={(v) => update({ accountId: v ?? "" })}>
                <SelectTrigger id="cycle-account">
                  <SelectValue placeholder="Select account" />
                </SelectTrigger>
                <SelectContent>
                  {accounts?.filter((a) => a.is_active).map((a) => (
                    <SelectItem key={a.id} value={a.id}>{a.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-2">
                <Label htmlFor="cycle-direction">Direction</Label>
                <Select value={settings.direction} onValueChange={(v) => update({ direction: v as "straight" | "reverse" })}>
                  <SelectTrigger id="cycle-direction"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="straight">Straight</SelectItem>
                    <SelectItem value="reverse">Reverse</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="cycle-leverage">Leverage</Label>
                <Input id="cycle-leverage" type="number" min={1} max={125} value={settings.leverage} onChange={(e) => update({ leverage: e.target.value })} />
              </div>
            </div>

            <div className="grid grid-cols-3 gap-3">
              <div className="space-y-2">
                <Label htmlFor="cycle-capital">Capital %</Label>
                <Input id="cycle-capital" type="number" min={0.1} max={100} step={0.1} value={settings.capitalPct} onChange={(e) => update({ capitalPct: e.target.value })} />
              </div>
              <div className="space-y-2">
                <Label htmlFor="cycle-tp">TP %</Label>
                <Input id="cycle-tp" type="number" min={0} max={1000} placeholder="Optional" value={settings.tpPct} onChange={(e) => update({ tpPct: e.target.value })} />
              </div>
              <div className="space-y-2">
                <Label htmlFor="cycle-sl">SL %</Label>
                <Input id="cycle-sl" type="number" min={0} max={1000} placeholder="Optional" value={settings.slPct} onChange={(e) => update({ slPct: e.target.value })} />
              </div>
            </div>

            <div className="border-t pt-3 space-y-3">
              <p className="text-sm font-medium">Scan Filters</p>
              <div className="grid grid-cols-3 gap-3">
                <div className="space-y-2">
                  <Label htmlFor="cycle-score">Min Score</Label>
                  <Input id="cycle-score" type="number" min={-10} max={10} value={settings.minScore} onChange={(e) => update({ minScore: e.target.value })} />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="cycle-confidence">Confidence</Label>
                  <Select value={settings.minConfidence} onValueChange={(v) => update({ minConfidence: v as CycleSettings["minConfidence"] })}>
                    <SelectTrigger id="cycle-confidence"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="none">None</SelectItem>
                      <SelectItem value="low">Low</SelectItem>
                      <SelectItem value="moderate">Moderate</SelectItem>
                      <SelectItem value="high">High</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="cycle-signal">Signal</Label>
                  <Select value={settings.signalFilter} onValueChange={(v) => update({ signalFilter: v as CycleSettings["signalFilter"] })}>
                    <SelectTrigger id="cycle-signal"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="both">Both</SelectItem>
                      <SelectItem value="buy">Buy</SelectItem>
                      <SelectItem value="sell">Sell</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>
              {preview && (
                <p className="text-xs text-muted-foreground">
                  {preview.qualifying_count} qualifying symbols
                  {preview.direction_breakdown.buy ? ` (${preview.direction_breakdown.buy} buy` : ""}
                  {preview.direction_breakdown.sell ? `, ${preview.direction_breakdown.sell} sell` : ""}
                  {preview.qualifying_count > 0 ? ")" : ""}
                </p>
              )}
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-2">
                <Label htmlFor="cycle-max-trades">Max Trades</Label>
                <Input id="cycle-max-trades" type="number" min={1} max={20} value={settings.maxTrades} onChange={(e) => update({ maxTrades: e.target.value })} />
              </div>
              <div className="space-y-2">
                <Label htmlFor="cycle-drawdown">Max Drawdown %</Label>
                <Input id="cycle-drawdown" type="number" min={0.1} max={100} step={0.1} value={settings.maxDrawdownPct} onChange={(e) => update({ maxDrawdownPct: e.target.value })} />
              </div>
            </div>

            <div className="border-t pt-3 space-y-3">
              <p className="text-sm font-medium">Target Goal</p>
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-2">
                  <Label htmlFor="cycle-target-type">Type</Label>
                  <Select value={settings.targetType} onValueChange={(v) => update({ targetType: v as "percentage" | "amount" })}>
                    <SelectTrigger id="cycle-target-type"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="percentage">Percentage</SelectItem>
                      <SelectItem value="amount">Fixed Amount</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="cycle-target-value">
                    {settings.targetType === "percentage" ? "Target %" : "Target $"}
                  </Label>
                  <Input id="cycle-target-value" type="number" min={0.1} step={0.1} value={settings.targetValue} onChange={(e) => update({ targetValue: e.target.value })} />
                </div>
              </div>
            </div>

            <DialogFooter>
              <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
              <Button
                disabled={!canSubmit || dryRunMutation.isPending}
                onClick={() => dryRunMutation.mutate(buildRequest())}
              >
                {dryRunMutation.isPending ? "Previewing..." : "Preview & Confirm"}
              </Button>
            </DialogFooter>
          </div>
        ) : (
          <div className="space-y-4">
            {dryRunResult && (
              <>
                <div className="rounded-lg bg-muted p-3 text-sm space-y-1">
                  <p>Current Equity: <strong>${dryRunResult.current_equity.toFixed(2)}</strong></p>
                  <p>Estimated Trades: <strong>{dryRunResult.estimated_trades}</strong></p>
                  <p>Capital per Trade: <strong>${dryRunResult.estimated_capital_per_trade.toFixed(2)}</strong></p>
                  <p>Total Capital: <strong>{dryRunResult.total_capital_pct.toFixed(1)}%</strong></p>
                  <p>Target (BALANCE_ABOVE): <strong>${dryRunResult.balance_above_threshold.toFixed(2)}</strong></p>
                  <p>Drawdown (BALANCE_BELOW): <strong>${dryRunResult.balance_below_threshold.toFixed(2)}</strong></p>
                </div>
                {dryRunResult.qualifying_symbols.length > 0 && (
                  <div>
                    <p className="text-sm font-medium mb-1">Qualifying Symbols:</p>
                    <div className="flex flex-wrap gap-1 max-h-24 overflow-y-auto">
                      {dryRunResult.qualifying_symbols.map((s) => (
                        <span key={s} className="px-2 py-0.5 rounded bg-muted text-xs">{s}</span>
                      ))}
                    </div>
                  </div>
                )}
                {dryRunResult.warnings.length > 0 && (
                  <div className="rounded-lg border border-yellow-500/30 bg-yellow-500/10 p-3">
                    <p className="text-sm font-medium text-yellow-600 mb-1">Warnings</p>
                    <ul className="text-xs space-y-1 text-yellow-700">
                      {dryRunResult.warnings.map((w, i) => <li key={i}>{w}</li>)}
                    </ul>
                  </div>
                )}
              </>
            )}
            <DialogFooter>
              <Button variant="outline" onClick={() => setStep("config")}>Back</Button>
              <Button
                disabled={createMutation.isPending}
                onClick={() => createMutation.mutate(buildRequest())}
              >
                {createMutation.isPending ? "Starting..." : "Start Cycle"}
              </Button>
            </DialogFooter>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
