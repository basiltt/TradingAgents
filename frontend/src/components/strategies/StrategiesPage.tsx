import { useEffect, useCallback, useState, useRef, useMemo } from "react";
import { apiClient } from "@/api/client";
import type { Strategy, StrategyCategory } from "@/api/client";
import { useAppDispatch, useAppSelector } from "@/store";
import {
  setLoading,
  setStrategies,
  setError,
  setFilterStatus,
  setFilterCategory,
  setSearchQuery,
  removeStrategy,
} from "@/store/strategies-slice";
import { StrategyFormDialog } from "./StrategyFormDialog";
import { CATEGORIES, STATUSES, STATUS_COLORS, CATEGORY_COLORS } from "./constants";
import { toast } from "sonner";

export function StrategiesPage() {
  const dispatch = useAppDispatch();
  const { strategies, status, error, filterStatus, filterCategory, searchQuery } =
    useAppSelector((s) => s.strategies);
  const [formOpen, setFormOpen] = useState(false);
  const [editingStrategy, setEditingStrategy] = useState<Strategy | null>(null);
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [duplicating, setDuplicating] = useState<string | null>(null);
  const importRef = useRef<HTMLInputElement>(null);

  const fetchStrategies = useCallback(async () => {
    dispatch(setLoading());
    try {
      const items = await apiClient.listStrategies();
      dispatch(setStrategies(items));
    } catch (e) {
      dispatch(setError(e instanceof Error ? e.message : "Failed to load strategies"));
    }
  }, [dispatch]);

  useEffect(() => {
    fetchStrategies();
  }, [fetchStrategies]);

  const handleDelete = async (id: string) => {
    setDeleting(true);
    try {
      await apiClient.deleteStrategy(id);
      dispatch(removeStrategy(id));
      toast.success("Strategy deleted");
    } catch {
      toast.error("Failed to delete strategy");
      fetchStrategies();
    }
    setDeleting(false);
    setDeleteConfirm(null);
  };

  const handleExport = async () => {
    try {
      const data = await apiClient.exportStrategies();
      const blob = new Blob([JSON.stringify(data.strategies, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `strategies-export-${new Date().toISOString().split("T")[0]}.json`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      toast.success(`Exported ${data.strategies.length} strategies`);
    } catch {
      toast.error("Failed to export strategies");
    }
  };

  const handleImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (file.size > 1024 * 1024) {
      toast.error("File too large (max 1MB)");
      if (importRef.current) importRef.current.value = "";
      return;
    }
    try {
      const text = await file.text();
      const parsed = JSON.parse(text);
      const items = Array.isArray(parsed) ? parsed : parsed.strategies ?? [];
      if (!items.length) {
        toast.error("No strategies found in file");
        if (importRef.current) importRef.current.value = "";
        return;
      }
      const invalid = items.filter((item: unknown) => typeof item !== "object" || item === null || !("name" in item) || !(item as Record<string, unknown>).name);
      if (invalid.length) {
        toast.error(`${invalid.length} item(s) missing a valid name`);
        if (importRef.current) importRef.current.value = "";
        return;
      }
      const result = await apiClient.importStrategies(items);
      toast.success(`Imported ${result.imported} strategies`);
      fetchStrategies();
    } catch {
      toast.error("Failed to import — check file format");
    }
    if (importRef.current) importRef.current.value = "";
  };

  const filtered = useMemo(() => strategies.filter((s) => {
    if (filterStatus !== "all" && s.status !== filterStatus) return false;
    if (filterCategory !== "all" && s.category !== filterCategory) return false;
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      if (!s.name.toLowerCase().includes(q) && !(s.description ?? "").toLowerCase().includes(q)) return false;
    }
    return true;
  }), [strategies, filterStatus, filterCategory, searchQuery]);

  const counts = useMemo(() => ({
    all: strategies.length,
    active: strategies.filter((s) => s.status === "active").length,
    draft: strategies.filter((s) => s.status === "draft").length,
  }), [strategies]);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Trading Strategies</h1>
          <p className="text-muted-foreground text-sm mt-1">
            Define and manage your trading strategy configurations
          </p>
        </div>
        <div className="flex items-center gap-2">
          <input
            ref={importRef}
            type="file"
            accept=".json"
            className="hidden"
            onChange={handleImport}
          />
          <button
            onClick={() => importRef.current?.click()}
            className="px-3 py-2 rounded-lg border border-border text-sm font-medium hover:bg-accent transition-colors"
          >
            <span className="flex items-center gap-2">
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
              </svg>
              Import
            </span>
          </button>
          <button
            onClick={handleExport}
            className="px-3 py-2 rounded-lg border border-border text-sm font-medium hover:bg-accent transition-colors"
          >
            <span className="flex items-center gap-2">
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
              </svg>
              Export
            </span>
          </button>
          <button
            onClick={() => { setEditingStrategy(null); setFormOpen(true); }}
            className="px-4 py-2 rounded-lg text-sm font-medium text-white transition-colors"
            style={{ backgroundColor: "var(--primary)" }}
          >
            <span className="flex items-center gap-2">
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
              </svg>
              New Strategy
            </span>
          </button>
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
        <StatCard label="TOTAL" value={counts.all} />
        <StatCard label="ACTIVE" value={counts.active} color="text-green-400" />
        <StatCard label="DRAFT" value={counts.draft} color="text-blue-400" />
        <StatCard label="CATEGORIES" value={new Set(strategies.map(s => s.category)).size} color="text-purple-400" />
        <StatCard label="PAUSED" value={strategies.filter(s => s.status === "paused").length} color="text-yellow-400" />
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3">
        <input
          type="text"
          placeholder="Search strategies..."
          value={searchQuery}
          onChange={(e) => dispatch(setSearchQuery(e.target.value))}
          className="px-3 py-2 rounded-lg border border-border bg-card text-sm w-64 placeholder:text-muted-foreground"
        />
        <div className="flex items-center gap-1 rounded-lg border border-border p-0.5">
          {(["all", ...STATUSES] as const).map((s) => (
            <button
              key={s}
              onClick={() => dispatch(setFilterStatus(s))}
              className={`px-3 py-1.5 rounded-md text-xs font-medium capitalize transition-colors ${
                filterStatus === s
                  ? "bg-primary text-white"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {s}
            </button>
          ))}
        </div>
        <select
          value={filterCategory}
          onChange={(e) => dispatch(setFilterCategory(e.target.value as StrategyCategory | "all"))}
          className="px-3 py-2 rounded-lg border border-border bg-card text-sm capitalize"
        >
          <option value="all">All Categories</option>
          {CATEGORIES.map((c) => (
            <option key={c} value={c} className="capitalize">{c}</option>
          ))}
        </select>
      </div>

      {/* Content */}
      {status === "loading" && !strategies.length ? (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="rounded-xl border border-border bg-card p-5 animate-pulse">
              <div className="h-5 w-40 bg-muted rounded mb-3" />
              <div className="h-3 w-60 bg-muted rounded mb-4" />
              <div className="h-3 w-32 bg-muted rounded" />
            </div>
          ))}
        </div>
      ) : error ? (
        <div className="rounded-xl border border-destructive/30 bg-destructive/10 p-6 text-center">
          <p className="text-destructive font-medium">{error}</p>
          <button onClick={fetchStrategies} className="mt-2 text-sm underline text-muted-foreground">
            Retry
          </button>
        </div>
      ) : !filtered.length ? (
        <div className="rounded-xl border border-border bg-card p-12 text-center">
          <div className="w-14 h-14 mx-auto rounded-2xl bg-muted flex items-center justify-center mb-4">
            <svg className="w-7 h-7 text-muted-foreground" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
            </svg>
          </div>
          <h3 className="text-lg font-semibold mb-1">No strategies found</h3>
          <p className="text-muted-foreground text-sm mb-4">
            {strategies.length ? "Try adjusting your filters" : "Create your first trading strategy"}
          </p>
          {!strategies.length && (
            <button
              onClick={() => { setEditingStrategy(null); setFormOpen(true); }}
              className="px-4 py-2 rounded-lg text-sm font-medium text-white"
              style={{ backgroundColor: "var(--primary)" }}
            >
              Create Strategy
            </button>
          )}
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {filtered.map((s) => (
            <StrategyCard
              key={s.id}
              strategy={s}
              onEdit={() => { setEditingStrategy(s); setFormOpen(true); }}
              onDelete={() => setDeleteConfirm(s.id)}
              onDuplicate={async () => {
                if (duplicating) return;
                setDuplicating(s.id);
                try {
                  await apiClient.createStrategy({
                    name: `${s.name} (Copy)`,
                    description: s.description,
                    category: s.category,
                    status: "draft",
                    config: s.config,
                  });
                  toast.success("Strategy duplicated");
                  fetchStrategies();
                } catch {
                  toast.error("Failed to duplicate");
                }
                setDuplicating(null);
              }}
            />
          ))}
        </div>
      )}

      {/* Delete confirmation */}
      {deleteConfirm && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
          onClick={() => !deleting && setDeleteConfirm(null)}
          onKeyDown={(e) => e.key === "Escape" && !deleting && setDeleteConfirm(null)}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="delete-dialog-title"
            className="bg-card border border-border rounded-xl p-6 max-w-sm w-full mx-4 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 id="delete-dialog-title" className="text-lg font-semibold mb-2">Delete Strategy</h3>
            <p className="text-muted-foreground text-sm mb-4">
              This action cannot be undone. Are you sure?
            </p>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setDeleteConfirm(null)}
                className="px-4 py-2 rounded-lg border border-border text-sm font-medium hover:bg-accent"
                disabled={deleting}
              >
                Cancel
              </button>
              <button
                onClick={() => handleDelete(deleteConfirm)}
                className="px-4 py-2 rounded-lg bg-destructive text-white text-sm font-medium hover:opacity-90 disabled:opacity-50"
                disabled={deleting}
              >
                {deleting ? "Deleting..." : "Delete"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Form dialog */}
      <StrategyFormDialog
        open={formOpen}
        strategy={editingStrategy}
        onClose={() => { setFormOpen(false); setEditingStrategy(null); }}
        onSaved={fetchStrategies}
      />
    </div>
  );
}

function StatCard({ label, value, color }: { label: string; value: number; color?: string }) {
  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <p className={`text-2xl font-bold ${color ?? "text-foreground"}`}>{value}</p>
      <p className="text-[11px] text-muted-foreground font-medium tracking-wider mt-1">{label}</p>
    </div>
  );
}

function StrategyCard({
  strategy,
  onEdit,
  onDelete,
  onDuplicate,
}: {
  strategy: Strategy;
  onEdit: () => void;
  onDelete: () => void;
  onDuplicate: () => void;
}) {
  const s = strategy;
  const cfg = s.config;
  const updatedAt = new Date(s.updated_at).toLocaleDateString("en-US", {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });

  return (
    <div className="rounded-xl border border-border bg-card p-5 hover:border-primary/30 transition-colors group">
      <div className="flex items-start justify-between mb-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <h3 className="text-base font-semibold truncate">{s.name}</h3>
            <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase ${STATUS_COLORS[s.status]}`}>
              {s.status}
            </span>
          </div>
          <p className="text-sm text-muted-foreground line-clamp-1">{s.description || "No description"}</p>
        </div>
        <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity ml-2">
          <button onClick={onEdit} className="p-1.5 rounded-md hover:bg-accent" title="Edit">
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
            </svg>
          </button>
          <button onClick={onDuplicate} className="p-1.5 rounded-md hover:bg-accent" title="Duplicate">
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
            </svg>
          </button>
          <button onClick={onDelete} className="p-1.5 rounded-md hover:bg-destructive/20 text-destructive" title="Delete">
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
            </svg>
          </button>
        </div>
      </div>

      {/* Tags row */}
      <div className="flex items-center gap-2 mb-3">
        <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase ${CATEGORY_COLORS[s.category]}`}>
          {s.category}
        </span>
        {cfg.trading_mode && (
          <span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-muted text-muted-foreground">
            {cfg.trading_mode}
          </span>
        )}
        {cfg.order_type && (
          <span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-muted text-muted-foreground">
            {cfg.order_type}
          </span>
        )}
      </div>

      {/* Key metrics */}
      <div className="flex flex-wrap gap-3 pt-3 border-t border-border">
        <Metric label="RISK" value={cfg.risk_per_trade_pct != null ? `${cfg.risk_per_trade_pct}%` : "—"} />
        <Metric label="LEVERAGE" value={cfg.leverage_multiplier != null ? `${cfg.leverage_multiplier}x` : "—"} />
        <Metric label="SL" value={cfg.sl_value != null ? `${cfg.sl_value}%` : "—"} color="text-red-400" />
        <Metric label="TP" value={cfg.tp_value != null ? `${cfg.tp_value}%` : "—"} color="text-green-400" />
        {cfg.cycle_enabled && <Metric label="CYC TGT" value={cfg.cycle_target_pnl_pct != null ? `${cfg.cycle_target_pnl_pct}%` : "—"} color="text-cyan-400" />}
      </div>

      <p className="text-[11px] text-muted-foreground mt-3">Updated {updatedAt}</p>
    </div>
  );
}

function Metric({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div>
      <p className={`text-sm font-semibold ${color ?? "text-foreground"}`}>{value}</p>
      <p className="text-[10px] text-muted-foreground font-medium">{label}</p>
    </div>
  );
}
