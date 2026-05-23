import { useState, useRef, useEffect, useCallback, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { accountsApi, ApiError, type TradingAccount, type PlaceTradeRequest } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { cn } from "@/lib/utils";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  symbol: string;
  signalDirection: "buy" | "sell";
  onTradeSuccess?: (symbol: string) => void;
}

type TradeDirection = "straight" | "reverse";

const STORAGE_KEY = "tradingagents_trade_settings";
const BASE_CAPITAL_KEY = "tradingagents_base_capital";

interface TradeSettings {
  accountId: string;
  direction: TradeDirection;
  leverage: string;
  tpPct: string;
  slPct: string;
  capitalPct: string;
}

interface BaseCapitalEntry {
  value: string;
  date: string;
}

const DEFAULT_SETTINGS: TradeSettings = {
  accountId: "",
  direction: "straight",
  leverage: "10",
  tpPct: "100",
  slPct: "50",
  capitalPct: "5",
};

const SIDE_TONES = {
  buy: {
    badge: "bg-[color-mix(in_oklch,var(--neu-success)_10%,var(--neu-surface-base))] text-[var(--neu-success)] border border-[color-mix(in_oklch,var(--neu-success)_20%,var(--neu-stroke-soft))] shadow-[var(--neu-shadow-pill)]",
    button: "border-none bg-[var(--neu-success)] text-white hover:brightness-110 shadow-[var(--neu-shadow-pill)] transition-all duration-150 cursor-pointer",
    text: "text-[var(--neu-success)]",
  },
  sell: {
    badge: "bg-[color-mix(in_oklch,var(--neu-danger)_10%,var(--neu-surface-base))] text-[var(--neu-danger)] border border-[color-mix(in_oklch,var(--neu-danger)_20%,var(--neu-stroke-soft))] shadow-[var(--neu-shadow-pill)]",
    button: "border-none bg-[var(--neu-danger)] text-white hover:brightness-110 shadow-[var(--neu-shadow-pill)] transition-all duration-150 cursor-pointer",
    text: "text-[var(--neu-danger)]",
  },
} as const;

function loadSettings(): TradeSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      return { ...DEFAULT_SETTINGS, ...parsed };
    }
  } catch { /* ignored */ }
  return { ...DEFAULT_SETTINGS };
}

function saveSettings(s: TradeSettings) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(s));
}

function getTodayKey(): string {
  return new Date().toISOString().slice(0, 10);
}

function loadBaseCapital(accountId: string): BaseCapitalEntry | null {
  try {
    const raw = localStorage.getItem(BASE_CAPITAL_KEY);
    if (raw) {
      const all = JSON.parse(raw) as Record<string, BaseCapitalEntry>;
      return all[accountId] || null;
    }
  } catch { /* ignored */ }
  return null;
}

function saveBaseCapital(accountId: string, value: string) {
  try {
    const raw = localStorage.getItem(BASE_CAPITAL_KEY);
    const all = raw ? JSON.parse(raw) : {};
    all[accountId] = { value, date: getTodayKey() };
    localStorage.setItem(BASE_CAPITAL_KEY, JSON.stringify(all));
  } catch { /* ignored */ }
}

function StatRow({
  label,
  value,
  className,
}: {
  label: string;
  value: ReactNode;
  className?: string;
}) {
  return (
    <div className="bg-[var(--neu-surface-muted)] shadow-[var(--neu-shadow-inset)] rounded-[var(--neu-radius-sm)] px-3.5 py-3 border-none">
      <div className="section-eyebrow text-[0.58rem] tracking-[0.24em] text-[var(--neu-text-muted)]">{label}</div>
      <div className={cn("mt-1.5 text-sm font-semibold text-[var(--neu-text-strong)]", className)}>{value}</div>
    </div>
  );
}

export function PlaceTradeDialog({ open, onOpenChange, symbol, signalDirection, onTradeSuccess }: Props) {
  const [settings, setSettings] = useState<TradeSettings>(loadSettings);
  const [baseCapital, setBaseCapital] = useState("");
  const [baseCapitalLoading, setBaseCapitalLoading] = useState(false);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<Record<string, string> | null>(null);
  const submittingRef = useRef(false);
  const initializedRef = useRef(false);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- reset trade confirmation when the symbol changes
    if (result) setResult(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbol]);

  const { data: accounts = [] } = useQuery({
    queryKey: ["accounts-list"],
    queryFn: ({ signal }) => accountsApi.list(undefined, signal),
    enabled: open,
  });

  useEffect(() => {
    if (accounts.length > 0 && settings.accountId) {
      const acc = accounts.find((a: TradingAccount) => a.id === settings.accountId);
      if (!acc || !acc.is_active) {
        // eslint-disable-next-line react-hooks/set-state-in-effect -- deselect invalid or inactive account after account refresh
        setSettings((prev) => {
          const next = { ...prev, accountId: "" };
          saveSettings(next);
          return next;
        });
        setBaseCapital("");
      }
    }
  }, [accounts, settings.accountId]);

  const update = useCallback((patch: Partial<TradeSettings>) => {
    setSettings((prev) => {
      const next = { ...prev, ...patch };
      saveSettings(next);
      return next;
    });
  }, []);

  const fetchAndSetBaseCapital = useCallback(async (accId: string, force: boolean) => {
    if (!accId) return;
    const existing = loadBaseCapital(accId);
    if (existing && existing.date === getTodayKey() && !force) {
      setBaseCapital(existing.value);
      return;
    }
    setBaseCapitalLoading(true);
    try {
      const wallet = await accountsApi.getWallet(accId);
      const balance = wallet.totalAvailableBalance || wallet.totalWalletBalance || "0";
      const rounded = parseFloat(balance).toFixed(2);
      setBaseCapital(rounded);
      saveBaseCapital(accId, rounded);
    } catch {
      if (existing) {
        setBaseCapital(existing.value);
      }
    } finally {
      setBaseCapitalLoading(false);
    }
  }, []);

  useEffect(() => {
    if (open && settings.accountId && !initializedRef.current) {
      initializedRef.current = true;
      fetchAndSetBaseCapital(settings.accountId, false);
    }
    if (!open) {
      initializedRef.current = false;
    }
  }, [open, settings.accountId, fetchAndSetBaseCapital]);

  useEffect(() => {
    if (!open) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !loading) {
        setResult(null);
        onOpenChange(false);
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [open, loading, onOpenChange]);

  const handleAccountChange = (accId: string) => {
    update({ accountId: accId });
    if (accId) {
      fetchAndSetBaseCapital(accId, false);
    } else {
      setBaseCapital("");
    }
  };

  if (!open) return null;

  const actualSide = settings.direction === "straight"
    ? signalDirection
    : (signalDirection === "buy" ? "sell" : "buy");

  const selectedAccount = accounts.find((acc: TradingAccount) => acc.id === settings.accountId);
  const leverageNum = parseInt(settings.leverage) || 0;
  const tpNum = parseFloat(settings.tpPct) || 0;
  const slNum = parseFloat(settings.slPct) || 0;
  const capitalPctNum = parseFloat(settings.capitalPct) || 0;
  const baseCapitalNum = parseFloat(baseCapital) || 0;

  const slActualNum = leverageNum > 0 ? slNum / leverageNum : 0;
  const tpActual = leverageNum > 0 ? (tpNum / leverageNum).toFixed(2) : "0";
  const slActual = leverageNum > 0 ? slActualNum.toFixed(2) : "0";
  const slExceedsPrice = slActualNum >= 100;
  const tpActualNum = leverageNum > 0 ? tpNum / leverageNum : 0;
  const tpExceedsPrice = actualSide === "sell" && tpActualNum >= 100;

  const usdtPerTrade = baseCapitalNum * capitalPctNum / 100;
  const notionalValue = usdtPerTrade * leverageNum;

  const isValid = settings.accountId && leverageNum >= 1 && leverageNum <= 125
    && tpNum > 0 && slNum > 0 && capitalPctNum > 0 && capitalPctNum <= 100 && baseCapitalNum > 0
    && !slExceedsPrice && !tpExceedsPrice;

  const handleSubmit = async () => {
    if (submittingRef.current || !isValid) return;
    submittingRef.current = true;
    setLoading(true);
    try {
      const payload: PlaceTradeRequest = {
        symbol,
        signal_direction: signalDirection,
        trade_direction: settings.direction,
        leverage: leverageNum,
        take_profit_pct: tpNum,
        stop_loss_pct: slNum,
        capital_pct: capitalPctNum,
        base_capital: baseCapitalNum,
      };
      const res = await accountsApi.placeTrade(settings.accountId, payload, AbortSignal.timeout(60_000));
      setResult({
        orderId: res.orderId,
        side: res.side,
        qty: res.qty,
        mark_price: res.mark_price,
        take_profit_price: res.take_profit_price,
        stop_loss_price: res.stop_loss_price,
        usdt_amount: res.usdt_amount,
        leverage: String(res.leverage),
        max_leverage: String(res.max_leverage),
      });
      const leverageNote = res.leverage < leverageNum ? ` (capped to ${res.leverage}x max)` : "";
      toast.success(`Trade placed: ${res.side} ${symbol}${leverageNote}`);
      onTradeSuccess?.(symbol);
    } catch (err: unknown) {
      let detail: string;
      if (err instanceof ApiError) {
        detail = err.detail;
      } else if (err instanceof DOMException && err.name === "TimeoutError") {
        detail = "Trade request timed out — check your positions manually";
      } else if (err instanceof DOMException && err.name === "AbortError") {
        detail = "Trade request was cancelled";
      } else {
        detail = err instanceof Error ? err.message : "Failed to place trade";
      }
      toast.error(detail);
    } finally {
      submittingRef.current = false;
      setLoading(false);
    }
  };

  const handleClose = () => {
    setResult(null);
    onOpenChange(false);
  };

  const sideTone = SIDE_TONES[actualSide];

  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen && !loading) handleClose();
      }}
    >
      <DialogContent className="max-w-[min(46rem,calc(100%-1.25rem))] gap-6 overflow-hidden border-none bg-[var(--neu-surface-base)] rounded-[var(--neu-radius-lg)] shadow-[var(--neu-shadow-float)] p-0">
        <DialogHeader className="page-hero relative overflow-hidden border-b border-[color:var(--neu-stroke-soft)] px-5 pb-5 pt-5 sm:px-6">
          <div className="relative flex flex-wrap items-start gap-4">
            <span className="gradient-hero glow-primary flex size-12 items-center justify-center rounded-[var(--neu-radius-md)] text-[var(--neu-accent-ink)] shadow-[var(--neu-shadow-pill)]">
              <svg className="size-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
              </svg>
            </span>
            <div className="min-w-0 flex-1 space-y-1">
              <div className="section-eyebrow text-[var(--neu-text-muted)]">Execution ticket</div>
              <DialogTitle>Place trade · {symbol}</DialogTitle>
              <DialogDescription>
                Confirm account routing, risk sizing, and directional intent from a cleaner high-contrast execution surface.
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

        <div className="space-y-5 px-5 pb-5 sm:px-6 sm:pb-6">
          {result ? (
            <div className="space-y-4 pt-1">
              <div className="rounded-[var(--neu-radius-md)] bg-[color-mix(in_oklch,var(--neu-success)_10%,var(--neu-surface-base))] border border-[color-mix(in_oklch,var(--neu-success)_20%,var(--neu-stroke-soft))] shadow-[var(--neu-shadow-pill)] px-4 py-4">
                <p className="text-sm font-semibold text-[var(--neu-success)]">Trade placed successfully</p>
                <p className="mt-1 text-[12px] leading-6 text-[var(--neu-text-muted)]">Order ID: {result.orderId}</p>
                {result.leverage !== String(leverageNum) ? (
                  <p className="mt-1 text-[12px] leading-6 text-[var(--neu-warning)]">Requested {leverageNum}x, capped to {result.leverage}x by account limits for {symbol}.</p>
                ) : null}
              </div>

              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                <StatRow label="Side" value={result.side} className={SIDE_TONES[result.side as "buy" | "sell"]?.text} />
                <StatRow label="Leverage" value={`${result.leverage}x`} />
                <StatRow label="Qty" value={result.qty} />
                <StatRow label="USDT" value={`$${parseFloat(result.usdt_amount).toFixed(2)}`} />
                <StatRow label="Entry" value={result.mark_price} />
                <StatRow label="Take profit" value={result.take_profit_price} className="text-[var(--neu-success)]" />
                <StatRow label="Stop loss" value={result.stop_loss_price} className="text-[var(--neu-danger)]" />
              </div>

              <DialogFooter className="pt-0">
                <Button onClick={handleClose}>Close</Button>
              </DialogFooter>
            </div>
          ) : (
            <>
              <div className="neu-surface-base neu-surface-raised rounded-[var(--neu-radius-md)] border-none shadow-[var(--shadow-card)] px-4 py-3.5">
                <div className="flex flex-wrap items-center gap-2.5">
                  <span className="section-eyebrow text-[0.6rem] text-[var(--neu-text-muted)]">Signal</span>
                  <span className={cn("inline-flex min-h-8 items-center rounded-full border px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.18em]", SIDE_TONES[signalDirection].badge)}>
                    {signalDirection}
                  </span>
                  <span className="text-[var(--neu-text-muted)]/70">→</span>
                  <span className="section-eyebrow text-[0.6rem] text-[var(--neu-text-muted)]">Trade</span>
                  <span className={cn("inline-flex min-h-8 items-center rounded-full border px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.18em]", sideTone.badge)}>
                    {actualSide}
                  </span>
                  {selectedAccount ? (
                    <Badge variant={selectedAccount.account_type === "live" ? "destructive" : "secondary"} className="ml-auto border border-border/50 px-3 py-1 text-[10px] tracking-[0.16em] uppercase">
                      {selectedAccount.account_type}
                    </Badge>
                  ) : null}
                </div>
              </div>

              <div className="grid gap-4 lg:grid-cols-[1.02fr_0.98fr]">
                <div className="neu-surface-base neu-surface-raised rounded-[var(--neu-radius-lg)] border-none shadow-[var(--shadow-card)] p-4 sm:p-5">
                  <div className="mb-4 flex items-center justify-between gap-3">
                    <div>
                      <div className="section-eyebrow text-[var(--neu-text-muted)]">Execution route</div>
                      <p className="mt-1 text-sm font-semibold text-[var(--neu-text-strong)]">Pick the account and trade direction.</p>
                    </div>
                  </div>

                  <div className="space-y-4">
                    <div>
                      <Label className="section-eyebrow text-[0.62rem] text-[var(--neu-text-muted)]">Account</Label>
                      <Select value={settings.accountId} onValueChange={(value) => handleAccountChange(value ?? "")}>
                        <SelectTrigger className="mt-2 w-full">
                          <SelectValue placeholder="Select account" />
                        </SelectTrigger>
                        <SelectContent>
                          {accounts.filter((acc: TradingAccount) => acc.is_active).map((acc: TradingAccount) => (
                            <SelectItem key={acc.id} value={acc.id}>
                              {acc.label} ({acc.account_type})
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>

                    {settings.accountId ? (
                      <div className="bg-[var(--neu-surface-muted)] shadow-[var(--neu-shadow-inset)] rounded-[var(--neu-radius-md)] px-4 py-3.5 border-none">
                        <div className="mb-2.5 flex items-center justify-between gap-2">
                          <Label className="section-eyebrow text-[0.62rem] text-[var(--neu-text-muted)]">Base capital (USDT)</Label>
                          <Button
                            type="button"
                            variant="ghost"
                            size="xs"
                            onClick={() => fetchAndSetBaseCapital(settings.accountId, true)}
                            disabled={baseCapitalLoading}
                            className="uppercase tracking-[0.16em]"
                          >
                            {baseCapitalLoading ? (
                              <span className="inline-flex items-center gap-1.5">
                                <span className="size-3 rounded-full border border-current border-t-transparent animate-spin" />
                                Syncing
                              </span>
                            ) : (
                              <span className="inline-flex items-center gap-1.5">
                                <svg className="size-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                                  <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                                </svg>
                                Sync balance
                              </span>
                            )}
                          </Button>
                        </div>
                        <Input
                          type="number"
                          value={baseCapital}
                          onChange={(e) => {
                            setBaseCapital(e.target.value);
                            if (settings.accountId && e.target.value) {
                              saveBaseCapital(settings.accountId, e.target.value);
                            }
                          }}
                          placeholder="0.00"
                        />
                        <p className="mt-2.5 text-[11px] leading-5 text-[var(--neu-text-muted)]">Captured from wallet balance daily. Sync when you need the live amount.</p>
                      </div>
                    ) : null}

                    <div>
                      <Label className="section-eyebrow text-[0.62rem] text-[var(--neu-text-muted)]">Direction</Label>
                      <div className="mt-2 grid grid-cols-2 gap-1.5 rounded-[var(--neu-radius-md)] bg-[var(--neu-surface-muted)] p-1 shadow-[var(--neu-shadow-inset)] border-none">
                        {(["straight", "reverse"] as const).map((direction) => (
                          <button
                            key={direction}
                            type="button"
                            onClick={() => update({ direction })}
                            className={cn(
                              "inline-flex min-h-11 items-center justify-center rounded-[var(--neu-radius-sm)] px-3 py-2 text-[11px] font-bold uppercase tracking-[0.16em] transition-all duration-200 border-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--neu-accent)]",
                              settings.direction === direction
                                ? "bg-[var(--neu-surface-base)] text-[var(--neu-text-strong)] shadow-[var(--neu-shadow-raised-soft)]"
                                : "text-[var(--neu-text-muted)] hover:text-[var(--neu-text-strong)] hover:bg-[color-mix(in_oklch,var(--neu-accent)_8%,var(--neu-surface-base))]",
                            )}
                          >
                            {direction}
                          </button>
                        ))}
                      </div>
                      <p className="mt-2.5 text-[11px] leading-5 text-[var(--neu-text-muted)]">
                        {settings.direction === "straight" ? "Trade follows the incoming signal direction." : "Trade flips the incoming signal for a contrarian entry."}
                      </p>
                    </div>
                  </div>
                </div>

                <div className="neu-surface-base neu-surface-raised rounded-[var(--neu-radius-lg)] border-none shadow-[var(--shadow-card)] p-4 sm:p-5">
                  <div className="mb-4">
                    <div className="section-eyebrow text-[var(--neu-text-muted)]">Risk model</div>
                    <p className="mt-1 text-sm font-semibold text-[var(--neu-text-strong)]">Tune leverage, position sizing, and exits.</p>
                  </div>

                  <div className="grid gap-4 sm:grid-cols-2">
                    <div>
                      <Label className="section-eyebrow text-[0.62rem] text-[var(--neu-text-muted)]">Leverage</Label>
                      <div className="mt-2 flex items-center gap-2">
                        <Input type="number" value={settings.leverage} onChange={(e) => update({ leverage: e.target.value })} min={1} max={125} className="h-11" />
                        <span className="text-sm text-[var(--neu-text-muted)]">x</span>
                      </div>
                    </div>
                    <div>
                      <Label className="section-eyebrow text-[0.62rem] text-[var(--neu-text-muted)]">Capital %</Label>
                      <div className="mt-2 flex items-center gap-2">
                        <Input type="number" value={settings.capitalPct} onChange={(e) => update({ capitalPct: e.target.value })} min={0.1} max={100} step={0.1} className="h-11" />
                        <span className="text-sm text-[var(--neu-text-muted)]">%</span>
                      </div>
                    </div>
                    <div>
                      <Label className="section-eyebrow text-[0.62rem] text-[var(--neu-text-muted)]">Take profit %</Label>
                      <Input type="number" value={settings.tpPct} onChange={(e) => update({ tpPct: e.target.value })} min={0.1} step={0.1} className="mt-2 h-11" />
                      <p className={cn("mt-2 text-[11px] leading-5", tpExceedsPrice ? "text-[var(--neu-danger)]" : "text-[var(--neu-text-muted)]")}>
                        {tpExceedsPrice ? "TP exceeds a 100% price move for a short." : `≈ ${tpActual}% price move`}
                      </p>
                    </div>
                    <div>
                      <Label className="section-eyebrow text-[0.62rem] text-[var(--neu-text-muted)]">Stop loss %</Label>
                      <Input type="number" value={settings.slPct} onChange={(e) => update({ slPct: e.target.value })} min={0.1} step={0.1} className="mt-2 h-11" />
                      <p className={cn("mt-2 text-[11px] leading-5", slExceedsPrice ? "text-[var(--neu-danger)]" : "text-[var(--neu-text-muted)]")}>
                        {slExceedsPrice ? "SL exceeds a 100% price move." : `≈ ${slActual}% price move`}
                      </p>
                    </div>
                  </div>

                  {baseCapitalNum > 0 && capitalPctNum > 0 ? (
                    <div className="mt-4 grid gap-3 sm:grid-cols-2">
                      <StatRow label="USDT per trade" value={`$${usdtPerTrade.toFixed(2)}`} />
                      <StatRow label={`Notional (${leverageNum}x)`} value={`$${notionalValue.toFixed(2)}`} />
                    </div>
                  ) : null}
                </div>
              </div>

              <DialogFooter>
                <Button variant="outline" onClick={handleClose} disabled={loading}>
                  Cancel
                </Button>
                <Button
                  onClick={handleSubmit}
                  disabled={!isValid || loading}
                  className={cn("border-none", sideTone.button)}
                >
                  {loading ? (
                    <span className="inline-flex items-center gap-2">
                      <span className="size-3.5 rounded-full border border-current border-t-transparent animate-spin" />
                      Routing trade
                    </span>
                  ) : (
                    `${actualSide === "buy" ? "Buy" : "Sell"} ${symbol}`
                  )}
                </Button>
              </DialogFooter>
            </>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
