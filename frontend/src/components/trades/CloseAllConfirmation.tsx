import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogDescription,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { useAppSelector, useAppDispatch } from "@/store";
import { setPendingCloseAll } from "@/store/trades-slice";
import { useTradeActions } from "@/components/trades/hooks/useTradeActions";
import { selectActiveTradesList } from "@/components/trades/selectors";
import { ACTIVE_STATUSES } from "@/components/trades/types";

export function CloseAllConfirmation() {
  const dispatch = useAppDispatch();
  const pendingCloseAll = useAppSelector((s) => s.trades.pendingCloseAll);
  const filters = useAppSelector((s) => s.trades.filters);
  const accounts = useAppSelector((s) => s.accounts.cards);
  const trades = useAppSelector(selectActiveTradesList);
  const { closeAll } = useTradeActions();

  const accountId = filters.account_ids?.[0];
  const account = accountId ? accounts.find((a) => a.id === accountId) : undefined;
  const activeTrades = trades.filter(
    (t) => ACTIVE_STATUSES.includes(t.status) && (!accountId || t.account_id === accountId),
  );

  const isOpen = pendingCloseAll === "confirming";
  const isClosing = pendingCloseAll === "closing";

  const handleClose = () => dispatch(setPendingCloseAll(null));

  const handleConfirm = () => {
    if (!accountId) return;
    closeAll(accountId);
  };

  return (
    <Dialog open={isOpen || isClosing} onOpenChange={(open) => !open && handleClose()}>
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
          <Button variant="outline" onClick={handleClose} disabled={isClosing}>
            Cancel
          </Button>
          <Button variant="destructive" onClick={handleConfirm} disabled={isClosing || !accountId}>
            {isClosing ? "Closing..." : "Close All"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
