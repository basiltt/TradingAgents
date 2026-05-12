import { useState, useEffect } from "react";
import { Loader2, X, ChevronLeft, ChevronRight, CheckCircle2, XCircle, Clock } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api/client";
import type { CloseExecution } from "@/api/client";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  accountId: string;
  accountLabel: string;
}

export function CloseHistoryDialog({ open, onOpenChange, accountId, accountLabel }: Props) {
  const [executions, setExecutions] = useState<CloseExecution[]>([]);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const limit = 10;

  useEffect(() => {
    if (!open) {
      setPage(1);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    api.getCloseExecutions(accountId, page, limit, controller.signal)
      .then((res) => {
        if (!controller.signal.aborted) {
          setExecutions(res.items);
          setTotal(res.total);
        }
      })
      .catch((e) => { if (!controller.signal.aborted) toast.error("Failed to load history"); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [open, accountId, page]);

  if (!open) return null;

  const totalPages = Math.max(1, Math.ceil(total / limit));

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" onClick={() => onOpenChange(false)}>
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" />
      <div
        className="relative bg-popover border border-border/50 rounded-2xl shadow-2xl shadow-black/30 max-w-lg w-full mx-4 max-h-[80vh] flex flex-col animate-in fade-in zoom-in-95 duration-200"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border/30">
          <div>
            <h3 className="font-semibold text-base">Close History</h3>
            <p className="text-xs text-muted-foreground mt-0.5">{accountLabel}</p>
          </div>
          <button
            className="p-1.5 rounded-lg hover:bg-muted/30 text-muted-foreground transition-colors"
            onClick={() => onOpenChange(false)}
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-2.5">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
            </div>
          ) : executions.length === 0 ? (
            <div className="text-center py-12">
              <p className="text-sm text-muted-foreground">No close history</p>
              <p className="text-xs text-muted-foreground/60 mt-1">Executions will appear here after positions are closed</p>
            </div>
          ) : (
            executions.map((exec) => <ExecutionRow key={exec.id} execution={exec} />)
          )}
        </div>

        {/* Footer / Pagination */}
        {total > limit && (
          <div className="flex items-center justify-between px-6 py-3 border-t border-border/30">
            <span className="text-xs text-muted-foreground">
              Page {page} of {totalPages}
            </span>
            <div className="flex items-center gap-1">
              <button
                className="p-1.5 rounded-lg hover:bg-muted/30 text-muted-foreground transition-colors disabled:opacity-30"
                disabled={page <= 1}
                onClick={() => setPage((p) => p - 1)}
              >
                <ChevronLeft className="w-4 h-4" />
              </button>
              <button
                className="p-1.5 rounded-lg hover:bg-muted/30 text-muted-foreground transition-colors disabled:opacity-30"
                disabled={page >= totalPages}
                onClick={() => setPage((p) => p + 1)}
              >
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function ExecutionRow({ execution }: { execution: CloseExecution }) {
  const allSuccess = execution.failed_count === 0;
  const allFailed = execution.closed_count === 0;
  const date = new Date(execution.executed_at);

  return (
    <div className="rounded-xl border border-border/40 p-3.5 space-y-2">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          {allSuccess ? (
            <CheckCircle2 className="w-4 h-4 text-emerald-500" />
          ) : allFailed ? (
            <XCircle className="w-4 h-4 text-red-400" />
          ) : (
            <Clock className="w-4 h-4 text-amber-400" />
          )}
          <span className="text-xs font-medium">
            {execution.closed_count}/{execution.total_positions} closed
          </span>
          <span className={`text-[9px] px-1.5 py-0.5 rounded-full font-medium ${
            execution.trigger_source === "rule"
              ? "bg-violet-500/15 text-violet-400"
              : "bg-blue-500/15 text-blue-400"
          }`}>
            {execution.trigger_source === "rule" ? "Rule" : "Manual"}
          </span>
        </div>
        <span className="text-[10px] text-muted-foreground/60">
          {date.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}
        </span>
      </div>

      {execution.results.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {execution.results.slice(0, 8).map((r, i) => (
            <span
              key={i}
              className={`text-[10px] px-1.5 py-0.5 rounded-md border ${
                r.status === "closed"
                  ? "border-emerald-500/20 text-emerald-400 bg-emerald-500/[0.04]"
                  : "border-red-500/20 text-red-400 bg-red-500/[0.04]"
              }`}
              title={r.error || undefined}
            >
              {r.symbol}
            </span>
          ))}
          {execution.results.length > 8 && (
            <span className="text-[10px] text-muted-foreground/50">+{execution.results.length - 8} more</span>
          )}
        </div>
      )}
    </div>
  );
}
