import { useState } from "react";
import { toast } from "sonner";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogDescription,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useAppSelector, useAppDispatch } from "@/store";
import { setCloseModalTradeId } from "@/store/trades-slice";
import { useTradeActions } from "@/components/trades/hooks/useTradeActions";

export function CloseTradeModal() {
  const dispatch = useAppDispatch();
  const tradeId = useAppSelector((s) => s.trades.closeModalTradeId);
  const activeTrades = useAppSelector((s) => s.trades.activeTrades);
  const pending = useAppSelector((s) => tradeId ? s.trades.pendingActions[tradeId] : undefined);
  const { closeTrade } = useTradeActions();
  const [qtyInput, setQtyInput] = useState("");
  const [mode, setMode] = useState<"full" | "partial">("full");
  const [submitting, setSubmitting] = useState(false);

  const trade = tradeId ? activeTrades[tradeId] : undefined;
  const isOpen = !!tradeId;

  const handleClose = () => {
    dispatch(setCloseModalTradeId(null));
    setQtyInput("");
    setMode("full");
    setSubmitting(false);
  };

  const handleConfirm = async () => {
    if (!trade || submitting) return;
    setSubmitting(true);
    const qty = mode === "partial" ? parseFloat(qtyInput) : undefined;
    try {
      await closeTrade(trade.account_id, trade.id, qty);
      handleClose();
    } catch {
      toast.error("Failed to close trade");
      setSubmitting(false);
    }
  };

  const partialQty = parseFloat(qtyInput);
  const isValidPartial =
    mode === "full" || (!isNaN(partialQty) && isFinite(partialQty) && partialQty > 0 && partialQty < (trade?.filled_qty ?? 0));

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && handleClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Close Trade</DialogTitle>
          <DialogDescription>
            {trade ? `${trade.symbol} ${trade.side === "Buy" ? "LONG" : "SHORT"} — ${trade.filled_qty ?? 0} qty` : ""}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3.5">
          <div className="flex gap-2">
            <Button
              variant={mode === "full" ? "default" : "outline"}
              size="sm"
              className="rounded-xl flex-1 h-9 cursor-pointer"
              onClick={() => setMode("full")}
            >
              Full Close
            </Button>
            <Button
              variant={mode === "partial" ? "default" : "outline"}
              size="sm"
              className="rounded-xl flex-1 h-9 cursor-pointer"
              onClick={() => setMode("partial")}
            >
              Partial Close
            </Button>
          </div>

          {mode === "partial" && (
            <div className="space-y-1">
              <label className="text-[10px] font-black uppercase tracking-wider text-muted-foreground/60">
                Quantity (max {trade?.filled_qty})
              </label>
              <Input
                type="number"
                step="any"
                min="0"
                max={trade?.filled_qty ?? undefined}
                value={qtyInput}
                onChange={(e) => setQtyInput(e.target.value)}
                placeholder="Enter quantity..."
                className="mt-1 h-10 bg-background/50 border-border/40 focus:border-primary/50 rounded-xl"
              />
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" className="rounded-xl cursor-pointer" onClick={handleClose}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            className="rounded-xl cursor-pointer"
            disabled={submitting || !!pending || !isValidPartial || !trade}
            onClick={handleConfirm}
          >
            {pending ? "Closing..." : "Confirm Close"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
