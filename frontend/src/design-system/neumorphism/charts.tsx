import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { NeuCard } from "./display";
import { NeuToggleGroup } from "./inputs";

export function NeuLegendChip({
  label,
  color,
  active = true,
  onToggle,
}: {
  label: ReactNode;
  color: string;
  active?: boolean;
  onToggle?: () => void;
}) {
  const body = (
    <span
      className={cn(
        "neu-surface-base inline-flex min-h-9 items-center gap-2 rounded-[var(--neu-radius-pill)] px-3 py-1.5 text-xs font-semibold uppercase tracking-[0.16em]",
        active ? "neu-surface-raised neu-pill-soft" : "neu-surface-inset neu-pill-outline opacity-70",
      )}
    >
      <span className="inline-flex size-2.5 rounded-full" style={{ background: color }} />
      {label}
    </span>
  );

  if (!onToggle) return body;

  return (
    <button type="button" onClick={onToggle}>
      {body}
    </button>
  );
}

export function NeuChartToolbar({
  period,
  scope,
  actions,
  onPeriodChange,
  onScopeChange,
  inline = true,
}: {
  period: string;
  scope: string;
  actions?: ReactNode;
  onPeriodChange: (period: string) => void;
  onScopeChange: (scope: string) => void;
  inline?: boolean;
}) {
  return (
    <div className={cn("flex gap-3", inline ? "flex-wrap items-center justify-between" : "flex-col")}>
      <div className="flex flex-wrap gap-3">
        <NeuToggleGroup
          label="Period"
          size="sm"
          value={period}
          onChange={(next) => onPeriodChange(next as string)}
          options={[
            { value: "1D", label: "1D" },
            { value: "1W", label: "1W" },
            { value: "1M", label: "1M" },
            { value: "1Y", label: "1Y" },
          ]}
        />
        <NeuToggleGroup
          label="Scope"
          size="sm"
          value={scope}
          onChange={(next) => onScopeChange(next as string)}
          options={[
            { value: "all", label: "All" },
            { value: "live", label: "Live" },
            { value: "demo", label: "Demo" },
          ]}
        />
      </div>
      {actions ? <div className="flex flex-wrap gap-2">{actions}</div> : null}
    </div>
  );
}

export function NeuChartCard({
  title,
  description,
  toolbar,
  legend,
  footer,
  loading = false,
  emptyState,
  variant = "line",
  children,
}: {
  title: ReactNode;
  description?: ReactNode;
  toolbar?: ReactNode;
  legend?: ReactNode;
  footer?: ReactNode;
  loading?: boolean;
  emptyState?: ReactNode;
  variant?: "line" | "area" | "bar" | "mixed";
  children?: ReactNode;
}) {
  return (
    <NeuCard
      title={title}
      description={description}
      actions={toolbar}
      footer={footer}
      className="space-y-4"
    >
      {legend ? <div className="flex flex-wrap gap-2">{legend}</div> : null}
      <div className="neu-chart-well neu-grid-highlight min-h-[16rem] rounded-[var(--neu-radius-lg)] p-4">
        {loading ? (
          <div className="flex h-full items-center justify-center text-sm font-semibold" style={{ color: "var(--neu-text-muted)" }}>
            Loading {variant} chart
          </div>
        ) : children ? (
          children
        ) : (
          emptyState ?? (
            <div className="flex h-full items-center justify-center text-sm font-semibold" style={{ color: "var(--neu-text-muted)" }}>
              No chart data
            </div>
          )
        )}
      </div>
    </NeuCard>
  );
}
