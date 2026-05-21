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
import { useAppSelector } from "@/store";
import { useTradeActions } from "@/components/trades/hooks/useTradeActions";
import { selectActiveTradesList } from "@/components/trades/selectors";
import { ACTIVE_STATUSES } from "@/components/trades/types";

export function CloseAllConfirmation({
  accountId,
  open,
  onClose,
}: {
  accountId: string | undefined;
  open: boolean;
  onClose: () => void;
}) {
  const accounts = useAppSelector((s) => s.accounts.dashboard);
  const trades = useAppSelector(selectActiveTradesList);
  const pendingCloseAll = useAppSelector((s) => s.trades.pendingCloseAll);
  const { closeAll } = useTradeActions();

  const account = accountId ? accounts.find((a) => a.id === accountId) : undefined;
  const activeTrades = trades.filter(
    (t) => ACTIVE_STATUSES.includes(t.status) && (!accountId || t.account_id === accountId),
  );
  const isClosing = accountId ? !!pendingCloseAll[accountId] : false;

  const handleConfirm = async () => {
    if (!accountId) return;
    try {
      await closeAll(accountId);
      toast.success("All trades closed");
      onClose();
    } catch {
      toast.error("Failed to close trades");
      onClose();
    }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Close All Trades</DialogTitle>
          <DialogDescription>
            Close {activeTrades.length} active trade{activeTrades.length !== 1 ? "s" : ""}
            {account ? ` for ${account.label}` : ""}?
          </DialogDescription>
        </DialogHeader>
        <p className="text-sm text-muted-foreground">
          This will send close orders for all open and pending trades. This action cannot be undone.
        </p>
        <DialogFooter>
          <Button variant="outline" className="rounded-xl cursor-pointer" onClick={onClose} disabled={isClosing}>
            Cancel
          </Button>
          <Button variant="destructive" className="rounded-xl cursor-pointer" onClick={handleConfirm} disabled={isClosing || !accountId}>
            {isClosing ? "Closing..." : "Close All"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
