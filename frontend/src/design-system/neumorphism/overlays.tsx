import { toast } from "sonner";
import { AlertTriangle, LoaderCircle, Wifi, WifiOff } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import { NeuSurface } from "./foundation";
import { NeuButton } from "./inputs";
import type { NeuTone } from "./types";

function toneColor(tone: NeuTone) {
  if (tone === "accent") return "var(--neu-accent)";
  if (tone === "success") return "var(--neu-success)";
  if (tone === "warning") return "var(--neu-warning)";
  if (tone === "danger") return "var(--neu-danger)";
  return "var(--neu-text-strong)";
}

export function NeuDialog({
  open,
  onOpenChange,
  title,
  description,
  size = "md",
  footer,
  danger = false,
  mobileFullscreen = false,
  initialFocus,
  children,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: React.ReactNode;
  description?: React.ReactNode;
  size?: "sm" | "md" | "lg" | "xl";
  footer?: React.ReactNode;
  danger?: boolean;
  mobileFullscreen?: boolean;
  initialFocus?: string;
  children: React.ReactNode;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className={cn(
          "max-w-[calc(100%-1rem)] border-0 bg-transparent p-0 shadow-none",
          mobileFullscreen && "h-[calc(100dvh-0.75rem)] max-h-[calc(100dvh-0.75rem)] sm:h-auto sm:max-h-none",
          size === "sm" && "sm:max-w-md",
          size === "md" && "sm:max-w-xl",
          size === "lg" && "sm:max-w-3xl",
          size === "xl" && "sm:max-w-5xl",
        )}
        showCloseButton={false}
      >
        <NeuSurface
          depth="raised"
          radius="lg"
          padding="lg"
          className={cn("space-y-4 shadow-[var(--neu-shadow-float)]", mobileFullscreen && "flex h-full flex-col")}
          style={{
            borderColor: danger
              ? "color-mix(in oklch, var(--neu-danger) 28%, var(--neu-stroke-soft))"
              : undefined,
          }}
        >
          <DialogHeader className="space-y-2">
            <DialogTitle className="text-xl font-semibold tracking-[-0.03em]">{title}</DialogTitle>
            {description ? (
              <DialogDescription className="text-sm leading-7" style={{ color: "var(--neu-text-muted)" }}>
                {description}
              </DialogDescription>
            ) : null}
          </DialogHeader>
          <div data-initial-focus={initialFocus} className={cn("space-y-4", mobileFullscreen && "neu-scrollbar min-h-0 flex-1 overflow-auto pr-1")}>
            {children}
          </div>
          {footer ? <DialogFooter className="border-0 bg-transparent p-0">{footer}</DialogFooter> : null}
        </NeuSurface>
      </DialogContent>
    </Dialog>
  );
}

export function NeuDrawer({
  open,
  onOpenChange,
  title,
  description,
  side = "right",
  size = "md",
  showHandle = true,
  footer,
  children,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: React.ReactNode;
  description?: React.ReactNode;
  side?: "left" | "right" | "bottom";
  size?: "sm" | "md" | "lg" | "full";
  showHandle?: boolean;
  footer?: React.ReactNode;
  children: React.ReactNode;
}) {
  const sizeClass =
    size === "sm"
      ? "w-[min(100vw,20rem)]"
      : size === "lg"
        ? "w-[min(100vw,40rem)]"
        : size === "full"
          ? "w-[min(100vw,100rem)]"
          : "w-[min(100vw,32rem)]";
  const sideClasses =
    side === "left"
      ? `left-0 top-0 ${sizeClass}`
      : side === "bottom"
        ? size === "full"
          ? "inset-x-0 bottom-0 top-0 w-full"
          : "bottom-0 left-1/2 top-auto w-[min(100vw,60rem)] -translate-x-1/2"
        : `right-0 top-0 ${sizeClass}`;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent variant="drawer" className={cn("inset-y-0 h-[100dvh] border-0 bg-transparent p-0 shadow-none", sideClasses)} showCloseButton={false}>
        <NeuSurface depth="raised" radius="lg" padding="md" className="flex h-full flex-col gap-2 shadow-none overflow-hidden">
          {showHandle && side === "bottom" ? (
            <div className="flex justify-center pt-2">
              <span
                className="inline-flex h-1.5 w-12 rounded-full"
                style={{ background: "color-mix(in oklch, var(--neu-text-soft) 30%, transparent)" }}
              />
            </div>
          ) : null}
          {title ? (
          <DialogHeader className="space-y-2 shrink-0">
            <DialogTitle className="text-xl font-semibold tracking-[-0.03em]">{title}</DialogTitle>
            {description ? (
              <DialogDescription className="text-sm leading-7" style={{ color: "var(--neu-text-muted)" }}>
                {description}
              </DialogDescription>
            ) : null}
          </DialogHeader>
          ) : null}
          <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain pb-[env(safe-area-inset-bottom,0.5rem)]">{children}</div>
          {footer ? <div className="shrink-0">{footer}</div> : null}
        </NeuSurface>
      </DialogContent>
    </Dialog>
  );
}

export function NeuToast({
  title,
  description,
  tone = "neutral",
  action,
}: {
  title: React.ReactNode;
  description?: React.ReactNode;
  tone?: NeuTone;
  action?: React.ReactNode;
}) {
  return (
    <NeuSurface
      depth="raised"
      radius="md"
      padding="sm"
      className="w-[min(100vw,24rem)] space-y-2 shadow-[var(--neu-shadow-float)]"
      style={{ borderColor: `color-mix(in oklch, ${toneColor(tone)} 20%, var(--neu-stroke-soft))` }}
    >
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm font-semibold">{title}</p>
        <span className="inline-flex size-2.5 rounded-full" style={{ background: toneColor(tone) }} />
      </div>
      {description ? (
        <p className="text-xs leading-6" style={{ color: "var(--neu-text-muted)" }}>
          {description}
        </p>
      ) : null}
      {action ? <div className="pt-1">{action}</div> : null}
    </NeuSurface>
  );
}

export function showNeuToast(props: React.ComponentProps<typeof NeuToast>) {
  toast.custom(() => <NeuToast {...props} />);
}

export function NeuBanner({
  tone = "neutral",
  title,
  description,
  actions,
}: {
  tone?: "accent" | "success" | "warning" | "danger" | "neutral";
  title: React.ReactNode;
  description: React.ReactNode;
  actions?: React.ReactNode;
}) {
  return (
    <NeuSurface
      depth="raised"
      radius="lg"
      padding="md"
      className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between"
      style={{ borderColor: `color-mix(in oklch, ${toneColor(tone)} 20%, var(--neu-stroke-soft))` }}
    >
      <div className="space-y-1">
        <div className="flex items-center gap-2">
          <span className="neu-surface-base neu-surface-raised inline-flex size-5 items-center justify-center rounded-full">
            <span className="inline-flex size-2.5 rounded-full" style={{ background: toneColor(tone) }} />
          </span>
          <p className="text-sm font-semibold">{title}</p>
        </div>
        <p className="text-sm leading-6" style={{ color: "var(--neu-text-muted)" }}>
          {description}
        </p>
      </div>
      {actions ? <div className="flex flex-wrap gap-2">{actions}</div> : null}
    </NeuSurface>
  );
}

export function NeuReconnectionChip({
  status,
  attempt,
  onRetry,
}: {
  status: "connected" | "reconnecting" | "offline";
  attempt?: number;
  onRetry?: () => void;
}) {
  const tone = status === "connected" ? "success" : status === "reconnecting" ? "warning" : "danger";
  const icon =
    status === "connected" ? <Wifi className="size-4" /> : status === "reconnecting" ? <LoaderCircle className="size-4 animate-spin" /> : <WifiOff className="size-4" />;

  return (
    <div className="flex flex-wrap items-center gap-2">
      <span
        className="neu-surface-base neu-surface-raised neu-pill-soft inline-flex min-h-9 items-center gap-2 rounded-[var(--neu-radius-pill)] px-3 py-1.5 text-xs font-semibold uppercase tracking-[0.16em]"
        style={{
          color: toneColor(tone),
          background: `color-mix(in oklch, ${toneColor(tone)} 14%, var(--neu-surface-raised))`,
          borderColor: `color-mix(in oklch, ${toneColor(tone)} 18%, var(--neu-stroke-soft))`,
        }}
      >
        {icon}
        {status}
        {attempt ? ` #${attempt}` : ""}
      </span>
      {onRetry ? (
        <NeuButton variant="soft-tonal" size="sm" onClick={onRetry}>
          Retry
        </NeuButton>
      ) : null}
    </div>
  );
}

export function NeuConfirmDialog({
  open,
  onConfirm,
  onCancel,
  title,
  body,
  confirmTone = "danger",
  confirmLabel = "Confirm",
}: {
  open: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  title: React.ReactNode;
  body: React.ReactNode;
  confirmTone?: "danger" | "warning";
  confirmLabel?: string;
}) {
  return (
    <NeuDialog
      open={open}
      onOpenChange={(next) => {
        if (!next) onCancel();
      }}
      title={title}
      description={body}
      danger={confirmTone === "danger"}
      footer={
        <div className="flex w-full flex-col gap-2 sm:flex-row sm:justify-end">
          <NeuButton variant="secondary" onClick={onCancel}>
            Cancel
          </NeuButton>
          <NeuButton variant={confirmTone === "danger" ? "danger" : "soft-tonal"} onClick={onConfirm}>
            <AlertTriangle className="size-4" />
            {confirmLabel}
          </NeuButton>
        </div>
      }
    >
      <div className="rounded-[var(--neu-radius-md)] neu-surface-inset p-4 text-sm leading-7" style={{ color: "var(--neu-text-muted)" }}>
        {body}
      </div>
    </NeuDialog>
  );
}
