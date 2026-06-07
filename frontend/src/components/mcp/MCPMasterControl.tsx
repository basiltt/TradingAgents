/**
 * MCPMasterControl — the on/off heart of the console.
 *
 * Enabling the MCP server exposes the application to an external AI agent, so
 * turning it ON requires an explicit confirm and a token to exist first. The
 * card also surfaces live runtime state: running/off, active tool count, and
 * the number of config proposals waiting for human approval.
 */
import { useState } from "react";
import { Loader2, Power, ShieldAlert, Activity, Inbox } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import type { MCPConfig, MCPStatus } from "./types";

export function MCPMasterControl({
  config,
  status,
  pending,
  toggling,
  onToggle,
}: {
  config: MCPConfig;
  status?: MCPStatus;
  pending: number;
  toggling?: boolean;
  onToggle: (next: boolean) => void;
}) {
  const [confirmOpen, setConfirmOpen] = useState(false);
  const running = status?.state === "running";
  const hasToken = config.has_token;
  const enabling = !running;

  function handleClick() {
    if (enabling) {
      setConfirmOpen(true);
    } else {
      onToggle(false);
    }
  }

  return (
    <div className="neu-surface-base neu-surface-raised rounded-[var(--neu-radius-lg)] p-5 shadow-[var(--neu-shadow-float)]">
      <div className="flex flex-col gap-5 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-start gap-4">
          <div
            className={cn(
              "flex size-12 items-center justify-center rounded-[var(--neu-radius-md)] shadow-[var(--neu-shadow-soft)]",
              running ? "bg-[var(--neu-accent)]/12 text-[var(--neu-accent)]" : "bg-[var(--neu-surface-inset)] text-[var(--neu-text-muted)]",
            )}
          >
            <Power className="size-6" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-lg font-bold tracking-tight text-[var(--neu-text-strong)]">
                MCP Server
              </h2>
              <StateBadge running={running} />
            </div>
            <p className="mt-1 max-w-md text-xs leading-relaxed text-[var(--neu-text-muted)]">
              {running
                ? "An external AI agent can connect over the loopback transport and use the enabled tools."
                : "Off by default. When on, an external AI agent can drive the app using the tools you enable below."}
            </p>
          </div>
        </div>

        <div className="flex flex-col items-stretch gap-2 sm:items-end">
          <Button
            variant={running ? "destructive" : "default"}
            size="lg"
            onClick={handleClick}
            disabled={(!hasToken && enabling) || toggling}
            className="min-w-36"
          >
            {toggling ? <Loader2 className="size-4 animate-spin" /> : null}
            {running ? "Disable server" : "Enable server"}
          </Button>
          {!hasToken && enabling ? (
            <span className="text-[11px] font-medium text-warning">
              Generate an access token first ↓
            </span>
          ) : null}
        </div>
      </div>

      {running ? (
        <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-3">
          <Stat icon={Activity} label="Active tools" value={String(status?.active_tools ?? 0)} tone="accent" />
          <Stat icon={Inbox} label="Pending proposals" value={String(pending)} tone={pending ? "warning" : "neutral"} />
          <Stat icon={ShieldAlert} label="Capability tier" value={config.capability_tier} tone="neutral" />
        </div>
      ) : null}

      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <ShieldAlert className="size-5 text-warning" />
              Enable the MCP server?
            </DialogTitle>
            <DialogDescription className="space-y-2 pt-1 text-left">
              <span className="block">
                This opens a loopback transport that lets an external AI agent call the
                tools you have enabled. The agent can read data and run backtests, but it
                can never change live trading config on its own — every money-affecting
                change comes back to you here as a proposal to approve.
              </span>
              <span className="block font-medium text-[var(--neu-text-strong)]">
                Tier: {config.capability_tier} · {status?.active_tools ?? "—"} tools will be exposed.
              </span>
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setConfirmOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="default"
              onClick={() => {
                setConfirmOpen(false);
                onToggle(true);
              }}
            >
              Enable server
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function StateBadge({ running }: { running: boolean }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-[0.16em]",
        running
          ? "bg-[var(--neu-accent)]/12 text-[var(--neu-accent)]"
          : "bg-[var(--neu-surface-inset)] text-[var(--neu-text-muted)]",
      )}
    >
      <span className={cn("size-1.5 rounded-full", running ? "bg-[var(--neu-accent)] animate-pulse" : "bg-[var(--neu-text-muted)]")} />
      {running ? "Running" : "Off"}
    </span>
  );
}

function Stat({
  icon: Icon,
  label,
  value,
  tone,
}: {
  icon: typeof Activity;
  label: string;
  value: string;
  tone: "accent" | "warning" | "neutral";
}) {
  return (
    <div data-tone={tone} className="page-header-stat rounded-[var(--neu-radius-md)] border px-3.5 py-3">
      <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-[var(--neu-text-muted)]">
        <Icon className="size-3.5" />
        {label}
      </div>
      <div className="mt-1.5 text-base font-bold tracking-tight text-[var(--neu-text-strong)]">{value}</div>
    </div>
  );
}
