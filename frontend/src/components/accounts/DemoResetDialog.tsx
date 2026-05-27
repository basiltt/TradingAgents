/**
 * @module DemoResetDialog
 * @description Modal dialog for resetting demo account balances to a target amount.
 * Streams SSE progress events and displays results.
 */

import { useState, useEffect, useRef, useCallback } from "react";
import { accountsApi } from "@/api/client";
import type { DemoResetBalanceResult, DashboardCard } from "@/api/client";
import { Button } from "@/components/ui/button";

/** Maximum number of progress entries to retain to prevent unbounded growth. */
const MAX_PROGRESS_ENTRIES = 200;

interface DemoResetDialogProps {
  open: boolean;
  onClose: () => void;
  onComplete: () => void;
  dashboard: DashboardCard[];
  initialSelectedIds: string[];
}

interface ResetProgressState {
  current: number;
  total: number;
  accounts: Array<{ name: string; status: string; amount?: number }>;
}

/**
 * Demo balance reset dialog — allows the user to set a target USDT balance for
 * selected demo accounts. Shows real-time SSE progress and final result summary.
 *
 * @param props.open - Whether the dialog is visible.
 * @param props.onClose - Called when the user dismisses the dialog.
 * @param props.onComplete - Called after the operation finishes (to refresh dashboard).
 * @param props.dashboard - Current dashboard cards (used to derive demo account list).
 * @param props.initialSelectedIds - Pre-selected demo account IDs.
 */
export function DemoResetDialog({ open, onClose, onComplete, dashboard, initialSelectedIds }: DemoResetDialogProps) {
  const [loading, setLoading] = useState(false);
  const [amount, setAmount] = useState("100");
  const [result, setResult] = useState<DemoResetBalanceResult | null>(null);
  const [progress, setProgress] = useState<ResetProgressState>({ current: 0, total: 0, accounts: [] });
  const [selectedIds, setSelectedIds] = useState<string[]>(initialSelectedIds);
  const taskId = useRef<string | null>(null);

  useEffect(() => {
    if (open) setSelectedIds(initialSelectedIds);
  }, [open, initialSelectedIds]);

  const reset = useCallback(() => {
    setResult(null);
    setProgress({ current: 0, total: 0, accounts: [] });
    setSelectedIds([]);
  }, []);

  useEffect(() => {
    if (!open) return;

    const onProgressEvt = (e: Event) => {
      const d = (e as CustomEvent).detail;
      if (taskId.current && d.task_id !== taskId.current) return;
      setProgress(p => ({
        current: d.current,
        total: d.total,
        accounts: [...p.accounts, { name: d.account?.name || "", status: d.account?.status || "", amount: d.account?.amount }].slice(-MAX_PROGRESS_ENTRIES),
      }));
    };
    const onCompleteEvt = (e: Event) => {
      const d = (e as CustomEvent).detail;
      if (taskId.current && d.task_id !== taskId.current) return;
      setResult({ target_balance: d.target_balance, accounts_processed: d.accounts_processed, success: d.success, results: d.results });
      setLoading(false);
      taskId.current = null;
      onComplete();
    };
    window.addEventListener("demo_reset_progress", onProgressEvt);
    window.addEventListener("demo_reset_complete", onCompleteEvt);
    return () => {
      window.removeEventListener("demo_reset_progress", onProgressEvt);
      window.removeEventListener("demo_reset_complete", onCompleteEvt);
    };
  }, [open, onComplete]);

  if (!open) return null;

  const demoAccounts = dashboard.filter(c => c.account_type === "demo" && c.is_active);

  const handleExecute = async () => {
    const parsedAmount = parseFloat(amount);
    if (!parsedAmount || parsedAmount <= 0 || parsedAmount > 100000) return;
    if (selectedIds.length === 0) return;
    setLoading(true);
    setProgress({ current: 0, total: 0, accounts: [] });
    try {
      const allDemoIds = demoAccounts.map(c => c.id);
      const ids = selectedIds.length === allDemoIds.length ? undefined : selectedIds;
      const res = await accountsApi.demoResetBalance(parsedAmount, ids);
      taskId.current = res.task_id;
      setProgress(p => ({ ...p, total: res.accounts_total }));
      if (!res.task_id) {
        setResult({ target_balance: parsedAmount, accounts_processed: 0, success: 0, results: [] });
        setLoading(false);
      }
    } catch (e: unknown) {
      setResult({ target_balance: parsedAmount, accounts_processed: 0, success: 0, results: [{ account_id: "", name: "", status: "error", reason: (e as { message?: string }).message || "Unknown error" }] });
      setLoading(false);
    }
  };

  const handleDismiss = () => {
    if (!loading) {
      reset();
      onClose();
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center animate-fade-in" role="dialog" aria-modal="true" aria-labelledby="reset-dialog-title">
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={handleDismiss} aria-hidden="true" />
      <div className="relative glass-card hover:transform-none hover:translate-y-0 rounded-2xl p-5 w-full max-w-md shadow-2xl mx-4 bg-card/75 backdrop-blur-md border border-border/40">
        {!loading && !result ? (
          <>
            <div className="flex items-center gap-3.5 mb-4">
              <div className="w-10 h-10 rounded-xl bg-amber-500/10 flex items-center justify-center glow-success">
                <svg className="w-5 h-5 text-amber-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5} aria-hidden="true">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v12m-3-2.818l.879.659c1.171.879 3.07.879 4.242 0 1.172-.879 1.172-2.303 0-3.182C13.536 12.219 12.768 12 12 12c-.725 0-1.45-.22-2.003-.659-1.106-.879-1.106-2.303 0-3.182s2.9-.879 4.006 0l.415.33M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
              </div>
              <div>
                <h3 id="reset-dialog-title" className="text-base font-bold text-foreground">Reset Demo Balance</h3>
                <p className="text-[10px] font-black uppercase tracking-wider text-amber-500/80">Balance Adjustment</p>
              </div>
            </div>
            <div className="space-y-4 mb-5">
              <div>
                <label htmlFor="reset-amount" className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1.5 block">Target Balance (USDT)</label>
                <input
                  id="reset-amount"
                  type="number"
                  value={amount}
                  onChange={(e) => setAmount(e.target.value)}
                  min="1"
                  max="100000"
                  className="w-full rounded-xl border border-border/40 bg-muted/20 px-3.5 py-2.5 text-sm font-bold text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-2 focus:ring-amber-500/30 focus:border-amber-500/50 transition-all"
                  placeholder="100"
                />
              </div>
              <div>
                <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1.5 block">Select Accounts</label>
                <div className="space-y-1.5 max-h-40 overflow-y-auto custom-scrollbar pr-1">
                  {demoAccounts.map((acc) => (
                    <label key={acc.id} className="flex items-center gap-2.5 text-xs px-3 py-2 rounded-xl bg-muted/20 border border-border/20 cursor-pointer hover:bg-muted/30 transition-colors">
                      <input
                        type="checkbox"
                        checked={selectedIds.includes(acc.id)}
                        onChange={(e) => {
                          if (e.target.checked) setSelectedIds(prev => [...prev, acc.id]);
                          else setSelectedIds(prev => prev.filter(id => id !== acc.id));
                        }}
                        className="rounded border-border/40"
                      />
                      <span className="font-semibold truncate">{acc.label}</span>
                    </label>
                  ))}
                </div>
              </div>
            </div>
            <div className="flex gap-3">
              <Button variant="outline" onClick={() => { reset(); onClose(); }} className="flex-1">
                Cancel
              </Button>
              <Button
                onClick={handleExecute}
                disabled={!amount || parseFloat(amount) <= 0 || selectedIds.length === 0}
                className="flex-1 border-amber-500/25 bg-amber-500/10 text-amber-500 hover:bg-amber-500/15 disabled:opacity-50"
              >
                Set Balance
              </Button>
            </div>
          </>
        ) : loading ? (
          <>
            <div className="flex items-center gap-3.5 mb-4">
              <div className="w-10 h-10 rounded-xl bg-amber-500/10 flex items-center justify-center animate-pulse glow-success">
                <svg className="w-5 h-5 text-amber-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5} aria-hidden="true">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v12m-3-2.818l.879.659c1.171.879 3.07.879 4.242 0 1.172-.879 1.172-2.303 0-3.182C13.536 12.219 12.768 12 12 12c-.725 0-1.45-.22-2.003-.659-1.106-.879-1.106-2.303 0-3.182s2.9-.879 4.006 0l.415.33M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
              </div>
              <div>
                <h3 className="text-base font-bold text-foreground">Resetting Balances...</h3>
                <p className="text-[10px] font-black uppercase tracking-wider text-muted-foreground" aria-live="polite">{progress.current} / {progress.total} accounts</p>
              </div>
            </div>
            {progress.total > 0 && (
              <div className="mb-4" role="progressbar" aria-valuenow={progress.current} aria-valuemax={progress.total}>
                <div className="h-2 rounded-full bg-muted/50 overflow-hidden border border-border/20">
                  <div
                    className="h-full bg-amber-500 transition-all duration-300 ease-out rounded-full glow-success"
                    style={{ width: `${(progress.current / progress.total) * 100}%` }}
                  />
                </div>
              </div>
            )}
            <div className="max-h-48 overflow-y-auto space-y-1.5 custom-scrollbar pr-1">
              {progress.accounts.map((a, i) => (
                <div key={i} className="flex items-center justify-between text-xs px-3 py-2 rounded-xl bg-muted/20 border border-border/20">
                  <span className="truncate mr-2 font-semibold">{a.name}</span>
                  <span className={`text-[10px] font-black uppercase tracking-wider shrink-0 ${a.status === "error" ? "text-red-500" : a.status === "unchanged" ? "text-muted-foreground" : "text-emerald-500"}`}>
                    {a.status === "added" || a.status === "reduced" ? `${a.status} $${a.amount || 0}` : a.status}
                  </span>
                </div>
              ))}
            </div>
            <Button
              variant="link"
              onClick={() => { onClose(); setLoading(false); setProgress({ current: 0, total: 0, accounts: [] }); taskId.current = null; onComplete(); }}
              className="mt-5 w-full text-[10px] font-black uppercase tracking-wider text-muted-foreground hover:text-foreground transition-colors cursor-pointer text-center"
            >
              Dismiss (continues in background)
            </Button>
          </>
        ) : result ? (
          <>
            <div className="flex items-center gap-3.5 mb-4">
              <div className="w-10 h-10 rounded-xl bg-emerald-500/10 flex items-center justify-center glow-success">
                <svg className="w-5 h-5 text-emerald-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5} aria-hidden="true">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                </svg>
              </div>
              <div>
                <h3 className="text-base font-bold text-foreground">Action Complete</h3>
                <p className="text-[10px] font-black uppercase tracking-wider text-emerald-500">Demo Balances Reset</p>
              </div>
            </div>
            <div className="space-y-2.5 text-xs mb-5 rounded-xl border border-border/40 bg-muted/10 p-3.5">
              <div className="flex justify-between items-center">
                <span className="text-muted-foreground">Target balance:</span>
                <span className="font-bold text-foreground">${result.target_balance} USDT</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-muted-foreground">Accounts processed:</span>
                <span className="font-bold text-foreground">{result.accounts_processed}</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-muted-foreground">Successful:</span>
                <span className="font-bold text-emerald-500">{result.success}</span>
              </div>
              {result.results.filter(r => r.status === "error").length > 0 && (
                <div className="mt-3 max-h-32 overflow-y-auto space-y-1.5 border-t border-border/40 pt-2.5 pr-1 custom-scrollbar">
                  {result.results.filter(r => r.status === "error").map((r, i) => (
                    <p key={i} className="text-[11px] text-red-400 font-semibold">{r.name || r.account_id}: {r.reason}</p>
                  ))}
                </div>
              )}
            </div>
            <Button onClick={() => { reset(); onClose(); }} className="w-full">
              Done
            </Button>
          </>
        ) : null}
      </div>
    </div>
  );
}
