import { useState, useEffect, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  scheduledScansApi,
  apiClient,
  ApiError,
  type ScheduledScan,
  type ScheduleType,
  type CreateScheduledScanRequest,
  type ScheduleConfig,
  type CryptoInterval,
} from "@/api/client";
import { toast } from "sonner";
import { Skeleton } from "@/components/ui/skeleton";
import { ModelSelect } from "@/components/ui/model-select";
import { useModels } from "@/hooks/useModels";
import { useConnectivityCheck } from "@/hooks/useConnectivityCheck";
import { getModelOptions } from "@/lib/model-catalog";
import { ConnBadge } from "@/components/ui/conn-badge";
import { loadEndpoints, saveEndpoint, removeEndpoint, type EndpointProfile } from "@/lib/endpoints";
import { cn } from "@/lib/utils";
import { exportSingle, exportAll, parseImportFile } from "./scheduled-scan-io";
import { AgentModelOverrides, loadOverrides, filterOverridesForAssetType } from "@/components/analysis/AgentModelOverrides";
import { AutoTradeSection } from "@/components/scanner/AutoTradeSection";
import { NeuSwitch } from "@/design-system/neumorphism";
import { PageHeader } from "@/components/layout/PageHeader";
import { Badge } from "@/components/ui/badge";
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
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

function relativeTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  const now = Date.now();
  const diff = d.getTime() - now;
  const abs = Math.abs(diff);
  const past = diff < 0;

  if (abs < 60_000) return past ? "just now" : "in <1m";
  if (abs < 3600_000) {
    const m = Math.round(abs / 60_000);
    return past ? `${m}m ago` : `in ${m}m`;
  }
  if (abs < 86400_000) {
    const h = Math.round(abs / 3600_000);
    return past ? `${h}h ago` : `in ${h}h`;
  }
  const days = Math.round(abs / 86400_000);
  return past ? `${days}d ago` : `in ${days}d`;
}

const STATUS_CONFIG: Record<string, { color: string; dot: string; label: string }> = {
  active: { color: "bg-[color-mix(in_oklch,var(--neu-success)_10%,var(--neu-surface-base))] text-[var(--neu-success)] border-[color-mix(in_oklch,var(--neu-success)_20%,var(--neu-stroke-soft))] shadow-[var(--neu-shadow-pill)]", dot: "bg-[var(--neu-success)]", label: "Active" },
  paused: { color: "bg-[color-mix(in_oklch,var(--neu-warning)_10%,var(--neu-surface-base))] text-[var(--neu-warning)] border-[color-mix(in_oklch,var(--neu-warning)_20%,var(--neu-stroke-soft))] shadow-[var(--neu-shadow-pill)]", dot: "bg-[var(--neu-warning)]", label: "Paused" },
  completed: { color: "bg-[var(--neu-surface-muted)] text-[var(--neu-text-muted)] border-[color:var(--neu-stroke-soft)] shadow-[var(--neu-shadow-pill)]", dot: "bg-[var(--neu-text-muted)]", label: "Completed" },
  error: { color: "bg-[color-mix(in_oklch,var(--neu-danger)_10%,var(--neu-surface-base))] text-[var(--neu-danger)] border-[color-mix(in_oklch,var(--neu-danger)_20%,var(--neu-stroke-soft))] shadow-[var(--neu-shadow-pill)]", dot: "bg-[var(--neu-danger)]", label: "Error" },
  cancelled: { color: "bg-[var(--neu-surface-muted)] text-[var(--neu-text-muted)] border-[color:var(--neu-stroke-soft)] shadow-[var(--neu-shadow-pill)]", dot: "bg-[var(--neu-text-muted)]", label: "Cancelled" },
};

const TYPE_CONFIG: Record<string, { icon: string; label: string; color: string }> = {
  once: { icon: "M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z", label: "One-time", color: "text-[var(--neu-accent)]" },
  interval: { icon: "M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15", label: "Interval", color: "text-[var(--neu-accent)]" },
  daily: { icon: "M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z", label: "Daily", color: "text-[var(--neu-warning)]" },
  weekly: { icon: "M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2", label: "Weekly", color: "text-[var(--neu-accent)]" },
  cron: { icon: "M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4", label: "Cron", color: "text-[var(--neu-danger)]" },
};

const DAYS_OF_WEEK = [
  { value: "mon", label: "Mon" },
  { value: "tue", label: "Tue" },
  { value: "wed", label: "Wed" },
  { value: "thu", label: "Thu" },
  { value: "fri", label: "Fri" },
  { value: "sat", label: "Sat" },
  { value: "sun", label: "Sun" },
];

function scheduleDescription(s: ScheduledScan): string {
  const cfg = s.schedule_config;
  switch (s.schedule_type) {
    case "once":
      return cfg.run_at ? `Scheduled for ${formatDate(cfg.run_at)}` : "One-time";
    case "interval": {
      if (!cfg.interval_minutes) return "Interval";
      const mins = cfg.interval_minutes;
      if (mins >= 60) {
        const h = Number((mins / 60).toFixed(1));
        return `Runs every ${h} hour${h === 1 ? "" : "s"}`;
      }
      return `Runs every ${mins} minute${mins === 1 ? "" : "s"}`;
    }
    case "daily": {
      const days = cfg.days ?? [];
      const timeStr = cfg.time ?? "09:00";
      return days.length === 7 ? `Every day at ${timeStr}` : `${timeStr} on ${days.join(", ")}`;
    }
    case "weekly":
      return `Every ${cfg.day ?? "mon"} at ${cfg.time ?? "09:00"}`;
    case "cron":
      return cfg.cron_expression ?? "Cron";
    default:
      return s.schedule_type;
  }
}

function PulsingDot({ className }: { className?: string }) {
  return (
    <span className={cn("relative flex h-2 w-2", className)}>
      <span className="animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 bg-inherit" />
      <span className="relative inline-flex rounded-full h-2 w-2 bg-inherit" />
    </span>
  );
}

function ScheduleCard({
  schedule: s,
  onPause,
  onResume,
  onTrigger,
  onEdit,
  onExport,
  onDelete,
  isPending,
}: {
  schedule: ScheduledScan;
  onPause: () => void;
  onResume: () => void;
  onTrigger: () => void;
  onEdit: () => void;
  onExport: () => void;
  onDelete: () => void;
  isPending: boolean;
}) {
  const status = STATUS_CONFIG[s.status] ?? STATUS_CONFIG.completed;
  const typeInfo = TYPE_CONFIG[s.schedule_type] ?? TYPE_CONFIG.once;
  const isRunning = s.is_running;

  return (
    <div className="group relative neu-surface-base neu-surface-raised neu-card-hover border-none rounded-[var(--neu-radius-lg)] shadow-[var(--shadow-card)] overflow-hidden">
      {/* Subtle top accent line */}
      <div className={cn(
        "absolute top-0 left-0 right-0 h-[2px] opacity-60",
        isRunning && "bg-gradient-to-r from-primary/0 via-primary to-primary/0",
        !isRunning && s.status === "active" && "bg-gradient-to-r from-emerald-500/0 via-emerald-500 to-emerald-500/0",
        !isRunning && s.status === "paused" && "bg-gradient-to-r from-amber-500/0 via-amber-500 to-amber-500/0",
        !isRunning && s.status === "error" && "bg-gradient-to-r from-red-500/0 via-red-500 to-red-500/0",
        !isRunning && s.status === "cancelled" && "bg-gradient-to-r from-zinc-500/0 via-zinc-500 to-zinc-500/0",
        !isRunning && s.status === "completed" && "bg-gradient-to-r from-zinc-500/0 via-zinc-500 to-zinc-500/0",
      )} />

      <div className="p-5">
        <div className="flex items-start gap-4">
          {/* Type icon */}
          <div className={cn("shrink-0 mt-0.5 w-10 h-10 rounded-[var(--neu-radius-md)] flex items-center justify-center bg-[var(--neu-surface-muted)] shadow-[var(--neu-shadow-inset)] border border-[color:var(--neu-stroke-soft)]", typeInfo.color)}>
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5} aria-hidden="true">
              <path strokeLinecap="round" strokeLinejoin="round" d={typeInfo.icon} />
            </svg>
          </div>

          {/* Main content */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2.5 mb-1">
              <h3 className="font-semibold text-sm text-[var(--neu-text-strong)] truncate" title={s.name}>{s.name}</h3>
              {isRunning && (
                <span className="inline-flex items-center gap-1.5 rounded-[var(--neu-radius-pill)] border px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wider bg-[color-mix(in_oklch,var(--neu-accent)_10%,var(--neu-surface-base))] text-[var(--neu-accent)] border-[color-mix(in_oklch,var(--neu-accent)_20%,var(--neu-stroke-soft))] shadow-[var(--neu-shadow-pill)]">
                  <svg className="w-3 h-3 animate-spin text-[var(--neu-accent)]" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  Running
                </span>
              )}
              <span className={cn("inline-flex items-center gap-1.5 rounded-[var(--neu-radius-pill)] border px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wider", status.color)}>
                {s.status === "active" && !isRunning && <PulsingDot className={status.dot} />}
                {status.label}
              </span>
            </div>

            <p className="text-xs text-[var(--neu-text-muted)] mb-3">{scheduleDescription(s)}</p>

            {/* Info chips */}
            <div className="flex flex-wrap items-center gap-2 text-[11px]">
              <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-[var(--neu-radius-sm)] bg-[var(--neu-surface-muted)] text-[var(--neu-text-muted)] border border-[color:var(--neu-stroke-soft)]">
                <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                Next: {relativeTime(s.next_run_at)}
              </span>
              {s.last_run_at && (
                <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-[var(--neu-radius-sm)] bg-[var(--neu-surface-muted)] text-[var(--neu-text-muted)] border border-[color:var(--neu-stroke-soft)]">
                  <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                  </svg>
                  Last: {relativeTime(s.last_run_at)}
                </span>
              )}
              <span className={cn("inline-flex items-center gap-1 px-2.5 py-1 rounded-[var(--neu-radius-sm)] bg-[var(--neu-surface-muted)] border border-[color:var(--neu-stroke-soft)]", typeInfo.color)}>
                <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d={typeInfo.icon} />
                </svg>
                {typeInfo.label}
              </span>
              {s.consecutive_failures > 0 && (
                <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-[var(--neu-radius-sm)] bg-[color-mix(in_oklch,var(--neu-danger)_10%,var(--neu-surface-base))] text-[var(--neu-danger)] border border-[color-mix(in_oklch,var(--neu-danger)_20%,var(--neu-stroke-soft))]">
                  <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                  </svg>
                  {s.consecutive_failures} failure{s.consecutive_failures > 1 ? "s" : ""}
                  {s.consecutive_failures >= 3 && s.status === "error" && " — auto-paused"}
                </span>
              )}
            </div>
          </div>

          {/* Actions */}
          <div className="flex items-center gap-1.5 shrink-0 opacity-100 sm:opacity-0 sm:group-hover:opacity-100 sm:group-focus-within:opacity-100 transition-opacity duration-200">
            {s.status === "active" && (
              <button
                onClick={onPause}
                className="p-2 rounded-[var(--neu-radius-sm)] bg-[var(--neu-surface-raised)] border border-[color:var(--neu-stroke-soft)] text-[var(--neu-text-muted)] hover:text-[var(--neu-warning)] hover:shadow-[var(--neu-shadow-raised-hover)] hover:translate-y-[-1px] transition-all disabled:opacity-40 cursor-pointer"
                aria-label="Pause"
                title="Pause"
                disabled={isPending}
              >
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M10 9v6m4-6v6m7-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
              </button>
            )}
            {(s.status === "paused" || s.status === "error" || s.status === "cancelled") && (
              <button
                onClick={onResume}
                className="p-2 rounded-[var(--neu-radius-sm)] bg-[var(--neu-surface-raised)] border border-[color:var(--neu-stroke-soft)] text-[var(--neu-text-muted)] hover:text-[var(--neu-success)] hover:shadow-[var(--neu-shadow-raised-hover)] hover:translate-y-[-1px] transition-all disabled:opacity-40 cursor-pointer"
                aria-label="Resume"
                title="Resume"
                disabled={isPending}
              >
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                  <path strokeLinecap="round" strokeLinejoin="round" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
              </button>
            )}
            <button
              onClick={onTrigger}
              className="p-2 rounded-[var(--neu-radius-sm)] bg-[var(--neu-surface-raised)] border border-[color:var(--neu-stroke-soft)] text-[var(--neu-text-muted)] hover:text-[var(--neu-accent)] hover:shadow-[var(--neu-shadow-raised-hover)] hover:translate-y-[-1px] transition-all disabled:opacity-40 cursor-pointer"
              aria-label="Run Now"
              title="Run Now"
              disabled={s.status === "completed" || s.status === "cancelled" || isRunning || isPending}
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
              </svg>
            </button>
            <button
              onClick={onEdit}
              className="p-2 rounded-[var(--neu-radius-sm)] bg-[var(--neu-surface-raised)] border border-[color:var(--neu-stroke-soft)] text-[var(--neu-text-muted)] hover:text-[var(--neu-text-strong)] hover:shadow-[var(--neu-shadow-raised-hover)] hover:translate-y-[-1px] transition-all cursor-pointer"
              aria-label="Edit"
              title="Edit"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
              </svg>
            </button>
            <button
              onClick={onExport}
              className="p-2 rounded-[var(--neu-radius-sm)] bg-[var(--neu-surface-raised)] border border-[color:var(--neu-stroke-soft)] text-[var(--neu-text-muted)] hover:text-[var(--neu-accent)] hover:shadow-[var(--neu-shadow-raised-hover)] hover:translate-y-[-1px] transition-all cursor-pointer"
              aria-label="Export"
              title="Export"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
              </svg>
            </button>
            <button
              onClick={onDelete}
              className="p-2 rounded-[var(--neu-radius-sm)] bg-[var(--neu-surface-raised)] border border-[color:var(--neu-stroke-soft)] text-[var(--neu-text-muted)] hover:text-[var(--neu-danger)] hover:shadow-[var(--neu-shadow-raised-hover)] hover:translate-y-[-1px] transition-all cursor-pointer"
              aria-label="Delete"
              title="Delete"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
              </svg>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export function ScheduledScansPage() {
  const queryClient = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);
  const [pendingActionIds, setPendingActionIds] = useState<Set<string>>(new Set());

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["scheduled-scans"],
    queryFn: ({ signal }) => scheduledScansApi.list(signal),
    refetchInterval: (query) => {
      const hasRunning = query.state.data?.schedules?.some((s: ScheduledScan) => s.is_running);
      return hasRunning ? 3_000 : 10_000;
    },
  });

  const addPending = (id: string) => setPendingActionIds((s) => new Set(s).add(id));
  const removePending = (id: string) => setPendingActionIds((s) => { const n = new Set(s); n.delete(id); return n; });

  const pauseMut = useMutation({
    mutationFn: (id: string) => scheduledScansApi.pause(id),
    onMutate: (id) => addPending(id),
    onSettled: (_d, _e, id) => removePending(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["scheduled-scans"] });
      toast.success("Schedule paused");
    },
    onError: (e) => toast.error(`Failed to pause: ${e.message}`),
  });

  const resumeMut = useMutation({
    mutationFn: (id: string) => scheduledScansApi.resume(id),
    onMutate: (id) => addPending(id),
    onSettled: (_d, _e, id) => removePending(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["scheduled-scans"] });
      toast.success("Schedule resumed");
    },
    onError: (e) => toast.error(`Failed to resume: ${e.message}`),
  });

  const triggerMut = useMutation({
    mutationFn: (id: string) => scheduledScansApi.trigger(id),
    onMutate: (id) => addPending(id),
    onSettled: (_d, _e, id) => removePending(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["scheduled-scans"] });
      toast.success("Schedule triggered");
    },
    onError: (e) => toast.error(e instanceof ApiError && e.status === 429 ? e.message : `Failed to trigger: ${e.message}`),
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => scheduledScansApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["scheduled-scans"] });
      setDeleteConfirm(null);
      toast.success("Schedule deleted");
    },
    onError: (e) => toast.error(`Failed to delete: ${e.message}`),
  });

  const schedules = data?.schedules ?? [];
  const activeCount = schedules.filter((s) => s.status === "active").length;
  const pausedCount = schedules.filter((s) => s.status === "paused").length;
  const errorCount = schedules.filter((s) => s.status === "error").length;
  const cancelledCount = schedules.filter((s) => s.status === "cancelled").length;
  const completedCount = schedules.filter((s) => s.status === "completed").length;

  function openCreate() {
    setEditingId(null);
    setDialogOpen(true);
  }

  function openEdit(id: string) {
    setEditingId(id);
    setDialogOpen(true);
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-center">
        <div className="w-12 h-12 rounded-[calc(var(--radius)*1.25)] bg-red-500/10 flex items-center justify-center mb-4">
          <svg className="w-6 h-6 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
          </svg>
        </div>
        <p className="text-sm text-red-400 font-medium">Failed to load schedules</p>
        <p className="text-xs text-muted-foreground mt-1">{(error as Error).message}</p>
        <Button variant="outline" size="sm" className="mt-4" onClick={() => refetch()}>
          Retry
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-5 pb-7">
      <PageHeader
        eyebrow="Scanner"
        title="Scheduled Scans"
        description=""
        actions={
          <Button onClick={openCreate} className="shrink-0 gap-1.5">
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
            </svg>
            New schedule
          </Button>
        }
        stats={[
          { label: "Active", value: String(activeCount), tone: activeCount ? "success" : "neutral" },
          { label: "Paused", value: String(pausedCount), tone: pausedCount ? "warning" : "neutral" },
          { label: "Errors", value: String(errorCount), tone: errorCount ? "danger" : "neutral" },
          { label: "Completed", value: String(completedCount), tone: "neutral" },
        ]}
      >
        <div className="flex flex-wrap gap-2">
          <Badge variant="outline">{cancelledCount} cancelled schedules</Badge>
        </div>
      </PageHeader>

      {/* Stats bar */}
      {!isLoading && schedules.length > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
          <div className="neu-surface-base neu-surface-raised rounded-[var(--neu-radius-lg)] border-none shadow-[var(--shadow-card)] p-3.5 flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-[color-mix(in_oklch,var(--neu-success)_10%,var(--neu-surface-base))] flex items-center justify-center border border-[color-mix(in_oklch,var(--neu-success)_20%,var(--neu-stroke-soft))]">
              <svg className="w-4.5 h-4.5 text-[var(--neu-success)]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5} aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
              </svg>
            </div>
            <div>
              <p className="text-lg font-bold text-[var(--neu-text-strong)] leading-none">{activeCount}</p>
              <p className="text-[10px] text-[var(--neu-text-muted)]/60 uppercase tracking-wider font-semibold mt-1">Active</p>
            </div>
          </div>
          <div className="neu-surface-base neu-surface-raised rounded-[var(--neu-radius-lg)] border-none shadow-[var(--shadow-card)] p-3.5 flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-[color-mix(in_oklch,var(--neu-warning)_10%,var(--neu-surface-base))] flex items-center justify-center border border-[color-mix(in_oklch,var(--neu-warning)_20%,var(--neu-stroke-soft))]">
              <svg className="w-4.5 h-4.5 text-[var(--neu-warning)]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5} aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" d="M10 9v6m4-6v6m7-3a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </div>
            <div>
              <p className="text-lg font-bold text-[var(--neu-text-strong)] leading-none">{pausedCount}</p>
              <p className="text-[10px] text-[var(--neu-text-muted)]/60 uppercase tracking-wider font-semibold mt-1">Paused</p>
            </div>
          </div>
          <div className="neu-surface-base neu-surface-raised rounded-[var(--neu-radius-lg)] border-none shadow-[var(--shadow-card)] p-3.5 flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-[color-mix(in_oklch,var(--neu-danger)_10%,var(--neu-surface-base))] flex items-center justify-center border border-[color-mix(in_oklch,var(--neu-danger)_20%,var(--neu-stroke-soft))]">
              <svg className="w-4.5 h-4.5 text-[var(--neu-danger)]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5} aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
              </svg>
            </div>
            <div>
              <p className="text-lg font-bold text-[var(--neu-text-strong)] leading-none">{errorCount}</p>
              <p className="text-[10px] text-[var(--neu-text-muted)]/60 uppercase tracking-wider font-semibold mt-1">Errors</p>
            </div>
          </div>
          <div className="neu-surface-base neu-surface-raised rounded-[var(--neu-radius-lg)] border-none shadow-[var(--shadow-card)] p-3.5 flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-[var(--neu-surface-deep)] flex items-center justify-center border border-[color:var(--neu-stroke-soft)]">
              <svg className="w-4.5 h-4.5 text-[var(--neu-text-muted)]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5} aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" d="M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 5.636m12.728 12.728L5.636 5.636" />
              </svg>
            </div>
            <div>
              <p className="text-lg font-bold text-[var(--neu-text-strong)] leading-none">{cancelledCount}</p>
              <p className="text-[10px] text-[var(--neu-text-muted)]/60 uppercase tracking-wider font-semibold mt-1">Cancelled</p>
            </div>
          </div>
          <div className="neu-surface-base neu-surface-raised rounded-[var(--neu-radius-lg)] border-none shadow-[var(--shadow-card)] p-3.5 flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-[var(--neu-surface-deep)] flex items-center justify-center border border-[color:var(--neu-stroke-soft)]">
              <svg className="w-4.5 h-4.5 text-[var(--neu-text-muted)]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5} aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </div>
            <div>
              <p className="text-lg font-bold text-[var(--neu-text-strong)] leading-none">{completedCount}</p>
              <p className="text-[10px] text-[var(--neu-text-muted)]/60 uppercase tracking-wider font-semibold mt-1">Completed</p>
            </div>
          </div>
        </div>
      )}

      {/* Schedule list */}
      {isLoading ? (
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-28 w-full rounded-2xl" />
          ))}
        </div>
      ) : schedules.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-18 text-center">
          <div className="w-12 h-12 rounded-[calc(var(--radius)*1.25)] bg-muted/50 flex items-center justify-center mb-4 border border-border/30">
            <svg className="w-6 h-6 text-muted-foreground/40" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <h3 className="text-base font-semibold text-foreground mb-1">No scheduled scans yet</h3>
          <p className="text-sm text-muted-foreground mb-6 max-w-sm">
            Create automated scan schedules to monitor markets on your preferred timing — from one-time runs to complex cron expressions.
          </p>
          <Button onClick={openCreate} className="gap-1.5">
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
            </svg>
            Create your first schedule
          </Button>
        </div>
      ) : (
        <div className="space-y-3">
          {schedules.map((s) => (
            <ScheduleCard
              key={s.id}
              schedule={s}
              onPause={() => pauseMut.mutate(s.id)}
              onResume={() => resumeMut.mutate(s.id)}
              onTrigger={() => triggerMut.mutate(s.id)}
              onEdit={() => openEdit(s.id)}
              onExport={() => exportSingle(s)}
              onDelete={() => setDeleteConfirm(s.id)}
              isPending={pendingActionIds.has(s.id)}
            />
          ))}
        </div>
      )}

      {/* Delete confirmation */}
      <Dialog open={!!deleteConfirm} onOpenChange={() => setDeleteConfirm(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete Schedule</DialogTitle>
            <DialogDescription>
              This will permanently delete{" "}
              <span className="font-medium text-foreground">
                {schedules.find((s) => s.id === deleteConfirm)?.name ?? "this schedule"}
              </span>{" "}
              and all its execution history. This action cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteConfirm(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={() => deleteConfirm && deleteMut.mutate(deleteConfirm)}
              disabled={deleteMut.isPending}
            >
              {deleteMut.isPending ? "Deleting..." : "Delete"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Create/Edit dialog */}
      <ScheduleFormDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        editingId={editingId}
      />
    </div>
  );
}

// ── Schedule Form Dialog ────────────────────────────────────────

const PROVIDERS_FALLBACK = ["openai", "anthropic", "google", "deepseek", "nvidia", "xai", "qwen", "glm", "openrouter", "azure", "ollama"];
const CRYPTO_ANALYSTS = ["crypto_technical", "crypto_derivatives", "crypto_news", "crypto_fundamentals", "crypto_social"] as const;
const CRYPTO_INTERVALS: { value: CryptoInterval; label: string }[] = [
  { value: "15", label: "15 min" },
  { value: "60", label: "1 hour" },
  { value: "240", label: "4 hours" },
  { value: "D", label: "1 day" },
];
const LANGUAGES = ["English", "Chinese", "Japanese", "Korean", "Spanish", "French", "German", "Portuguese", "Russian", "Arabic", "Hindi"] as const;
const STORAGE_KEY = "tradingagents_settings";
const SCHED_FORM_KEY = "tradingagents_scheduled_scan_form";

interface ScheduledFormDefaults {
  name?: string;
  scheduleType?: ScheduleType;
  runAt?: string;
  intervalMinutes?: number;
  time?: string;
  days?: string[];
  day?: string;
  cronExpression?: string;
  timezone?: string;
  provider?: string;
  klineInterval?: CryptoInterval;
  analysts?: string[];
  researchDepth?: number;
  outputLanguage?: string;
  maxDebateRounds?: number;
  maxRiskRounds?: number;
  maxRecurLimit?: number;
  maxParallel?: number;
  workflowMode?: "quick_trade" | "deep_analysis";
  taPrefilterEnabled?: boolean;
  taPrefilterThreshold?: number;
  checkpointEnabled?: boolean;
  llmMaxConcurrent?: number;
  llmMinSpacingMs?: number;
  backendUrl?: string;
  llmApiKey?: string;
  deepModel?: string;
  quickModel?: string;
  autoTradeConfigs?: import("@/api/client").AutoTradeConfig[];
}

function loadFormDefaults(): ScheduledFormDefaults {
  try { return JSON.parse(localStorage.getItem(SCHED_FORM_KEY) ?? "{}"); } catch { return {}; }
}

function saveFormDefaults(data: ScheduledFormDefaults) {
  try { localStorage.setItem(SCHED_FORM_KEY, JSON.stringify(data)); } catch { /* quota */ }
}

function loadSavedSettings(): Record<string, string> {
  try { return JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "{}"); } catch { return {}; }
}

const SCHEDULE_TYPES: { value: ScheduleType; label: string }[] = [
  { value: "once", label: "Once" },
  { value: "interval", label: "Interval" },
  { value: "daily", label: "Daily" },
  { value: "weekly", label: "Weekly" },
  { value: "cron", label: "Cron" },
];

function ScheduleFormDialog({
  open,
  onOpenChange,
  editingId,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  editingId: string | null;
}) {
  const queryClient = useQueryClient();
  const [formDefaults] = useState(loadFormDefaults);
  const [name, setName] = useState(() => formDefaults.name ?? "");
  const [scheduleType, setScheduleType] = useState<ScheduleType>(() => formDefaults.scheduleType ?? "interval");
  const [runAt, setRunAt] = useState(() => formDefaults.runAt ?? "");
  const [intervalMinutes, setIntervalMinutes] = useState(() => formDefaults.intervalMinutes ?? 60);
  const [time, setTime] = useState(() => formDefaults.time ?? "09:00");
  const [days, setDays] = useState<string[]>(() => formDefaults.days ?? DAYS_OF_WEEK.map((d) => d.value));
  const [day, setDay] = useState(() => formDefaults.day ?? "mon");
  const [cronExpression, setCronExpression] = useState(() => formDefaults.cronExpression ?? "0 9 * * *");
  const [timezone, setTimezone] = useState(() => formDefaults.timezone ?? Intl.DateTimeFormat().resolvedOptions().timeZone);
  const [submitting, setSubmitting] = useState(false);
  const [showScanConfig, setShowScanConfig] = useState(false);

  const [saved] = useState(loadSavedSettings);
  const [provider, setProvider] = useState(() => formDefaults.provider ?? saved.provider ?? "anthropic");
  const [llmApiKey, setLlmApiKey] = useState(() => formDefaults.llmApiKey ?? saved.llm_api_key ?? "");
  const [backendUrl, setBackendUrl] = useState(() => formDefaults.backendUrl ?? saved.backend_url ?? "http://localhost:4141");
  const [deepModel, setDeepModel] = useState(() => formDefaults.deepModel ?? saved.deep_think_llm ?? "");
  const [quickModel, setQuickModel] = useState(() => formDefaults.quickModel ?? saved.quick_think_llm ?? "");
  const [klineInterval, setKlineInterval] = useState<CryptoInterval>(() => formDefaults.klineInterval ?? "D");
  const [analysts, setAnalysts] = useState<string[]>(() => formDefaults.analysts ?? [...CRYPTO_ANALYSTS]);
  const [researchDepth, setResearchDepth] = useState(() => formDefaults.researchDepth ?? 3);
  const [outputLanguage, setOutputLanguage] = useState(() => formDefaults.outputLanguage ?? "English");
  const [maxDebateRounds, setMaxDebateRounds] = useState(() => formDefaults.maxDebateRounds ?? 1);
  const [maxRiskRounds, setMaxRiskRounds] = useState(() => formDefaults.maxRiskRounds ?? 1);
  const [maxRecurLimit, setMaxRecurLimit] = useState(() => formDefaults.maxRecurLimit ?? 100);
  const [maxParallel, setMaxParallel] = useState(() => formDefaults.maxParallel ?? 10);
  const [workflowMode, setWorkflowMode] = useState<"quick_trade" | "deep_analysis">(() => formDefaults.workflowMode ?? "deep_analysis");
  const [taPrefilterEnabled, setTaPrefilterEnabled] = useState(() => formDefaults.taPrefilterEnabled ?? false);
  const [taPrefilterThreshold, setTaPrefilterThreshold] = useState(() => formDefaults.taPrefilterThreshold ?? 40);
  const [checkpointEnabled, setCheckpointEnabled] = useState(() => formDefaults.checkpointEnabled ?? false);
  const [llmMaxConcurrent, setLlmMaxConcurrent] = useState(() => formDefaults.llmMaxConcurrent ?? 0);
  const [llmMinSpacingMs, setLlmMinSpacingMs] = useState(() => formDefaults.llmMinSpacingMs ?? 0);
  const [agentModelOverrides, setAgentModelOverrides] = useState<Record<string, string>>(loadOverrides);
  const [autoTradeConfigs, setAutoTradeConfigs] = useState<import("@/api/client").AutoTradeConfig[]>(() => {
    try { return JSON.parse(localStorage.getItem("tradingagents_auto_trade_configs") ?? "[]"); } catch { return []; }
  });
  const [showWorkflowSettings, setShowWorkflowSettings] = useState(false);
  const [showLlmSettings, setShowLlmSettings] = useState(false);

  const [endpoints, setEndpoints] = useState(loadEndpoints);
  const [showEndpoints, setShowEndpoints] = useState(false);
  const endpointsRef = useRef<HTMLDivElement>(null);
  const conn = useConnectivityCheck(backendUrl, llmApiKey || undefined, 800, provider);

  const { data: providersData } = useQuery({
    queryKey: ["providers"],
    queryFn: ({ signal }) => apiClient.getProviders(signal),
    staleTime: 300_000,
  });
  const PROVIDERS = providersData?.providers ?? PROVIDERS_FALLBACK;

  const { data: remoteModels } = useModels(backendUrl, llmApiKey || undefined);
  const remoteIds = (remoteModels ?? []).map((m) => m.id);
  const catalogDeep = getModelOptions(provider, "deep");
  const catalogQuick = getModelOptions(provider, "quick");
  const deepOptions = remoteModels?.length
    ? remoteModels.map((m) => ({ label: m.name ?? m.id, value: m.id }))
    : catalogDeep;
  const quickOptions = remoteModels?.length
    ? remoteModels.map((m) => ({ label: m.name ?? m.id, value: m.id }))
    : catalogQuick;

  useEffect(() => {
    if (backendUrl.trim()) {
      saveEndpoint({ url: backendUrl.trim(), apiKey: llmApiKey, deepModel, quickModel });
      // eslint-disable-next-line react-hooks/set-state-in-effect -- syncing localStorage into state after write
      setEndpoints(loadEndpoints());
    }
  }, [backendUrl, llmApiKey, deepModel, quickModel]);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (endpointsRef.current && !endpointsRef.current.contains(e.target as Node)) setShowEndpoints(false);
    }
    if (showEndpoints) document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [showEndpoints]);

  function selectEndpoint(ep: EndpointProfile) {
    setBackendUrl(ep.url);
    if (ep.apiKey != null) setLlmApiKey(ep.apiKey);
    if (ep.deepModel) setDeepModel(ep.deepModel);
    if (ep.quickModel) setQuickModel(ep.quickModel);
    setShowEndpoints(false);
  }

  function deleteEndpoint(url: string) {
    removeEndpoint(url);
    setEndpoints(loadEndpoints());
  }

  const { data: editData, isLoading: editLoading } = useQuery({
    queryKey: ["scheduled-scan", editingId],
    queryFn: ({ signal }) => editingId ? scheduledScansApi.get(editingId, signal) : null,
    enabled: !!editingId && open,
  });

  useEffect(() => {
    if (editData && editingId) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- populating form from fetched data
      setName(editData.name);
      setScheduleType(editData.schedule_type);
      setTimezone(editData.timezone);
      const cfg = editData.schedule_config;
      if (cfg.run_at) {
        try {
          const d = new Date(cfg.run_at);
          const pad = (n: number) => String(n).padStart(2, "0");
          setRunAt(`${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`);
        } catch { setRunAt(cfg.run_at); }
      }
      if (cfg.interval_minutes != null) setIntervalMinutes(cfg.interval_minutes);
      if (cfg.time) setTime(cfg.time);
      if (cfg.days) setDays(cfg.days);
      if (cfg.day) setDay(cfg.day);
      if (cfg.cron_expression) setCronExpression(cfg.cron_expression);
      const sc = editData.scan_config as Record<string, unknown>;
      if (sc.provider) setProvider(sc.provider as string);
      if (sc.llm_api_key && sc.llm_api_key !== "***") setLlmApiKey(sc.llm_api_key as string);
      if (sc.backend_url) setBackendUrl(sc.backend_url as string);
      if (sc.deep_think_llm) setDeepModel(sc.deep_think_llm as string);
      if (sc.quick_think_llm) setQuickModel(sc.quick_think_llm as string);
      if (sc.interval) setKlineInterval(sc.interval as CryptoInterval);
      if (Array.isArray(sc.analysts)) setAnalysts(sc.analysts as string[]);
      if (sc.research_depth != null) setResearchDepth(sc.research_depth as number);
      if (sc.output_language != null) setOutputLanguage(sc.output_language as string);
      if (sc.max_debate_rounds != null) setMaxDebateRounds(sc.max_debate_rounds as number);
      if (sc.max_risk_discuss_rounds != null) setMaxRiskRounds(sc.max_risk_discuss_rounds as number);
      if (sc.max_recur_limit != null) setMaxRecurLimit(sc.max_recur_limit as number);
      if (sc.max_parallel != null) setMaxParallel(sc.max_parallel as number);
      if (sc.workflow_mode) setWorkflowMode(sc.workflow_mode as "quick_trade" | "deep_analysis");
      if (sc.ta_prefilter_enabled != null) setTaPrefilterEnabled(sc.ta_prefilter_enabled as boolean);
      if (sc.ta_prefilter_threshold != null) setTaPrefilterThreshold(sc.ta_prefilter_threshold as number);
      if (sc.checkpoint_enabled != null) setCheckpointEnabled(sc.checkpoint_enabled as boolean);
      if (sc.llm_max_concurrent != null) setLlmMaxConcurrent(sc.llm_max_concurrent as number);
      if (sc.llm_min_spacing_ms != null) setLlmMinSpacingMs(sc.llm_min_spacing_ms as number);
      if (sc.agent_model_overrides != null && typeof sc.agent_model_overrides === "object") {
        setAgentModelOverrides(sc.agent_model_overrides as Record<string, string>);
      }
      if (Array.isArray(sc.auto_trade_configs)) {
        setAutoTradeConfigs(sc.auto_trade_configs as import("@/api/client").AutoTradeConfig[]);
      }
    }
  }, [editData, editingId]);

  useEffect(() => {
    if (editingId) return;
    saveFormDefaults({
      name, scheduleType, runAt, intervalMinutes, time, days, day,
      cronExpression, timezone, provider, klineInterval, analysts,
      researchDepth, outputLanguage, maxDebateRounds, maxRiskRounds,
      maxRecurLimit, maxParallel, workflowMode, taPrefilterEnabled,
      taPrefilterThreshold, checkpointEnabled, llmMaxConcurrent, llmMinSpacingMs,
      backendUrl, llmApiKey, deepModel, quickModel, autoTradeConfigs,
    });
  }, [
    editingId, name, scheduleType, runAt, intervalMinutes, time, days, day,
    cronExpression, timezone, provider, klineInterval, analysts,
    researchDepth, outputLanguage, maxDebateRounds, maxRiskRounds,
    maxRecurLimit, maxParallel, workflowMode, taPrefilterEnabled,
    taPrefilterThreshold, checkpointEnabled, llmMaxConcurrent, llmMinSpacingMs,
    backendUrl, llmApiKey, deepModel, quickModel, autoTradeConfigs,
  ]);

  function handleOpenChange(v: boolean) {
    if (v) {
      setEndpoints(loadEndpoints());
    }
    if (!v) {
      const fresh = loadSavedSettings();
      const fd = loadFormDefaults();
      setName(fd.name ?? ""); setScheduleType(fd.scheduleType ?? "interval");
      setRunAt(fd.runAt ?? ""); setIntervalMinutes(fd.intervalMinutes ?? 60);
      setTime(fd.time ?? "09:00"); setDays(fd.days ?? DAYS_OF_WEEK.map((d) => d.value));
      setDay(fd.day ?? "mon"); setCronExpression(fd.cronExpression ?? "0 9 * * *");
      setTimezone(fd.timezone ?? Intl.DateTimeFormat().resolvedOptions().timeZone);
      setProvider(fd.provider ?? fresh.provider ?? "anthropic");
      setLlmApiKey(fd.llmApiKey ?? fresh.llm_api_key ?? "");
      setBackendUrl(fd.backendUrl ?? fresh.backend_url ?? "http://localhost:4141");
      setDeepModel(fd.deepModel ?? fresh.deep_think_llm ?? "");
      setQuickModel(fd.quickModel ?? fresh.quick_think_llm ?? "");
      setKlineInterval(fd.klineInterval ?? "D"); setAnalysts(fd.analysts ?? [...CRYPTO_ANALYSTS]);
      setResearchDepth(fd.researchDepth ?? 3); setOutputLanguage(fd.outputLanguage ?? "English");
      setMaxDebateRounds(fd.maxDebateRounds ?? 1); setMaxRiskRounds(fd.maxRiskRounds ?? 1);
      setMaxRecurLimit(fd.maxRecurLimit ?? 100); setMaxParallel(fd.maxParallel ?? 10);
      setWorkflowMode(fd.workflowMode ?? "deep_analysis");
      setTaPrefilterEnabled(fd.taPrefilterEnabled ?? false); setTaPrefilterThreshold(fd.taPrefilterThreshold ?? 40);
      setCheckpointEnabled(fd.checkpointEnabled ?? false);
      setLlmMaxConcurrent(fd.llmMaxConcurrent ?? 0); setLlmMinSpacingMs(fd.llmMinSpacingMs ?? 0);
      setAgentModelOverrides(loadOverrides());
      setAutoTradeConfigs(fd.autoTradeConfigs ?? []);
      setShowScanConfig(false); setShowWorkflowSettings(false); setShowLlmSettings(false); setShowEndpoints(false);
    }
    onOpenChange(v);
  }

  function buildConfig(): ScheduleConfig {
    switch (scheduleType) {
      case "once": return { run_at: runAt ? new Date(runAt).toISOString() : "" };
      case "interval": return { interval_minutes: intervalMinutes };
      case "daily": {
        const dayOrder = DAYS_OF_WEEK.map((d) => d.value);
        const sorted = [...days].sort((a, b) => dayOrder.indexOf(a) - dayOrder.indexOf(b));
        return { time, days: sorted };
      }
      case "weekly": return { day, time };
      case "cron": return { cron_expression: cronExpression };
    }
  }

  async function handleSubmit(e: React.SyntheticEvent) {
    e.preventDefault();
    if (submitting) return;
    if (!name.trim()) { toast.error("Name is required"); return; }
    if (scheduleType === "once" && !runAt) { toast.error("Date/time is required for one-time schedules"); return; }
    if (scheduleType === "once" && runAt) {
      const d = new Date(runAt);
      if (isNaN(d.getTime())) { toast.error("Invalid date/time"); return; }
    }
    if (scheduleType === "daily" && days.length === 0) { toast.error("Select at least one day"); return; }
    if (scheduleType === "cron" && !cronExpression.trim()) { toast.error("Cron expression is required"); return; }
    if (scheduleType === "interval" && (intervalMinutes < 15 || intervalMinutes > 10080)) { toast.error("Interval must be between 15 and 10080 minutes"); return; }
    setSubmitting(true);
    const clamp = (v: number, min: number, max: number) => Math.max(min, Math.min(max, v));
    try {
      const payload: CreateScheduledScanRequest = {
        name: name.trim(),
        schedule_type: scheduleType,
        schedule_config: buildConfig(),
        scan_config: {
          asset_type: "crypto",
          interval: klineInterval,
          provider: provider || undefined,
          llm_api_key: llmApiKey.trim() || undefined,
          deep_think_llm: deepModel.trim() || undefined,
          quick_think_llm: quickModel.trim() || undefined,
          backend_url: backendUrl.trim() || undefined,
          analysts,
          research_depth: clamp(researchDepth, 1, 5),
          output_language: outputLanguage,
          max_debate_rounds: clamp(maxDebateRounds, 1, 10),
          max_risk_discuss_rounds: clamp(maxRiskRounds, 1, 10),
          max_recur_limit: clamp(maxRecurLimit, 1, 500),
          max_parallel: clamp(maxParallel, 1, 25),
          workflow_mode: workflowMode,
          ta_prefilter_enabled: taPrefilterEnabled,
          ta_prefilter_threshold: taPrefilterEnabled ? taPrefilterThreshold : undefined,
          checkpoint_enabled: checkpointEnabled,
          llm_max_concurrent: llmMaxConcurrent,
          llm_min_spacing_ms: llmMinSpacingMs,
          agent_model_overrides: filterOverridesForAssetType(agentModelOverrides, "crypto"),
          auto_trade_configs: autoTradeConfigs.length > 0 ? autoTradeConfigs.filter(c => c.account_id) : undefined,
        },
        timezone,
      };
      if (editingId) {
        await scheduledScansApi.update(editingId, payload);
        toast.success("Schedule updated");
      } else {
        await scheduledScansApi.create(payload);
        toast.success("Schedule created");
        const current = loadFormDefaults();
        saveFormDefaults({ ...current, name: "", runAt: "" });
      }
      queryClient.invalidateQueries({ queryKey: ["scheduled-scans"] });
      if (editingId) queryClient.invalidateQueries({ queryKey: ["scheduled-scan", editingId] });
      handleOpenChange(false);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Failed to save schedule");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="w-[95vw] sm:max-w-2xl lg:max-w-4xl max-h-[85vh] overflow-y-auto custom-scrollbar">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <svg className="w-5 h-5 text-primary" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            {editingId ? "Edit Schedule" : "New Scheduled Scan"}
          </DialogTitle>
          <DialogDescription className="sr-only">Configure schedule timing and scan parameters</DialogDescription>
        </DialogHeader>

        {editingId && editLoading ? (
          <div className="flex items-center justify-center py-12">
            <svg className="w-6 h-6 animate-spin text-muted-foreground" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            <span className="ml-2 text-sm text-muted-foreground">Loading schedule...</span>
          </div>
        ) : (
        <form onSubmit={handleSubmit} className="space-y-5">
          <button type="submit" hidden aria-hidden="true" tabIndex={-1} />
          <div>
            <Label htmlFor="schedule-name" className="text-xs font-medium">Schedule Name</Label>
            <Input id="schedule-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="My daily scan" maxLength={255} className="mt-1.5" />
          </div>

          {/* Schedule type selector */}
          <div>
            <Label className="text-xs font-semibold text-[var(--neu-text-muted)] uppercase tracking-wider">Schedule Type</Label>
            <div className="grid grid-cols-3 sm:grid-cols-5 gap-1.5 mt-1.5">
              {SCHEDULE_TYPES.map((t) => {
                const typeIcon = TYPE_CONFIG[t.value]?.icon ?? "";
                return (
                <button
                  key={t.value}
                  type="button"
                  onClick={() => setScheduleType(t.value)}
                  className={cn(
                    "flex flex-col items-center gap-1 px-2 py-2.5 text-[11px] rounded-[var(--neu-radius-md)] border transition-all duration-150 font-bold uppercase tracking-wider cursor-pointer",
                    scheduleType === t.value
                      ? "bg-[color-mix(in_oklch,var(--neu-accent)_10%,var(--neu-surface-base))] text-[var(--neu-accent)] border-[color-mix(in_oklch,var(--neu-accent)_20%,var(--neu-stroke-soft))] shadow-[var(--neu-shadow-pill)]"
                      : "bg-[var(--neu-surface-raised)] text-[var(--neu-text-muted)] border-[color:var(--neu-stroke-soft)] shadow-[var(--neu-shadow-raised)] hover:shadow-[var(--neu-shadow-raised-hover)] hover:text-[var(--neu-text-strong)]"
                  )}
                >
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5} aria-hidden="true">
                    <path strokeLinecap="round" strokeLinejoin="round" d={typeIcon} />
                  </svg>
                  {t.label}
                </button>
                );
              })}
            </div>
          </div>

          {/* Type-specific fields */}
          {scheduleType === "once" && (
            <div>
              <Label htmlFor="run-at" className="text-xs font-semibold text-[var(--neu-text-muted)] uppercase tracking-wider">Date &amp; Time</Label>
              <Input id="run-at" type="datetime-local" value={runAt} onChange={(e) => setRunAt(e.target.value)} className="mt-1.5" />
            </div>
          )}
          {scheduleType === "interval" && (
            <div>
              <Label htmlFor="interval" className="text-xs font-semibold text-[var(--neu-text-muted)] uppercase tracking-wider">Interval (minutes)</Label>
              <Input id="interval" type="number" min={15} max={10080} value={intervalMinutes} onChange={(e) => setIntervalMinutes(parseInt(e.target.value) || 60)} className="mt-1.5" />
              <p className="text-[11px] text-[var(--neu-text-muted)]/60 mt-1">
                {intervalMinutes >= 60 ? `Every ${(intervalMinutes / 60).toFixed(1)} hours` : `Every ${intervalMinutes} minutes`}
              </p>
            </div>
          )}
          {(scheduleType === "daily" || scheduleType === "weekly") && (
            <div>
              <Label htmlFor="time" className="text-xs font-semibold text-[var(--neu-text-muted)] uppercase tracking-wider">Time</Label>
              <Input id="time" type="time" value={time} onChange={(e) => setTime(e.target.value)} className="mt-1.5" />
            </div>
          )}
          {scheduleType === "daily" && (
            <div>
              <Label className="text-xs font-semibold text-[var(--neu-text-muted)] uppercase tracking-wider">Days</Label>
              <div className="flex gap-1.5 mt-1.5 flex-wrap">
                {DAYS_OF_WEEK.map((d) => (
                  <button
                    key={d.value}
                    type="button"
                    onClick={() => setDays((prev) => prev.includes(d.value) ? prev.filter((x) => x !== d.value) : [...prev, d.value])}
                    className={cn(
                      "w-9 h-9 text-xs rounded-[var(--neu-radius-sm)] border transition-all duration-150 font-bold uppercase cursor-pointer",
                      days.includes(d.value)
                        ? "bg-[color-mix(in_oklch,var(--neu-accent)_10%,var(--neu-surface-base))] text-[var(--neu-accent)] border-[color-mix(in_oklch,var(--neu-accent)_20%,var(--neu-stroke-soft))] shadow-[var(--neu-shadow-pill)]"
                        : "bg-[var(--neu-surface-raised)] text-[var(--neu-text-muted)] border-[color:var(--neu-stroke-soft)] shadow-[var(--neu-shadow-raised)] hover:shadow-[var(--neu-shadow-raised-hover)] hover:text-[var(--neu-text-strong)]"
                    )}
                  >
                    {d.label}
                  </button>
                ))}
              </div>
            </div>
          )}
          {scheduleType === "weekly" && (
            <div>
              <Label className="text-xs font-medium">Day of Week</Label>
              <Select value={day} onValueChange={(v) => v != null && setDay(v)}>
                <SelectTrigger className="mt-1.5"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {DAYS_OF_WEEK.map((d) => (<SelectItem key={d.value} value={d.value}>{d.label}</SelectItem>))}
                </SelectContent>
              </Select>
            </div>
          )}
          {scheduleType === "cron" && (
            <div>
              <Label htmlFor="cron" className="text-xs font-medium">Cron Expression (5-field)</Label>
              <Input id="cron" value={cronExpression} onChange={(e) => setCronExpression(e.target.value)} placeholder="0 9 * * 1-5" className="font-mono mt-1.5" />
              <p className="text-[11px] text-muted-foreground mt-1">minute hour day-of-month month day-of-week</p>
            </div>
          )}

          <div>
            <Label htmlFor="timezone" className="text-xs font-medium">Timezone</Label>
            <Input id="timezone" value={timezone} onChange={(e) => setTimezone(e.target.value)} placeholder="America/New_York" className="mt-1.5" />
          </div>

          {/* Scan Configuration (collapsible) */}
          <CollapsibleSection title="Scan Configuration" open={showScanConfig} onToggle={() => setShowScanConfig(!showScanConfig)}>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              <div className="flex flex-col gap-1.5">
                <Label className="text-xs font-semibold text-[var(--neu-text-muted)] uppercase tracking-wider">LLM Provider</Label>
                <Select value={provider} onValueChange={(v) => v != null && setProvider(v)}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>{PROVIDERS.map((p) => (<SelectItem key={p} value={p}>{p}</SelectItem>))}</SelectContent>
                </Select>
              </div>
              <div className="flex flex-col gap-1.5">
                <Label className="text-xs font-semibold text-[var(--neu-text-muted)] uppercase tracking-wider">Kline Interval</Label>
                <Select value={klineInterval} onValueChange={(v) => setKlineInterval(v as CryptoInterval)}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>{CRYPTO_INTERVALS.map((i) => (<SelectItem key={i.value} value={i.value}>{i.label}</SelectItem>))}</SelectContent>
                </Select>
              </div>
              <div className="flex flex-col gap-1.5">
                <Label className="text-xs font-semibold text-[var(--neu-text-muted)] uppercase tracking-wider">Output Language</Label>
                <Select value={outputLanguage} onValueChange={(v) => v != null && setOutputLanguage(v)}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>{LANGUAGES.map((l) => (<SelectItem key={l} value={l}>{l}</SelectItem>))}</SelectContent>
                </Select>
              </div>
            </div>
            <div className="flex flex-col gap-1.5">
              <Label className="text-xs font-semibold text-[var(--neu-text-muted)] uppercase tracking-wider">Workflow Mode</Label>
              <div className="grid grid-cols-2 gap-1 rounded-[var(--neu-radius-md)] bg-[var(--neu-surface-muted)] p-1 shadow-[var(--neu-shadow-inset)] border-none">
                {(
                  [
                    { value: "quick_trade" as const, label: "Quick Trade" },
                    { value: "deep_analysis" as const, label: "Deep Analysis" },
                  ] as const
                ).map((opt) => (
                  <button
                    key={opt.value}
                    type="button"
                    className={cn(
                      "flex min-h-9 items-center justify-center rounded-[var(--neu-radius-sm)] px-3 py-1.5 text-[11px] font-bold uppercase tracking-wider transition-all duration-200 cursor-pointer border-none",
                      workflowMode === opt.value
                        ? "bg-[var(--neu-surface-base)] text-[var(--neu-text-strong)] shadow-[var(--neu-shadow-raised-soft)]"
                        : "text-[var(--neu-text-muted)] hover:text-[var(--neu-text-strong)] hover:bg-[color-mix(in_oklch,var(--neu-accent)_8%,var(--neu-surface-base))]"
                    )}
                    onClick={() => setWorkflowMode(opt.value)}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            </div>
            <div className="space-y-3">
              <NeuSwitch
                checked={taPrefilterEnabled}
                onChange={setTaPrefilterEnabled}
                label="Smart Pre-Screen"
                description="Filter low-conviction assets before LLM debate."
                className="neu-surface-base neu-surface-raised rounded-[var(--neu-radius-md)] border-none shadow-[var(--shadow-card)] px-3.5 py-3.5"
              />
              {taPrefilterEnabled && (
                <div className="neu-surface-base neu-surface-raised rounded-[var(--neu-radius-md)] border-none shadow-[var(--shadow-card)] flex flex-wrap items-center gap-3 px-4 py-3 bg-[color-mix(in_oklch,var(--neu-accent)_8%,var(--neu-surface-base))]">
                  <Label htmlFor="sched_ta_threshold" className="text-[10px] font-bold uppercase tracking-wider text-[var(--neu-text-muted)]">Threshold</Label>
                  <Input
                    id="sched_ta_threshold"
                    type="number"
                    min={0}
                    max={100}
                    value={taPrefilterThreshold}
                    onChange={(e) => setTaPrefilterThreshold(Number(e.target.value))}
                    className="h-10 w-24"
                  />
                  <span className="inline-flex items-center rounded-full border border-transparent shadow-[var(--neu-shadow-pill)] bg-[var(--neu-surface-muted)] px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.18em] text-[var(--neu-text-muted)]">/ 100</span>
                </div>
              )}
            </div>
            <div className="flex flex-col gap-1.5">
              <Label className="text-xs font-semibold text-[var(--neu-text-muted)] uppercase tracking-wider">Analyst Team</Label>
              <div className="flex flex-wrap gap-2.5">
                {CRYPTO_ANALYSTS.map((a) => {
                  const active = analysts.includes(a);
                  return (
                    <button
                      key={a}
                      type="button"
                      onClick={() => setAnalysts((prev) => active ? prev.filter((x) => x !== a) : [...prev, a])}
                      className={cn(
                        "px-3 py-1.5 text-[10px] font-bold uppercase tracking-wider rounded-[var(--neu-radius-pill)] border transition-all duration-150 cursor-pointer shadow-[var(--neu-shadow-pill)] hover:translate-y-[-1px]",
                        active
                          ? "bg-[color-mix(in_oklch,var(--neu-accent)_10%,var(--neu-surface-base))] text-[var(--neu-accent)] border-[color-mix(in_oklch,var(--neu-accent)_20%,var(--neu-stroke-soft))]"
                          : "bg-[var(--neu-surface-raised)] text-[var(--neu-text-muted)] border-[color:var(--neu-stroke-soft)] hover:text-[var(--neu-text-strong)] hover:shadow-[var(--neu-shadow-raised-hover)]"
                      )}
                    >
                      {a.replace("crypto_", "")}
                    </button>
                  );
                })}
              </div>
            </div>
          </CollapsibleSection>

          {/* Workflow Settings (collapsible) */}
          <CollapsibleSection title="Workflow Settings" open={showWorkflowSettings} onToggle={() => setShowWorkflowSettings(!showWorkflowSettings)}>
            <div className="rounded-[var(--neu-radius-md)] bg-[var(--neu-surface-muted)] shadow-[var(--neu-shadow-inset)] p-4 border-none flex flex-col gap-2">
              <Label className="text-xs font-semibold text-[var(--neu-text-muted)] uppercase tracking-wider">Research Depth</Label>
              <div className="flex items-center gap-3">
                <input
                  type="range"
                  min={1}
                  max={5}
                  step={1}
                  value={researchDepth}
                  onChange={(e) => setResearchDepth(Number(e.target.value))}
                  className="neu-slider flex-1"
                />
                <span className="rounded-full border border-[color:var(--neu-stroke-soft)] bg-[var(--neu-surface-base)] px-3 py-1 font-mono text-[var(--neu-text-strong)] shadow-[var(--neu-shadow-pill)] text-xs text-center w-8">
                  {researchDepth}
                </span>
              </div>
              <p className="text-[10px] text-[var(--neu-text-muted)]/60 font-semibold uppercase">1 = Quick scan, 5 = Deep analysis</p>
            </div>
            <div className={`grid ${workflowMode === "quick_trade" ? "grid-cols-1" : "grid-cols-2"} gap-3`}>
              <div className="flex flex-col gap-1.5">
                <Label className="text-xs font-semibold text-[var(--neu-text-muted)] uppercase tracking-wider">Max Debate Rounds</Label>
                <Input type="number" min={1} max={10} value={maxDebateRounds} onChange={(e) => setMaxDebateRounds(Number(e.target.value))} />
              </div>
              {workflowMode !== "quick_trade" && (
                <div className="flex flex-col gap-1.5">
                  <Label className="text-xs font-semibold text-[var(--neu-text-muted)] uppercase tracking-wider">Max Risk Rounds</Label>
                  <Input type="number" min={1} max={10} value={maxRiskRounds} onChange={(e) => setMaxRiskRounds(Number(e.target.value))} />
                </div>
              )}
            </div>
            <div className="flex flex-col gap-1.5">
              <Label className="text-xs font-semibold text-[var(--neu-text-muted)] uppercase tracking-wider">Max Recursion Limit</Label>
              <Input type="number" min={1} max={500} value={maxRecurLimit} onChange={(e) => setMaxRecurLimit(Number(e.target.value))} className="w-32" />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label className="text-xs font-semibold text-[var(--neu-text-muted)] uppercase tracking-wider">Max Parallel Analyses</Label>
              <Input type="number" min={1} max={25} value={maxParallel} onChange={(e) => setMaxParallel(Math.min(25, Math.max(1, Number(e.target.value))))} className="w-32" />
            </div>
            <NeuSwitch
              checked={checkpointEnabled}
              onChange={setCheckpointEnabled}
              label="Enable Checkpoints"
              description="Save state after each step so crashed runs can resume."
              className="neu-surface-base neu-surface-raised rounded-[var(--neu-radius-md)] border-none shadow-[var(--shadow-card)] px-3.5 py-3.5"
            />
          </CollapsibleSection>

          {/* LLM & Proxy Settings (collapsible) */}
          <CollapsibleSection title="LLM & Proxy Settings" open={showLlmSettings} onToggle={() => setShowLlmSettings(!showLlmSettings)}>
            <div className="flex flex-col gap-1.5">
              <div className="flex items-center justify-between">
                <Label className="text-xs font-medium">Backend URL / Proxy Endpoint</Label>
                <ConnBadge status={conn.status} latency={conn.latency} error={conn.errorMsg} />
              </div>
              <div className="relative" ref={endpointsRef}>
                <Input
                  value={backendUrl}
                  onChange={(e) => setBackendUrl(e.target.value)}
                  onFocus={() => endpoints.length > 1 && setShowEndpoints(true)}
                  placeholder="Enter your LLM provider override URL"
                  className="text-xs pr-9 placeholder:text-muted-foreground/40"
                />
                {endpoints.length > 1 && (
                  <button
                    type="button"
                    onClick={() => setShowEndpoints(!showEndpoints)}
                    className="absolute right-2 top-1/2 -translate-y-1/2 p-1 rounded hover:bg-muted transition-colors"
                  >
                    <svg className={cn("w-4 h-4 text-muted-foreground transition-transform", showEndpoints && "rotate-180")} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                    </svg>
                  </button>
                )}
                {showEndpoints && endpoints.length > 1 && (
                  <div className="absolute z-50 mt-1.5 w-full rounded-[var(--neu-radius-md)] border border-[color:var(--neu-stroke-soft)] bg-[var(--neu-surface-raised)] shadow-[var(--neu-shadow-float)] overflow-hidden max-h-48 overflow-y-auto backdrop-blur-xl">
                    {endpoints.map((ep) => (
                      <div
                        key={ep.url}
                        className={cn(
                          "flex items-center justify-between px-3 py-2 text-sm cursor-pointer hover:bg-[color-mix(in_oklch,var(--neu-accent)_8%,var(--neu-surface-base))] transition-colors",
                          ep.url === backendUrl && "bg-[color-mix(in_oklch,var(--neu-accent)_10%,var(--neu-surface-base))] text-[var(--neu-accent)] font-semibold",
                        )}
                      >
                        <button
                          type="button"
                          className="flex-1 text-left truncate font-mono text-xs"
                          onClick={() => selectEndpoint(ep)}
                        >
                          {ep.url}
                          {ep.deepModel && <span className="ml-2 text-muted-foreground">({ep.deepModel})</span>}
                        </button>
                        {ep.url !== backendUrl && (
                          <button
                            type="button"
                            onClick={(e) => { e.stopPropagation(); deleteEndpoint(ep.url); }}
                            className="ml-2 p-1 rounded hover:bg-destructive/10 text-muted-foreground hover:text-destructive transition-colors shrink-0"
                            title="Remove endpoint"
                          >
                            <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                            </svg>
                          </button>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
              <p className="text-[11px] text-muted-foreground">
                Custom API endpoint. Models are fetched from <code className="text-[10px] px-1 py-0.5 rounded bg-muted">/v1/models</code> automatically.
                {remoteIds.length > 0 && (
                  <span className="ml-1 text-primary">{remoteIds.length} models loaded</span>
                )}
              </p>
            </div>
            <div className="flex flex-col gap-1.5">
              <div className="flex items-center justify-between">
                <Label className="text-xs font-medium">API Key</Label>
                {llmApiKey.trim() && <ConnBadge status={conn.status} latency={null} error={conn.errorMsg} label="Authenticated" />}
              </div>
              <Input type="password" value={llmApiKey} onChange={(e) => setLlmApiKey(e.target.value)} placeholder="Provider API key (optional)" className="text-xs" />
              <p className="text-[11px] text-muted-foreground">Optional. Overrides the environment variable for the selected provider.</p>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div className="flex flex-col gap-1.5">
                <Label className="text-xs font-medium">Deep Think Model</Label>
                <ModelSelect options={deepOptions} value={deepModel} onChange={(v) => setDeepModel(v ?? "")} placeholder="Select model..." />
                <p className="text-[11px] text-muted-foreground">Model for complex reasoning tasks</p>
              </div>
              <div className="flex flex-col gap-1.5">
                <Label className="text-xs font-medium">Quick Think Model</Label>
                <ModelSelect options={quickOptions} value={quickModel} onChange={(v) => setQuickModel(v ?? "")} placeholder="Select model..." />
                <p className="text-[11px] text-muted-foreground">Model for fast, lightweight tasks</p>
              </div>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div className="flex flex-col gap-1">
                <Label className="text-xs font-medium">LLM Concurrency Limit</Label>
                <Input type="number" min={0} max={100} value={llmMaxConcurrent} onChange={(e) => setLlmMaxConcurrent(Number(e.target.value))} className="w-28 text-xs" />
                <p className="text-[11px] text-muted-foreground">0 = unlimited</p>
              </div>
              <div className="flex flex-col gap-1">
                <Label className="text-xs font-medium">Min Spacing (ms)</Label>
                <Input type="number" min={0} max={60000} value={llmMinSpacingMs} onChange={(e) => setLlmMinSpacingMs(Number(e.target.value))} className="w-28 text-xs" />
                <p className="text-[11px] text-muted-foreground">0 = no delay</p>
              </div>
            </div>
          </CollapsibleSection>

          {/* Agent Model Overrides */}
          <AgentModelOverrides assetType="crypto" modelOptions={deepOptions} overrides={agentModelOverrides} onChange={setAgentModelOverrides} />

          {/* Auto-Trade */}
          <AutoTradeSection value={autoTradeConfigs} onChange={setAutoTradeConfigs} />

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => handleOpenChange(false)}>Cancel</Button>
            <Button disabled={submitting || (!!editingId && editLoading)} onClick={handleSubmit}>
              {submitting ? "Saving..." : editingId ? "Update" : "Create"}
            </Button>
          </DialogFooter>
        </form>
        )}
      </DialogContent>
    </Dialog>
  );
}

function CollapsibleSection({ title, open, onToggle, children }: { title: string; open: boolean; onToggle: () => void; children: React.ReactNode }) {
  return (
    <div className="neu-surface-base neu-surface-raised rounded-[var(--neu-radius-lg)] border-none shadow-[var(--shadow-card)] overflow-hidden">
      <button
        type="button"
        onClick={onToggle}
        className="flex items-center gap-2 text-sm font-semibold text-[var(--neu-text-muted)] hover:text-[var(--neu-text-strong)] hover:bg-[color-mix(in_oklch,var(--neu-accent)_4%,var(--neu-surface-base))] transition-colors w-full px-4 py-3 cursor-pointer"
      >
        <svg className={cn("w-4 h-4 transition-transform duration-200", open && "rotate-90")} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
        </svg>
        {title}
      </button>
      {open && <div className="px-4 pb-4 space-y-3 border-t border-[color:var(--neu-stroke-soft)] pt-3 bg-[var(--neu-surface-base)]">{children}</div>}
    </div>
  );
}
