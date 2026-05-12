import { useState, useRef } from "react";
import { Loader2, AlertTriangle } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api/client";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  accountId: string;
  accountLabel: string;
  positionsCount: number;
  onSuccess: () => void;
}

export function CloseAllConfirmDialog({ open, onOpenChange, accountId, accountLabel, positionsCount, onSuccess }: Props) {
  const [loading, setLoading] = useState(false);
  const submittingRef = useRef(false);

  if (!open) return null;

  const handleConfirm = async () => {
    if (submittingRef.current) return;
    submittingRef.current = true;
    setLoading(true);
    try {
      const result = await api.closeAllPositions(accountId);
      onOpenChange(false);

      if (result.total === 0) {
        toast.info("No open positions found");
      } else if (result.failed === 0) {
        toast.success(`All ${result.closed} positions closed for ${accountLabel}`);
      } else if (result.closed > 0) {
        toast.warning(`${result.closed} of ${result.total} positions closed for ${accountLabel}. ${result.failed} failed.`);
      } else {
        toast.error(`Failed to close positions for ${accountLabel}`);
      }
      onSuccess();
    } catch (err: any) {
      if (err?.status === 409) {
        toast.error("Close already in progress for this account");
      } else {
        toast.error(err?.detail || "Failed to close positions");
      }
    } finally {
      submittingRef.current = false;
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" onClick={() => !loading && onOpenChange(false)}>
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" />
      <div
        className="relative bg-popover border border-border/50 rounded-2xl shadow-2xl shadow-black/30 max-w-md w-full mx-4 p-6 animate-in fade-in zoom-in-95 duration-200"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-3 mb-4">
          <div className="p-2.5 rounded-xl bg-red-500/10">
            <AlertTriangle className="w-5 h-5 text-red-400" />
          </div>
          <div>
            <h3 className="font-semibold text-base">Close All Positions</h3>
            <p className="text-sm text-muted-foreground">{accountLabel}</p>
          </div>
        </div>

        <p className="text-sm text-muted-foreground mb-6">
          This will close all <strong className="text-foreground">{positionsCount}</strong> open position{positionsCount !== 1 ? "s" : ""} for this account using market orders. This action cannot be undone.
        </p>

        <div className="flex justify-end gap-3">
          <button
            className="px-4 py-2 text-sm rounded-lg border border-border/50 hover:bg-muted/30 transition-colors"
            onClick={() => onOpenChange(false)}
            disabled={loading}
          >
            Cancel
          </button>
          <button
            className="px-4 py-2 text-sm rounded-lg bg-red-500 hover:bg-red-600 text-white font-medium transition-colors flex items-center gap-2 disabled:opacity-50"
            onClick={handleConfirm}
            disabled={loading}
          >
            {loading && <Loader2 className="w-4 h-4 animate-spin" />}
            {loading ? "Closing..." : "Close All Positions"}
          </button>
        </div>
      </div>
    </div>
  );
}
