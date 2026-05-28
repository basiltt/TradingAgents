/**
 * @module KillSwitchDialog
 * @description Modal dialog for the master kill switch — closes all open positions
 * across every active account. Streams SSE progress events and displays results.
 */

import { useState, useEffect, useRef, useCallback } from "react";
import { accountsApi } from "@/api/client";
import type { MasterCloseAllResult, DashboardCard } from "@/api/client";
import { Button } from "@/components/ui/button";

/** Maximum number of progress entries to retain to prevent unbounded growth. */
const MAX_PROGRESS_ENTRIES = 200;

interface KillSwitchDialogProps {
  open: boolean;
  onClose: () => void;
  onComplete: () => void;
  dashboard: DashboardCard[];
}

interface KillProgressState {
  current: number;
  total: number;
  accounts: Array<{ name: string; status: string; closed?: number }>;
}

/**
 * Master kill switch dialog — confirms and executes close-all-positions across
 * every active account. Shows real-time SSE progress and final result summary.
 *
 * @param props.open - Whether the dialog is visible.
 * @param props.onClose - Called when the user dismisses the dialog.
 * @param props.onComplete - Called after the operation finishes (to refresh dashboard).
 * @param props.dashboard - Current dashboard cards (used to derive active account list).
 */
export function KillSwitchDialog({ open, onClose, onComplete, dashboard }: KillSwitchDialogProps) {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<MasterCloseAllResult | null>(null);
  const [progress, setProgress] = useState<KillProgressState>({ current: 0, total: 0, accounts: [] });
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const taskId = useRef<string | null>(null);

  const activeAccounts = dashboard.filter(a => a.is_active);
  const filteredAccounts = activeAccounts.filter(a => a.label.toLowerCase().includes(searchQuery.toLowerCase()));

  const prevOpenRef = useRef(false);
  useEffect(() => {
    if (open && !prevOpenRef.current) {
      setSelectedIds(dashboard.filter(a => a.is_active).map(a => a.id));
    }
    prevOpenRef.current = open;
  }, [open, dashboard]);

  const reset = useCallback(() => {
    setResult(null);
    setProgress({ current: 0, total: 0, accounts: [] });
    setSelectedIds([]);
    setSearchQuery("");
  }, []);

  useEffect(() => {
    if (!open) return;

    const onProgress = (e: Event) => {
      const d = (e as CustomEvent).detail;
      if (taskId.current && d.task_id !== taskId.current) return;
      setProgress(p => ({
        current: d.current,
        total: d.total,
        accounts: [...p.accounts, { name: d.account?.name || "", status: d.account?.status || "", closed: d.account?.closed }].slice(-MAX_PROGRESS_ENTRIES),
      }));
    };
    const onCompleteEvt = (e: Event) => {
      const d = (e as CustomEvent).detail;
      if (taskId.current && d.task_id !== taskId.current) return;
      setResult({ accounts_processed: d.accounts_processed, total_positions_closed: d.total_positions_closed, accounts_failed: d.accounts_failed, results: d.results });
      setLoading(false);
      taskId.current = null;
      onComplete();
    };
    window.addEventListener("master_close_progress", onProgress);
    window.addEventListener("master_close_complete", onCompleteEvt);
    return () => {
      window.removeEventListener("master_close_progress", onProgress);
      window.removeEventListener("master_close_complete", onCompleteEvt);
    };
  }, [open, onComplete]);

  if (!open) return null;

  const handleExecute = async () => {
    if (selectedIds.length === 0) return;
    setLoading(true);
    setProgress({ current: 0, total: 0, accounts: [] });
    try {
      const ids = selectedIds.length === activeAccounts.length ? undefined : selectedIds;
      const res = await accountsApi.masterCloseAll(ids);
      taskId.current = res.task_id;
      setProgress(p => ({ ...p, total: res.accounts_total }));
      if (!res.task_id) {
        setResult({ accounts_processed: 0, total_positions_closed: 0, accounts_failed: 0, results: [] });
        setLoading(false);
      }
    } catch (e: unknown) {
      setResult({ accounts_processed: 0, total_positions_closed: 0, accounts_failed: 1, results: [{ account_id: "", name: "", status: "error", reason: (e as { message?: string }).message || "Unknown error" }] });
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
    <div className="fixed inset-0 z-50 flex items-center justify-center animate-fade-in" role="dialog" aria-modal="true" aria-labelledby="kill-dialog-title">
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={handleDismiss} aria-hidden="true" />
      <div className="relative glass-card hover:transform-none hover:translate-y-0 rounded-2xl p-5 w-full max-w-md shadow-2xl mx-4 bg-card/75 backdrop-blur-md border border-border/40">
        {!loading && !result ? (
          <>
            <div className="flex items-center gap-3.5 mb-4">
              <div className="w-10 h-10 rounded-xl bg-red-500/10 flex items-center justify-center glow-destructive">
                <svg className="w-5 h-5 text-red-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5} aria-hidden="true">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z" />
                </svg>
              </div>
              <div>
                <h3 id="kill-dialog-title" className="text-base font-bold text-foreground">Close All Positions</h3>
                <p className="text-[10px] font-black uppercase tracking-wider text-red-500/80">Master Kill Switch</p>
              </div>
            </div>
            <p className="text-xs text-muted-foreground mb-3 font-semibold uppercase tracking-wider">This will immediately:</p>
            <ul className="text-xs text-muted-foreground/90 mb-4 space-y-1.5">
              <li className="flex items-center gap-2">
                <span className="w-1.5 h-1.5 rounded-full bg-red-500 shrink-0" aria-hidden="true" />
                <span>Close <span className="text-foreground font-bold">all open positions</span> on selected accounts</span>
              </li>
              <li className="flex items-center gap-2">
                <span className="w-1.5 h-1.5 rounded-full bg-red-500 shrink-0" aria-hidden="true" />
                <span>Delete <span className="text-foreground font-bold">all conditional close rules</span></span>
              </li>
            </ul>
            <div className="mb-4">
              <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1.5 block">Select Accounts</label>
              <div className="flex items-center gap-2 mb-2">
                <input
                  type="text"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="Search accounts..."
                  className="flex-1 rounded-xl border border-border/40 bg-muted/20 px-3 py-1.5 text-xs text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-2 focus:ring-red-500/30 focus:border-red-500/50 transition-all"
                />
                <button
                  type="button"
                  onClick={() => {
                    const filteredIds = filteredAccounts.map(a => a.id);
                    const allSelected = filteredIds.every(id => selectedIds.includes(id));
                    if (allSelected) setSelectedIds(prev => prev.filter(id => !filteredIds.includes(id)));
                    else setSelectedIds(prev => [...new Set([...prev, ...filteredIds])]);
                  }}
                  className="text-[10px] font-bold uppercase tracking-wider text-red-500 hover:text-red-400 transition-colors whitespace-nowrap px-2 py-1.5 rounded-lg hover:bg-red-500/10"
                >
                  {filteredAccounts.length > 0 && filteredAccounts.every(a => selectedIds.includes(a.id)) ? "Deselect All" : "Select All"}
                </button>
              </div>
              <div className="space-y-1.5 max-h-40 overflow-y-auto custom-scrollbar pr-1">
                {filteredAccounts.map((acc) => (
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
                    {(acc.positions_count || 0) > 0 && (
                      <span className="ml-auto text-[10px] text-muted-foreground">{acc.positions_count} pos</span>
                    )}
                  </label>
                ))}
                {filteredAccounts.length === 0 && (
                  <p className="text-xs text-muted-foreground/60 text-center py-2">No accounts match</p>
                )}
              </div>
            </div>
            <div className="rounded-xl bg-red-500/5 border border-red-500/10 p-3 mb-5">
              <p className="text-xs text-red-500 font-bold uppercase tracking-wide mb-1">This action cannot be undone.</p>
              <p className="text-[11px] text-muted-foreground/80 leading-relaxed">Affects <span className="font-bold text-foreground">{selectedIds.length} accounts</span>. Active scheduled scans will not be paused. Pause them separately to prevent new trades from opening.</p>
            </div>
            <div className="flex gap-3">
              <Button variant="outline" onClick={handleDismiss} className="flex-1">
                Cancel
              </Button>
              <Button variant="destructive" onClick={handleExecute} disabled={selectedIds.length === 0} className="flex-1">
                Confirm &mdash; Close All
              </Button>
            </div>
          </>
        ) : loading ? (
          <>
            <div className="flex items-center gap-3.5 mb-4">
              <div className="w-10 h-10 rounded-xl bg-red-500/10 flex items-center justify-center animate-pulse glow-destructive">
                <svg className="w-5 h-5 text-red-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5} aria-hidden="true">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </div>
              <div>
                <h3 className="text-base font-bold text-foreground">Closing Positions...</h3>
                <p className="text-[10px] font-black uppercase tracking-wider text-muted-foreground" aria-live="polite">{progress.current} / {progress.total} accounts</p>
              </div>
            </div>
            {progress.total > 0 && (
              <div className="mb-4" role="progressbar" aria-valuenow={progress.current} aria-valuemax={progress.total}>
                <div className="h-2 rounded-full bg-muted/50 overflow-hidden border border-border/20">
                  <div
                    className="h-full bg-red-500 transition-all duration-300 ease-out rounded-full glow-destructive"
                    style={{ width: `${(progress.current / progress.total) * 100}%` }}
                  />
                </div>
              </div>
            )}
            <div className="max-h-48 overflow-y-auto space-y-1.5 custom-scrollbar pr-1">
              {progress.accounts.map((a, i) => (
                <div key={i} className="flex items-center justify-between text-xs px-3 py-2 rounded-xl bg-muted/20 border border-border/20">
                  <span className="truncate mr-2 font-semibold">{a.name}</span>
                  <span className={`text-[10px] font-black uppercase tracking-wider shrink-0 ${a.status === "error" ? "text-red-500" : "text-emerald-500"}`}>
                    {a.status === "success" ? `${a.closed || 0} closed` : a.status}
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
                <p className="text-[10px] font-black uppercase tracking-wider text-emerald-500">Positions Closed</p>
              </div>
            </div>
            <div className="space-y-2.5 text-xs mb-5 rounded-xl border border-border/40 bg-muted/10 p-3.5">
              <div className="flex justify-between items-center">
                <span className="text-muted-foreground">Accounts processed:</span>
                <span className="font-bold text-foreground">{result.accounts_processed}</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-muted-foreground">Positions closed:</span>
                <span className="font-bold text-emerald-500">{result.total_positions_closed}</span>
              </div>
              {result.accounts_failed > 0 && (
                <div className="flex justify-between items-center">
                  <span className="text-muted-foreground">Accounts failed:</span>
                  <span className="font-bold text-red-500">{result.accounts_failed}</span>
                </div>
              )}
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
