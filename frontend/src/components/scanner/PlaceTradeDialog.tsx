import { useState, useRef, useEffect, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { accountsApi, ApiError, type TradingAccount, type PlaceTradeRequest } from "@/api/client";

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

function loadSettings(): TradeSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      return { ...DEFAULT_SETTINGS, ...parsed };
    }
  } catch {}
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
  } catch {}
  return null;
}

function saveBaseCapital(accountId: string, value: string) {
  try {
    const raw = localStorage.getItem(BASE_CAPITAL_KEY);
    const all = raw ? JSON.parse(raw) : {};
    all[accountId] = { value, date: getTodayKey() };
    localStorage.setItem(BASE_CAPITAL_KEY, JSON.stringify(all));
  } catch {}
}

export function PlaceTradeDialog({ open, onOpenChange, symbol, signalDirection, onTradeSuccess }: Props) {
  const [settings, setSettings] = useState<TradeSettings>(loadSettings);
  const [baseCapital, setBaseCapital] = useState("");
  const [baseCapitalLoading, setBaseCapitalLoading] = useState(false);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<Record<string, string> | null>(null);
  const submittingRef = useRef(false);
  const initializedRef = useRef(false);
  const prevSymbolRef = useRef(symbol);

  if (prevSymbolRef.current !== symbol) {
    prevSymbolRef.current = symbol;
    if (result) setResult(null);
  }

  const { data: accounts = [] } = useQuery({
    queryKey: ["accounts-list"],
    queryFn: ({ signal }) => accountsApi.list(undefined, signal),
    enabled: open,
  });

  useEffect(() => {
    if (accounts.length > 0 && settings.accountId) {
      const acc = accounts.find((a: TradingAccount) => a.id === settings.accountId);
      if (!acc || !acc.is_active) {
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

  const inputClass = "w-full px-3 py-2 rounded-lg bg-muted/50 text-sm border border-border focus:ring-1 focus:ring-primary/50 outline-none";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={() => !loading && handleClose()} />
      <div className="relative bg-card border rounded-xl shadow-2xl p-6 max-w-md w-full mx-4 space-y-4 max-h-[90vh] overflow-y-auto">
        <h3 className="text-lg font-bold flex items-center gap-2">
          <svg className="w-5 h-5 text-primary" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
          </svg>
          Place Trade — {symbol}
        </h3>

        {result ? (
          <div className="space-y-3">
            <div className="p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/20">
              <p className="text-sm font-medium text-emerald-400">Trade placed successfully</p>
              <p className="text-xs text-muted-foreground mt-1">Order ID: {result.orderId}</p>
              {result.leverage !== String(leverageNum) && (
                <p className="text-xs text-yellow-400 mt-1">Leverage capped: {leverageNum}x → {result.leverage}x (max for {symbol})</p>
              )}
            </div>
            <div className="grid grid-cols-2 gap-2 text-xs">
              <div><span className="text-muted-foreground">Side:</span> <span className="font-medium">{result.side}</span></div>
              <div><span className="text-muted-foreground">Leverage:</span> <span className="font-medium">{result.leverage}x</span></div>
              <div><span className="text-muted-foreground">Qty:</span> <span className="font-medium">{result.qty}</span></div>
              <div><span className="text-muted-foreground">USDT:</span> <span className="font-medium">${parseFloat(result.usdt_amount).toFixed(2)}</span></div>
              <div><span className="text-muted-foreground">Entry:</span> <span className="font-medium">{result.mark_price}</span></div>
              <div><span className="text-muted-foreground">TP:</span> <span className="font-medium text-emerald-400">{result.take_profit_price}</span></div>
              <div><span className="text-muted-foreground">SL:</span> <span className="font-medium text-red-400">{result.stop_loss_price}</span></div>
            </div>
            <div className="flex justify-end pt-2">
              <button
                onClick={handleClose}
                className="px-4 py-2 rounded-lg text-sm font-medium bg-secondary text-secondary-foreground hover:bg-secondary/80 transition-colors"
              >
                Close
              </button>
            </div>
          </div>
        ) : (
          <>
            {/* Signal info */}
            <div className="flex items-center gap-2 text-sm">
              <span className="text-muted-foreground">Signal:</span>
              <span className={`px-2 py-0.5 rounded text-xs font-bold ${
                signalDirection === "buy" ? "bg-emerald-500/10 text-emerald-400" : "bg-red-500/10 text-red-400"
              }`}>
                {signalDirection.toUpperCase()}
              </span>
              <span className="text-muted-foreground mx-1">→</span>
              <span className="text-muted-foreground">Trade:</span>
              <span className={`px-2 py-0.5 rounded text-xs font-bold ${
                actualSide === "buy" ? "bg-emerald-500/10 text-emerald-400" : "bg-red-500/10 text-red-400"
              }`}>
                {actualSide.toUpperCase()}
              </span>
            </div>

            {/* Account */}
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-muted-foreground">Account</label>
              <select
                value={settings.accountId}
                onChange={(e) => handleAccountChange(e.target.value)}
                className={inputClass}
              >
                <option value="">Select account...</option>
                {accounts.filter((acc: TradingAccount) => acc.is_active).map((acc: TradingAccount) => (
                  <option key={acc.id} value={acc.id}>
                    {acc.label} ({acc.account_type})
                  </option>
                ))}
              </select>
            </div>

            {/* Base Capital */}
            {settings.accountId && (
              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <label className="text-xs font-medium text-muted-foreground">Base Capital (USDT)</label>
                  <button
                    onClick={() => fetchAndSetBaseCapital(settings.accountId, true)}
                    disabled={baseCapitalLoading}
                    className="text-[11px] text-primary hover:underline flex items-center gap-1 disabled:opacity-50"
                    title="Refresh from current wallet balance"
                  >
                    {baseCapitalLoading ? (
                      <div className="w-3 h-3 border border-primary border-t-transparent rounded-full animate-spin" />
                    ) : (
                      <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                      </svg>
                    )}
                    Sync balance
                  </button>
                </div>
                <input
                  type="number"
                  value={baseCapital}
                  onChange={(e) => {
                    setBaseCapital(e.target.value);
                    if (settings.accountId && e.target.value) {
                      saveBaseCapital(settings.accountId, e.target.value);
                    }
                  }}
                  className={inputClass}
                  placeholder="0.00"
                />
                <p className="text-[11px] text-muted-foreground">
                  Auto-set from wallet balance daily. Click sync to update now.
                </p>
              </div>
            )}

            {/* Direction */}
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-muted-foreground">Direction</label>
              <div className="flex gap-2">
                {(["straight", "reverse"] as const).map((d) => (
                  <button
                    key={d}
                    onClick={() => update({ direction: d })}
                    className={`flex-1 px-3 py-2 rounded-lg text-sm font-medium border transition-colors ${
                      settings.direction === d
                        ? "border-primary bg-primary/10 text-primary"
                        : "border-border bg-muted/30 text-muted-foreground hover:bg-muted/50"
                    }`}
                  >
                    {d === "straight" ? "Straight" : "Reverse"}
                  </button>
                ))}
              </div>
              <p className="text-[11px] text-muted-foreground">
                {settings.direction === "straight"
                  ? "Trade follows signal direction"
                  : "Trade opposes signal direction"}
              </p>
            </div>

            {/* Leverage & Capital % */}
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-muted-foreground">Leverage</label>
                <div className="flex items-center gap-2">
                  <input
                    type="number"
                    value={settings.leverage}
                    onChange={(e) => update({ leverage: e.target.value })}
                    min={1}
                    max={125}
                    className={inputClass}
                  />
                  <span className="text-sm text-muted-foreground">x</span>
                </div>
              </div>
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-muted-foreground">Capital %</label>
                <div className="flex items-center gap-2">
                  <input
                    type="number"
                    value={settings.capitalPct}
                    onChange={(e) => update({ capitalPct: e.target.value })}
                    min={0.1}
                    max={100}
                    step={0.1}
                    className={inputClass}
                  />
                  <span className="text-sm text-muted-foreground">%</span>
                </div>
              </div>
            </div>

            {/* Position size preview */}
            {baseCapitalNum > 0 && capitalPctNum > 0 && (
              <div className="rounded-lg bg-muted/30 border border-border/50 p-3 space-y-1">
                <div className="flex justify-between text-xs">
                  <span className="text-muted-foreground">USDT per trade</span>
                  <span className="font-medium font-mono">${usdtPerTrade.toFixed(2)}</span>
                </div>
                <div className="flex justify-between text-xs">
                  <span className="text-muted-foreground">Notional ({leverageNum}x)</span>
                  <span className="font-medium font-mono">${notionalValue.toFixed(2)}</span>
                </div>
              </div>
            )}

            {/* TP / SL */}
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-muted-foreground">Take Profit %</label>
                <input
                  type="number"
                  value={settings.tpPct}
                  onChange={(e) => update({ tpPct: e.target.value })}
                  min={0.1}
                  step={0.1}
                  className={inputClass}
                />
                <p className={`text-[11px] ${tpExceedsPrice ? "text-red-400 font-medium" : "text-muted-foreground"}`}>
                  {tpExceedsPrice ? "TP exceeds 100% price move (short)" : `≈ ${tpActual}% price move`}
                </p>
              </div>
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-muted-foreground">Stop Loss %</label>
                <input
                  type="number"
                  value={settings.slPct}
                  onChange={(e) => update({ slPct: e.target.value })}
                  min={0.1}
                  step={0.1}
                  className={inputClass}
                />
                <p className={`text-[11px] ${slExceedsPrice ? "text-red-400 font-medium" : "text-muted-foreground"}`}>
                  {slExceedsPrice ? "SL exceeds 100% price move" : `≈ ${slActual}% price move`}
                </p>
              </div>
            </div>

            {/* Actions */}
            <div className="flex items-center justify-end gap-2 pt-2">
              <button
                onClick={handleClose}
                disabled={loading}
                className="px-4 py-2 rounded-lg text-sm font-medium bg-secondary text-secondary-foreground hover:bg-secondary/80 transition-colors disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={handleSubmit}
                disabled={!isValid || loading}
                className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors disabled:opacity-50 flex items-center gap-2 ${
                  actualSide === "buy"
                    ? "bg-emerald-600 text-white hover:bg-emerald-700"
                    : "bg-red-600 text-white hover:bg-red-700"
                }`}
              >
                {loading && (
                  <div className="w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin" />
                )}
                {actualSide === "buy" ? "Buy" : "Sell"} {symbol}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
