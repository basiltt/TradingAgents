import { useState, useEffect } from "react";
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
import { getModelOptions } from "@/lib/model-catalog";
import { cn } from "@/lib/utils";
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

const STATUS_COLORS: Record<string, string> = {
  active: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  paused: "bg-yellow-500/15 text-yellow-400 border-yellow-500/30",
  completed: "bg-zinc-500/15 text-zinc-400 border-zinc-500/30",
  error: "bg-red-500/15 text-red-400 border-red-500/30",
};

const TYPE_LABELS: Record<string, string> = {
  once: "One-time",
  interval: "Interval",
  daily: "Daily",
  weekly: "Weekly",
  cron: "Cron",
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
      return cfg.run_at ? `At ${formatDate(cfg.run_at)}` : "One-time";
    case "interval":
      return cfg.interval_minutes
        ? cfg.interval_minutes >= 60
          ? `Every ${Number((cfg.interval_minutes / 60).toFixed(1))}h`
          : `Every ${cfg.interval_minutes}m`
        : "Interval";
    case "daily":
      return `${cfg.time ?? "09:00"} on ${(cfg.days ?? []).join(", ")}`;
    case "weekly":
      return `${cfg.day ?? "mon"} at ${cfg.time ?? "09:00"}`;
    case "cron":
      return cfg.cron_expression ?? "Cron";
    default:
      return s.schedule_type;
  }
}

export function ScheduledScansPage() {
  const queryClient = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);
  const [pendingActionIds, setPendingActionIds] = useState<Set<string>>(new Set());

  const { data, isLoading, error } = useQuery({
    queryKey: ["scheduled-scans"],
    queryFn: ({ signal }) => scheduledScansApi.list(signal),
    refetchInterval: 10_000,
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
    onError: (e) => toast.error(`Failed to trigger: ${e.message}`),
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
      <div className="p-6 text-center text-red-400">
        Failed to load schedules: {(error as Error).message}
      </div>
    );
  }

  return (
    <div className="p-4 md:p-6 max-w-5xl mx-auto space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-foreground">
          Scheduled Scans
        </h1>
        <Button onClick={openCreate} size="sm">
          + New Schedule
        </Button>
      </div>

      {isLoading ? (
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-20 w-full rounded-lg" />
          ))}
        </div>
      ) : schedules.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 text-center text-muted-foreground">
          <svg
            className="w-12 h-12 mb-4 opacity-30"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={1.5}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z"
            />
          </svg>
          <p className="text-sm mb-3">No scheduled scans yet</p>
          <Button onClick={openCreate} variant="outline" size="sm">
            Create your first scheduled scan
          </Button>
        </div>
      ) : (
        <div className="space-y-2">
          {schedules.map((s) => (
            <div
              key={s.id}
              className="flex items-center gap-4 rounded-lg border border-border/50 bg-card p-4 hover:border-border transition-colors"
            >
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  <span className="font-medium text-sm text-foreground truncate">
                    {s.name}
                  </span>
                  <span
                    className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider ${STATUS_COLORS[s.status] ?? STATUS_COLORS.completed}`}
                  >
                    {s.status}
                  </span>
                  <span className="text-[10px] text-muted-foreground/60 uppercase tracking-wider">
                    {TYPE_LABELS[s.schedule_type] ?? s.schedule_type}
                  </span>
                </div>
                <p className="text-xs text-muted-foreground">
                  {scheduleDescription(s)}
                </p>
              </div>

              <div className="hidden sm:flex flex-col items-end text-xs text-muted-foreground gap-0.5">
                <span>Next: {relativeTime(s.next_run_at)}</span>
                <span>Last: {relativeTime(s.last_run_at)}</span>
              </div>

              {s.consecutive_failures > 0 && (
                <span className="text-[10px] text-red-400">
                  {s.consecutive_failures} fail{s.consecutive_failures > 1 ? "s" : ""}
                </span>
              )}

              <div className="flex items-center gap-1">
                {s.status === "active" ? (
                  <button
                    onClick={() => pauseMut.mutate(s.id)}
                    className="p-1.5 rounded hover:bg-muted text-muted-foreground hover:text-yellow-400 transition-colors disabled:opacity-50"
                    aria-label="Pause"
                    disabled={pendingActionIds.has(s.id)}
                  >
                    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M10 9v6m4-6v6" />
                    </svg>
                  </button>
                ) : s.status === "paused" || s.status === "error" ? (
                  <button
                    onClick={() => resumeMut.mutate(s.id)}
                    className="p-1.5 rounded hover:bg-muted text-muted-foreground hover:text-emerald-400 transition-colors disabled:opacity-50"
                    aria-label="Resume"
                    disabled={pendingActionIds.has(s.id)}
                  >
                    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                    </svg>
                  </button>
                ) : null}

                <button
                  onClick={() => triggerMut.mutate(s.id)}
                  className="p-1.5 rounded hover:bg-muted text-muted-foreground hover:text-blue-400 transition-colors disabled:opacity-50"
                  aria-label="Run Now"
                  disabled={s.status === "completed" || pendingActionIds.has(s.id)}
                >
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
                  </svg>
                </button>

                <button
                  onClick={() => openEdit(s.id)}
                  className="p-1.5 rounded hover:bg-muted text-muted-foreground hover:text-foreground transition-colors"
                  aria-label="Edit"
                >
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                  </svg>
                </button>

                <button
                  onClick={() => setDeleteConfirm(s.id)}
                  className="p-1.5 rounded hover:bg-muted text-muted-foreground hover:text-red-400 transition-colors"
                  aria-label="Delete"
                >
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                  </svg>
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Delete confirmation */}
      <Dialog open={!!deleteConfirm} onOpenChange={() => setDeleteConfirm(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete Schedule</DialogTitle>
            <DialogDescription>
              This will permanently delete this schedule and all its execution
              history. This action cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setDeleteConfirm(null)}
            >
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
  const [name, setName] = useState("");
  const [scheduleType, setScheduleType] = useState<ScheduleType>("interval");
  const [runAt, setRunAt] = useState("");
  const [intervalMinutes, setIntervalMinutes] = useState(60);
  const [time, setTime] = useState("09:00");
  const [days, setDays] = useState<string[]>(DAYS_OF_WEEK.map((d) => d.value));
  const [day, setDay] = useState("mon");
  const [cronExpression, setCronExpression] = useState("0 9 * * *");
  const [timezone, setTimezone] = useState(
    Intl.DateTimeFormat().resolvedOptions().timeZone,
  );
  const [submitting, setSubmitting] = useState(false);
  const [showScanConfig, setShowScanConfig] = useState(false);

  // Scan config state — defaults from localStorage (same as ScannerPage)
  const [saved] = useState(loadSavedSettings);
  const [provider, setProvider] = useState(saved.provider ?? "anthropic");
  const [llmApiKey, setLlmApiKey] = useState(saved.llm_api_key ?? "");
  const [backendUrl, setBackendUrl] = useState(saved.backend_url ?? "http://localhost:4141");
  const [deepModel, setDeepModel] = useState(saved.deep_think_llm ?? "");
  const [quickModel, setQuickModel] = useState(saved.quick_think_llm ?? "");
  const [klineInterval, setKlineInterval] = useState<CryptoInterval>("D");
  const [analysts, setAnalysts] = useState<string[]>([...CRYPTO_ANALYSTS]);
  const [researchDepth, setResearchDepth] = useState(3);
  const [outputLanguage, setOutputLanguage] = useState("English");
  const [maxDebateRounds, setMaxDebateRounds] = useState(1);
  const [maxRiskRounds, setMaxRiskRounds] = useState(1);
  const [maxRecurLimit, setMaxRecurLimit] = useState(100);
  const [maxParallel, setMaxParallel] = useState(10);
  const [workflowMode, setWorkflowMode] = useState<"quick_trade" | "deep_analysis">("deep_analysis");
  const [taPrefilterEnabled, setTaPrefilterEnabled] = useState(false);
  const [taPrefilterThreshold, setTaPrefilterThreshold] = useState(40);

  // Providers list from API
  const { data: providersData } = useQuery({
    queryKey: ["providers"],
    queryFn: ({ signal }) => apiClient.getProviders(signal),
    staleTime: 300_000,
  });
  const PROVIDERS = providersData?.providers ?? PROVIDERS_FALLBACK;

  // Model options
  const { data: remoteModels } = useModels(backendUrl, llmApiKey);
  const remoteIds = (remoteModels ?? []).map((m) => m.id);
  const catalogDeep = getModelOptions(provider, "deep");
  const catalogQuick = getModelOptions(provider, "quick");
  const deepOptions = remoteIds.length > 0
    ? remoteIds.map((id) => ({ label: id, value: id }))
    : catalogDeep;
  const quickOptions = remoteIds.length > 0
    ? remoteIds.map((id) => ({ label: id, value: id }))
    : catalogQuick;

  const { data: editData, isLoading: editLoading } = useQuery({
    queryKey: ["scheduled-scan", editingId],
    queryFn: ({ signal }) =>
      editingId ? scheduledScansApi.get(editingId, signal) : null,
    enabled: !!editingId && open,
  });

  // Populate form when editing
  useEffect(() => {
    if (editData && editingId) {
      setName(editData.name);
      setScheduleType(editData.schedule_type);
      setTimezone(editData.timezone);
      const cfg = editData.schedule_config;
      if (cfg.run_at) {
        try {
          const d = new Date(cfg.run_at);
          const pad = (n: number) => String(n).padStart(2, "0");
          setRunAt(`${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`);
        } catch {
          setRunAt(cfg.run_at);
        }
      }
      if (cfg.interval_minutes != null) setIntervalMinutes(cfg.interval_minutes);
      if (cfg.time) setTime(cfg.time);
      if (cfg.days) setDays(cfg.days);
      if (cfg.day) setDay(cfg.day);
      if (cfg.cron_expression) setCronExpression(cfg.cron_expression);
      // Populate scan config
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
    }
  }, [editData, editingId]);

  // Reset when closing
  function handleOpenChange(v: boolean) {
    if (!v) {
      setName("");
      setScheduleType("interval");
      setRunAt("");
      setIntervalMinutes(60);
      setTime("09:00");
      setDays(DAYS_OF_WEEK.map((d) => d.value));
      setDay("mon");
      setCronExpression("0 9 * * *");
      setTimezone(Intl.DateTimeFormat().resolvedOptions().timeZone);
      // Reset scan config to defaults
      setProvider(saved.provider ?? "anthropic");
      setLlmApiKey(saved.llm_api_key ?? "");
      setBackendUrl(saved.backend_url ?? "http://localhost:4141");
      setDeepModel(saved.deep_think_llm ?? "");
      setQuickModel(saved.quick_think_llm ?? "");
      setKlineInterval("D");
      setAnalysts([...CRYPTO_ANALYSTS]);
      setResearchDepth(3);
      setOutputLanguage("English");
      setMaxDebateRounds(1);
      setMaxRiskRounds(1);
      setMaxRecurLimit(100);
      setMaxParallel(10);
      setWorkflowMode("deep_analysis");
      setTaPrefilterEnabled(false);
      setTaPrefilterThreshold(40);
      setShowScanConfig(false);
    }
    onOpenChange(v);
  }

  function buildConfig(): ScheduleConfig {
    switch (scheduleType) {
      case "once":
        return { run_at: runAt ? new Date(runAt).toISOString() : "" };
      case "interval":
        return { interval_minutes: intervalMinutes };
      case "daily":
        return { time, days };
      case "weekly":
        return { day, time };
      case "cron":
        return { cron_expression: cronExpression };
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) {
      toast.error("Name is required");
      return;
    }
    if (scheduleType === "once" && !runAt) {
      toast.error("Date/time is required for one-time schedules");
      return;
    }
    if (scheduleType === "daily" && days.length === 0) {
      toast.error("Select at least one day");
      return;
    }
    if (scheduleType === "cron" && !cronExpression.trim()) {
      toast.error("Cron expression is required");
      return;
    }
    setSubmitting(true);
    try {
      const payload: CreateScheduledScanRequest = {
        name: name.trim(),
        schedule_type: scheduleType,
        schedule_config: buildConfig(),
        scan_config: {
          asset_type: "crypto",
          interval: klineInterval,
          provider: provider || undefined,
          llm_api_key: llmApiKey || undefined,
          deep_think_llm: deepModel || undefined,
          quick_think_llm: quickModel || undefined,
          backend_url: backendUrl || undefined,
          analysts,
          research_depth: researchDepth,
          output_language: outputLanguage,
          max_debate_rounds: maxDebateRounds,
          max_risk_discuss_rounds: maxRiskRounds,
          max_recur_limit: maxRecurLimit,
          max_parallel: maxParallel,
          workflow_mode: workflowMode,
          ta_prefilter_enabled: taPrefilterEnabled,
          ta_prefilter_threshold: taPrefilterEnabled ? taPrefilterThreshold : undefined,
        },
        timezone,
      };

      if (editingId) {
        await scheduledScansApi.update(editingId, payload);
        toast.success("Schedule updated");
      } else {
        await scheduledScansApi.create(payload);
        toast.success("Schedule created");
      }
      queryClient.invalidateQueries({ queryKey: ["scheduled-scans"] });
      if (editingId) {
        queryClient.invalidateQueries({ queryKey: ["scheduled-scan", editingId] });
      }
      handleOpenChange(false);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Failed to save schedule");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {editingId ? "Edit Schedule" : "New Scheduled Scan"}
          </DialogTitle>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <Label htmlFor="schedule-name">Name</Label>
            <Input
              id="schedule-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="My daily scan"
              maxLength={255}
            />
          </div>

          <div>
            <Label>Schedule Type</Label>
            <div className="flex gap-1 mt-1">
              {SCHEDULE_TYPES.map((t) => (
                <button
                  key={t.value}
                  type="button"
                  onClick={() => setScheduleType(t.value)}
                  className={`px-3 py-1.5 text-xs rounded-md border transition-colors ${
                    scheduleType === t.value
                      ? "bg-primary text-primary-foreground border-primary"
                      : "bg-muted/50 text-muted-foreground border-border hover:bg-muted"
                  }`}
                >
                  {t.label}
                </button>
              ))}
            </div>
          </div>

          {scheduleType === "once" && (
            <div>
              <Label htmlFor="run-at">Date & Time</Label>
              <Input
                id="run-at"
                type="datetime-local"
                value={runAt}
                onChange={(e) => setRunAt(e.target.value)}
              />
            </div>
          )}

          {scheduleType === "interval" && (
            <div>
              <Label htmlFor="interval">Interval (minutes)</Label>
              <Input
                id="interval"
                type="number"
                min={15}
                max={10080}
                value={intervalMinutes}
                onChange={(e) =>
                  setIntervalMinutes(parseInt(e.target.value) || 60)
                }
              />
              <p className="text-xs text-muted-foreground mt-1">
                {intervalMinutes >= 60
                  ? `Every ${(intervalMinutes / 60).toFixed(1)} hours`
                  : `Every ${intervalMinutes} minutes`}
              </p>
            </div>
          )}

          {(scheduleType === "daily" || scheduleType === "weekly") && (
            <div>
              <Label htmlFor="time">Time</Label>
              <Input
                id="time"
                type="time"
                value={time}
                onChange={(e) => setTime(e.target.value)}
              />
            </div>
          )}

          {scheduleType === "daily" && (
            <div>
              <Label>Days</Label>
              <div className="flex gap-1 mt-1 flex-wrap">
                {DAYS_OF_WEEK.map((d) => (
                  <button
                    key={d.value}
                    type="button"
                    onClick={() =>
                      setDays((prev) =>
                        prev.includes(d.value)
                          ? prev.filter((x) => x !== d.value)
                          : [...prev, d.value],
                      )
                    }
                    className={`px-2.5 py-1 text-xs rounded border transition-colors ${
                      days.includes(d.value)
                        ? "bg-primary text-primary-foreground border-primary"
                        : "bg-muted/50 text-muted-foreground border-border hover:bg-muted"
                    }`}
                  >
                    {d.label}
                  </button>
                ))}
              </div>
            </div>
          )}

          {scheduleType === "weekly" && (
            <div>
              <Label>Day of Week</Label>
              <Select value={day} onValueChange={setDay}>
                <SelectTrigger className="mt-1">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {DAYS_OF_WEEK.map((d) => (
                    <SelectItem key={d.value} value={d.value}>
                      {d.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}

          {scheduleType === "cron" && (
            <div>
              <Label htmlFor="cron">Cron Expression (5-field)</Label>
              <Input
                id="cron"
                value={cronExpression}
                onChange={(e) => setCronExpression(e.target.value)}
                placeholder="0 9 * * 1-5"
                className="font-mono"
              />
              <p className="text-xs text-muted-foreground mt-1">
                minute hour day-of-month month day-of-week
              </p>
            </div>
          )}

          <div>
            <Label htmlFor="timezone">Timezone</Label>
            <Input
              id="timezone"
              value={timezone}
              onChange={(e) => setTimezone(e.target.value)}
              placeholder="America/New_York"
            />
          </div>

          {/* ── Scan Configuration (collapsible) ── */}
          <div className="rounded-lg border border-border/40">
            <button
              type="button"
              onClick={() => setShowScanConfig(!showScanConfig)}
              className="flex items-center gap-2 text-sm font-medium text-muted-foreground hover:text-foreground transition-colors w-full px-4 py-3"
            >
              <svg className={cn("w-4 h-4 transition-transform duration-200", showScanConfig && "rotate-90")} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
              </svg>
              Scan Configuration
            </button>
            {showScanConfig && (
              <div className="px-4 pb-4 space-y-4">
                {/* Provider + Interval + Workflow Mode */}
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                  <div className="flex flex-col gap-1.5">
                    <Label className="text-xs font-medium">LLM Provider</Label>
                    <Select value={provider} onValueChange={setProvider}>
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        {PROVIDERS.map((p) => (
                          <SelectItem key={p} value={p}>{p}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <Label className="text-xs font-medium">Kline Interval</Label>
                    <Select value={klineInterval} onValueChange={(v) => setKlineInterval(v as CryptoInterval)}>
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        {CRYPTO_INTERVALS.map((i) => (
                          <SelectItem key={i.value} value={i.value}>{i.label}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <Label className="text-xs font-medium">Output Language</Label>
                    <Select value={outputLanguage} onValueChange={setOutputLanguage}>
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        {LANGUAGES.map((l) => (
                          <SelectItem key={l} value={l}>{l}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                </div>

                {/* Workflow Mode */}
                <div className="flex flex-col gap-1.5">
                  <Label className="text-xs font-medium">Workflow Mode</Label>
                  <div className="flex rounded-lg border overflow-hidden">
                    {([
                      { value: "quick_trade" as const, label: "Quick Trade" },
                      { value: "deep_analysis" as const, label: "Deep Analysis" },
                    ]).map((opt) => (
                      <button
                        key={opt.value}
                        type="button"
                        className={`flex-1 px-3 py-1.5 text-xs font-medium transition-colors ${
                          workflowMode === opt.value
                            ? "bg-primary text-primary-foreground"
                            : "bg-muted/50 hover:bg-muted"
                        }`}
                        onClick={() => setWorkflowMode(opt.value)}
                      >
                        {opt.label}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Smart Pre-Screen */}
                <div className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    id="sched_ta_prefilter"
                    checked={taPrefilterEnabled}
                    onChange={(e) => setTaPrefilterEnabled(e.target.checked)}
                    className="h-4 w-4 rounded border-input"
                  />
                  <Label htmlFor="sched_ta_prefilter" className="text-xs font-medium cursor-pointer">Smart Pre-Screen</Label>
                  {taPrefilterEnabled && (
                    <Input
                      type="number"
                      min={0}
                      max={100}
                      value={taPrefilterThreshold}
                      onChange={(e) => setTaPrefilterThreshold(Number(e.target.value))}
                      className="w-16 h-7 text-xs ml-2"
                    />
                  )}
                </div>

                {/* Analyst Team */}
                <div className="flex flex-col gap-1.5">
                  <Label className="text-xs font-medium">Analyst Team</Label>
                  <div className="flex flex-wrap gap-1.5">
                    {CRYPTO_ANALYSTS.map((a) => {
                      const active = analysts.includes(a);
                      return (
                        <button
                          key={a}
                          type="button"
                          onClick={() => setAnalysts((prev) => active ? prev.filter((x) => x !== a) : [...prev, a])}
                          className={`px-2.5 py-1 text-xs rounded border transition-colors ${
                            active
                              ? "bg-primary text-primary-foreground border-primary"
                              : "bg-muted/50 text-muted-foreground border-border hover:bg-muted"
                          }`}
                        >
                          {a.replace("crypto_", "")}
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* Backend URL + API Key */}
                <div className="flex flex-col gap-1.5">
                  <Label className="text-xs font-medium">Backend URL</Label>
                  <Input
                    value={backendUrl}
                    onChange={(e) => setBackendUrl(e.target.value)}
                    placeholder="http://localhost:4141"
                    className="text-xs"
                  />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label className="text-xs font-medium">API Key</Label>
                  <Input
                    type="password"
                    value={llmApiKey}
                    onChange={(e) => setLlmApiKey(e.target.value)}
                    placeholder="Provider API key (optional)"
                    className="text-xs"
                  />
                </div>

                {/* Model selectors */}
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div className="flex flex-col gap-1.5">
                    <Label className="text-xs font-medium">Deep Think Model</Label>
                    <ModelSelect
                      options={deepOptions}
                      value={deepModel}
                      onChange={(v) => setDeepModel(v ?? "")}
                      placeholder="Select model..."
                    />
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <Label className="text-xs font-medium">Quick Think Model</Label>
                    <ModelSelect
                      options={quickOptions}
                      value={quickModel}
                      onChange={(v) => setQuickModel(v ?? "")}
                      placeholder="Select model..."
                    />
                  </div>
                </div>

                {/* Workflow parameters */}
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                  <div className="flex flex-col gap-1">
                    <Label className="text-xs font-medium">Research Depth</Label>
                    <Input type="number" min={1} max={5} value={researchDepth} onChange={(e) => setResearchDepth(Number(e.target.value))} className="text-xs" />
                  </div>
                  <div className="flex flex-col gap-1">
                    <Label className="text-xs font-medium">Debate Rounds</Label>
                    <Input type="number" min={1} max={10} value={maxDebateRounds} onChange={(e) => setMaxDebateRounds(Number(e.target.value))} className="text-xs" />
                  </div>
                  {workflowMode !== "quick_trade" && (
                    <div className="flex flex-col gap-1">
                      <Label className="text-xs font-medium">Risk Rounds</Label>
                      <Input type="number" min={1} max={10} value={maxRiskRounds} onChange={(e) => setMaxRiskRounds(Number(e.target.value))} className="text-xs" />
                    </div>
                  )}
                  <div className="flex flex-col gap-1">
                    <Label className="text-xs font-medium">Parallel</Label>
                    <Input type="number" min={1} max={25} value={maxParallel} onChange={(e) => setMaxParallel(Math.min(25, Math.max(1, Number(e.target.value))))} className="text-xs" />
                  </div>
                </div>
                <div className="flex flex-col gap-1">
                  <Label className="text-xs font-medium">Max Recursion Limit</Label>
                  <Input type="number" min={1} max={500} value={maxRecurLimit} onChange={(e) => setMaxRecurLimit(Number(e.target.value))} className="w-32 text-xs" />
                </div>
              </div>
            )}
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => handleOpenChange(false)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={submitting || (!!editingId && editLoading)}>
              {submitting
                ? "Saving..."
                : editingId
                  ? "Update"
                  : "Create"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
