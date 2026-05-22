import { useEffect, useCallback, useState, useRef, useMemo } from "react";
import { CopyPlus, Download, PencilLine, Plus, Search, Trash2, Upload, Waypoints } from "lucide-react";
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
import { CATEGORIES, STATUSES, CATEGORY_COLORS } from "./constants";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { PageHeader } from "@/components/layout/PageHeader";

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
      const blob = new Blob([JSON.stringify(data.strategies, null, 2)], {
        type: "application/json",
      });
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
      const invalid = items.filter(
        (item: unknown) =>
          typeof item !== "object" ||
          item === null ||
          !("name" in item) ||
          !(item as Record<string, unknown>).name,
      );
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

  const filtered = useMemo(
    () =>
      strategies.filter((strategy) => {
        if (filterStatus !== "all" && strategy.status !== filterStatus) return false;
        if (filterCategory !== "all" && strategy.category !== filterCategory) return false;
        if (searchQuery) {
          const query = searchQuery.toLowerCase();
          if (
            !strategy.name.toLowerCase().includes(query) &&
            !(strategy.description ?? "").toLowerCase().includes(query)
          ) {
            return false;
          }
        }
        return true;
      }),
    [strategies, filterStatus, filterCategory, searchQuery],
  );

  const counts = useMemo(
    () => ({
      all: strategies.length,
      active: strategies.filter((strategy) => strategy.status === "active").length,
      draft: strategies.filter((strategy) => strategy.status === "draft").length,
      paused: strategies.filter((strategy) => strategy.status === "paused").length,
      categories: new Set(strategies.map((strategy) => strategy.category)).size,
    }),
    [strategies],
  );

  return (
    <div className="space-y-5 pb-7">
      <PageHeader
        eyebrow="Strategies"
        title="Strategies"
        description=""
        actions={
          <div className="flex flex-wrap gap-2">
            <input
              ref={importRef}
              type="file"
              accept=".json"
              className="hidden"
              onChange={handleImport}
            />
            <Button variant="outline" onClick={() => importRef.current?.click()}>
              <Upload className="size-4" />
              Import
            </Button>
            <Button variant="outline" onClick={handleExport}>
              <Download className="size-4" />
              Export
            </Button>
            <Button onClick={() => { setEditingStrategy(null); setFormOpen(true); }}>
              <Plus className="size-4" />
              New Strategy
            </Button>
          </div>
        }
        stats={[
          { label: "Strategies", value: String(counts.all), tone: "accent" },
          { label: "Active", value: String(counts.active), tone: counts.active ? "success" : "neutral" },
          { label: "Draft", value: String(counts.draft), tone: "neutral" },
          { label: "Paused", value: String(counts.paused), tone: counts.paused ? "warning" : "neutral" },
        ]}
      >
        <div className="flex flex-wrap gap-2">
          <Badge variant="outline">{counts.categories} category groups</Badge>
        </div>
      </PageHeader>

      <Card>
        <CardContent className="grid gap-4 p-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] lg:items-end">
          <div className="space-y-1.5">
            <p className="section-eyebrow">Search</p>
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                type="text"
                placeholder="Search strategies..."
                value={searchQuery}
                onChange={(e) => dispatch(setSearchQuery(e.target.value))}
                className="pl-10"
              />
            </div>
          </div>

          <div className="space-y-1.5">
            <p className="section-eyebrow">Status</p>
            <div className="flex flex-wrap gap-2">
              {(["all", ...STATUSES] as const).map((statusKey) => (
                <Button
                  key={statusKey}
                  variant={filterStatus === statusKey ? "default" : "outline"}
                  size="sm"
                  onClick={() => dispatch(setFilterStatus(statusKey))}
                >
                  {statusKey}
                </Button>
              ))}
            </div>
          </div>

          <div className="space-y-1.5">
            <p className="section-eyebrow">Category</p>
            <select
              value={filterCategory}
              onChange={(e) =>
                dispatch(setFilterCategory(e.target.value as StrategyCategory | "all"))
              }
              className="h-10 min-w-[14rem] rounded-[calc(var(--radius)*1.2)] border border-border/70 bg-card/72 px-3.5 text-sm text-foreground shadow-[var(--shadow-soft)] outline-none focus:border-ring focus:ring-4 focus:ring-ring/20"
            >
              <option value="all">All Categories</option>
              {CATEGORIES.map((category) => (
                <option key={category} value={category} className="capitalize">
                  {category}
                </option>
              ))}
            </select>
          </div>
        </CardContent>
      </Card>

      {status === "loading" && !strategies.length ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 6 }).map((_, index) => (
            <Skeleton key={index} className="h-72 rounded-[calc(var(--radius)*1.7)]" />
          ))}
        </div>
      ) : error ? (
        <Card className="border-destructive/25">
          <CardContent className="flex flex-col items-center gap-4 p-6 text-center">
            <p className="section-eyebrow">Strategy library</p>
            <h2 className="text-xl font-semibold tracking-tight">Failed to load strategies</h2>
            <p className="max-w-xl text-sm text-muted-foreground">{error}</p>
            <Button variant="outline" onClick={fetchStrategies}>
              Retry
            </Button>
          </CardContent>
        </Card>
      ) : !filtered.length ? (
        <Card className="border-dashed">
          <CardContent className="flex flex-col items-center justify-center gap-4 p-6 text-center sm:p-8">
            <div className="gradient-primary flex size-12 items-center justify-center rounded-[calc(var(--radius)*1.45)] text-primary-foreground shadow-[var(--shadow-accent)]">
              <Waypoints className="size-5.5" />
            </div>
            <div className="space-y-2">
              <p className="section-eyebrow">Ready state</p>
              <h2 className="text-xl font-semibold tracking-tight">No strategies found</h2>
              <p className="max-w-xl text-sm text-muted-foreground">
                {strategies.length
                  ? "Adjust the current filters to reveal matching strategy templates."
                  : "Create your first reusable trading strategy to seed the library."}
              </p>
            </div>
            {!strategies.length ? (
              <Button onClick={() => { setEditingStrategy(null); setFormOpen(true); }}>
                <Plus className="size-4" />
                Create strategy
              </Button>
            ) : null}
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-3">
          {filtered.map((strategy) => (
            <StrategyCard
              key={strategy.id}
              strategy={strategy}
              duplicating={duplicating === strategy.id}
              onEdit={() => { setEditingStrategy(strategy); setFormOpen(true); }}
              onDelete={() => setDeleteConfirm(strategy.id)}
              onDuplicate={async () => {
                if (duplicating) return;
                setDuplicating(strategy.id);
                try {
                  await apiClient.createStrategy({
                    name: `${strategy.name} (Copy)`,
                    description: strategy.description,
                    category: strategy.category,
                    status: "draft",
                    config: strategy.config,
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

      <Dialog open={!!deleteConfirm} onOpenChange={() => setDeleteConfirm(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete Strategy</DialogTitle>
            <DialogDescription>
              This permanently removes{" "}
              <span className="font-medium text-foreground">
                {strategies.find((strategy) => strategy.id === deleteConfirm)?.name ?? "this strategy"}
              </span>
              . This action cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteConfirm(null)} disabled={deleting}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={() => deleteConfirm && handleDelete(deleteConfirm)}
              disabled={deleting}
            >
              {deleting ? "Deleting..." : "Delete"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <StrategyFormDialog
        open={formOpen}
        strategy={editingStrategy}
        onClose={() => { setFormOpen(false); setEditingStrategy(null); }}
        onSaved={fetchStrategies}
      />
    </div>
  );
}

function StrategyCard({
  strategy,
  duplicating,
  onEdit,
  onDelete,
  onDuplicate,
}: {
  strategy: Strategy;
  duplicating: boolean;
  onEdit: () => void;
  onDelete: () => void;
  onDuplicate: () => void;
}) {
  const config = strategy.config;
  const updatedAt = new Date(strategy.updated_at).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });

  const statusVariant: "default" | "secondary" | "outline" =
    strategy.status === "active"
      ? "default"
      : strategy.status === "paused"
        ? "secondary"
        : strategy.status === "archived"
          ? "outline"
          : "secondary";

  return (
    <Card className="h-full">
      <CardHeader className="gap-4">
        <div className="flex items-start gap-4">
          <div className="gradient-primary flex size-10 shrink-0 items-center justify-center rounded-[calc(var(--radius)*1.25)] text-primary-foreground shadow-[var(--shadow-accent)]">
            <Waypoints className="size-4.5" />
          </div>

          <div className="min-w-0 flex-1 space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <CardTitle className="text-base">{strategy.name}</CardTitle>
              <Badge variant={statusVariant}>{strategy.status}</Badge>
              <span
                className={`rounded-full px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.16em] ${CATEGORY_COLORS[strategy.category]}`}
              >
                {strategy.category}
              </span>
            </div>
            <CardDescription className="line-clamp-2">
              {strategy.description || "No description"}
            </CardDescription>
          </div>
        </div>

        <div className="flex flex-wrap gap-2">
          {config.trading_mode ? <Badge variant="outline">{config.trading_mode}</Badge> : null}
          {config.order_type ? <Badge variant="outline">{config.order_type}</Badge> : null}
          {config.cycle_enabled ? <Badge variant="outline">Cycle ready</Badge> : null}
        </div>
      </CardHeader>

      <CardContent className="grid gap-3 sm:grid-cols-2">
        <Metric label="Risk" value={config.risk_per_trade_pct != null ? `${config.risk_per_trade_pct}%` : "—"} />
        <Metric label="Leverage" value={config.leverage_multiplier != null ? `${config.leverage_multiplier}x` : "—"} />
        <Metric label="Stop Loss" value={config.sl_value != null ? `${config.sl_value}%` : "—"} tone="danger" />
        <Metric label="Take Profit" value={config.tp_value != null ? `${config.tp_value}%` : "—"} tone="success" />
        {config.cycle_enabled ? (
          <Metric
            label="Cycle Target"
            value={
              config.cycle_target_pnl_pct != null ? `${config.cycle_target_pnl_pct}%` : "—"
            }
            tone="accent"
          />
        ) : null}
      </CardContent>

      <CardFooter className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <span className="text-xs text-muted-foreground">Updated {updatedAt}</span>
        <div className="flex w-full flex-wrap gap-2 sm:w-auto sm:justify-end">
          <Button variant="ghost" size="sm" onClick={onEdit}>
            <PencilLine className="size-3.5" />
            Edit
          </Button>
          <Button variant="ghost" size="sm" onClick={onDuplicate} disabled={duplicating}>
            <CopyPlus className="size-3.5" />
            {duplicating ? "Copying..." : "Duplicate"}
          </Button>
          <Button variant="ghost" size="sm" onClick={onDelete} className="text-destructive hover:text-destructive">
            <Trash2 className="size-3.5" />
            Delete
          </Button>
        </div>
      </CardFooter>
    </Card>
  );
}

function Metric({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: string;
  tone?: "neutral" | "success" | "danger" | "accent";
}) {
  const colorMap = {
    neutral: "text-foreground",
    success: "text-emerald-500",
    danger: "text-destructive",
    accent: "text-primary",
  } as const;

  return (
    <div className="rounded-[calc(var(--radius)*1.15)] border border-border/60 bg-muted/16 p-2.5">
      <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
        {label}
      </p>
      <p className={`mt-1.5 text-base font-semibold tracking-tight ${colorMap[tone]}`}>
        {value}
      </p>
    </div>
  );
}
