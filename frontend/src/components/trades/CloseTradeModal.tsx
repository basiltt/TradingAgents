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

        <div className="space-y-3">
          <div className="flex gap-2">
            <Button
              variant={mode === "full" ? "default" : "outline"}
              size="sm"
              onClick={() => setMode("full")}
            >
              Full Close
            </Button>
            <Button
              variant={mode === "partial" ? "default" : "outline"}
              size="sm"
              onClick={() => setMode("partial")}
            >
              Partial Close
            </Button>
          </div>

          {mode === "partial" && (
            <div>
              <label className="text-xs text-muted-foreground">
                Quantity (max {trade?.filled_qty})
              </label>
              <Input
                type="number"
                step="any"
                min="0"
                max={trade?.filled_qty}
                value={qtyInput}
                onChange={(e) => setQtyInput(e.target.value)}
                placeholder="Enter quantity..."
              />
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={handleClose}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            disabled={submitting || !!pending || !isValidPartial}
            onClick={handleConfirm}
          >
            {pending ? "Closing..." : "Confirm Close"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
