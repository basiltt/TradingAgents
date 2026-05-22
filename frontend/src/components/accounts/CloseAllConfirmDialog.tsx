import { useRef, useState } from "react";
import { AlertTriangle, Loader2, ShieldAlert, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { accountsApi } from "@/api/client";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

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
      const result = await accountsApi.closeAllPositions(accountId);
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
    } catch (err: unknown) {
      const e = err as { status?: number; detail?: string };
      if (e?.status === 409) {
        toast.error("Close already in progress for this account");
      } else {
        toast.error(e?.detail || "Failed to close positions");
      }
    } finally {
      submittingRef.current = false;
      setLoading(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="close-all-title"
      onClick={() => !loading && onOpenChange(false)}
    >
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_top,oklch(0.58_0.15_24_/_0.18),transparent_38%),rgba(3,8,20,0.72)] backdrop-blur-md" />
      <div
        className="glass-card aurora-border relative w-full max-w-xl overflow-hidden rounded-[calc(var(--radius)*2)] border border-destructive/25 bg-card/88 shadow-[0_38px_120px_-48px_rgba(0,0,0,0.8)]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="absolute inset-x-0 top-0 h-px bg-[linear-gradient(90deg,transparent,color-mix(in_oklch,var(--destructive)_50%,white),transparent)]" />

        <div className="space-y-6 p-5 sm:p-6">
          <div className="flex items-start gap-4">
            <div className="relative flex size-14 shrink-0 items-center justify-center rounded-[calc(var(--radius)*1.35)] border border-destructive/25 bg-destructive/10 text-destructive shadow-[var(--shadow-soft)]">
              <AlertTriangle className="size-6" />
              <span className="absolute -right-1.5 -top-1.5 inline-flex size-6 items-center justify-center rounded-full border border-background/80 bg-background/95 text-[10px] font-bold text-destructive shadow-[var(--shadow-soft)]">
                !
              </span>
            </div>
            <div className="min-w-0 flex-1">
              <p className="section-eyebrow text-destructive/80">Emergency risk action</p>
              <h2 id="close-all-title" className="mt-1 text-xl font-semibold tracking-[-0.04em] text-foreground sm:text-[1.65rem]">
                Close all open positions
              </h2>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">
                Liquidate the current exposure on <span className="font-semibold text-foreground">{accountLabel}</span> using market orders.
                This is designed for rapid risk containment and cannot be undone.
              </p>
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-3">
            {[
              { label: "Account", value: accountLabel, icon: ShieldAlert, tone: "text-primary" },
              { label: "Open positions", value: String(positionsCount), icon: Sparkles, tone: "text-warning" },
              { label: "Execution", value: "Market close", icon: AlertTriangle, tone: "text-destructive" },
            ].map((item) => {
              const Icon = item.icon;
              return (
                <div
                  key={item.label}
                  className="surface-lift rounded-[calc(var(--radius)*1.2)] border border-border/60 px-4 py-3.5"
                >
                  <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                    <Icon className={cn("size-3.5", item.tone)} />
                    {item.label}
                  </div>
                  <div className="mt-2 truncate text-sm font-semibold text-foreground">{item.value}</div>
                </div>
              );
            })}
          </div>

          <div className="rounded-[calc(var(--radius)*1.25)] border border-destructive/18 bg-destructive/7 px-4 py-3.5">
            <div className="flex items-start gap-3">
              <ShieldAlert className="mt-0.5 size-4 shrink-0 text-destructive" />
              <div className="space-y-2 text-sm text-muted-foreground">
                <p className="font-semibold text-foreground">What happens next</p>
                <ul className="space-y-1.5 text-[13px] leading-6">
                  <li>• Every active position on this account will receive a close request.</li>
                  <li>• Partial failures may still leave some positions open and require follow-up review.</li>
                  <li>• The close execution is recorded in account history for later audit.</li>
                </ul>
              </div>
            </div>
          </div>

          <div className="flex flex-col-reverse gap-3 border-t border-border/60 pt-4 sm:flex-row sm:justify-end">
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={loading}
              className="w-full sm:w-auto"
            >
              Keep positions open
            </Button>
            <Button
              type="button"
              variant="destructive"
              onClick={handleConfirm}
              disabled={loading}
              className="w-full sm:w-auto"
            >
              {loading ? <Loader2 className="size-4 animate-spin" /> : <AlertTriangle className="size-4" />}
              {loading ? "Closing positions..." : "Confirm close all"}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
