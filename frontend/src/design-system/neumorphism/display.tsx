import type { ReactNode } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { NeuDivider, NeuSurface } from "./foundation";
import { NeuButton } from "./inputs";
import { NeuStatusPill } from "./headers";
import type {
  NeuFilterChip,
  NeuMetric,
  NeuPaginationState,
  NeuTableColumn,
  NeuTone,
} from "./types";

function toneColor(tone: NeuTone) {
  if (tone === "accent") return "var(--neu-accent)";
  if (tone === "success") return "var(--neu-success)";
  if (tone === "warning") return "var(--neu-warning)";
  if (tone === "danger") return "var(--neu-danger)";
  return "var(--neu-text-strong)";
}

export function NeuCard({
  title,
  description,
  actions,
  footer,
  size = "default",
  interactive = false,
  className,
  children,
}: {
  title?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  footer?: ReactNode;
  size?: "default" | "compact" | "clickable";
  interactive?: boolean;
  className?: string;
  children?: ReactNode;
}) {
  const isInteractive = interactive || size === "clickable";

  return (
    <NeuSurface
      depth="raised"
      radius="lg"
      padding={size === "compact" ? "sm" : "md"}
      interactive={isInteractive}
      className={cn("flex h-full flex-col gap-4", className)}
    >
      {(title || description || actions) && (
        <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
          <div className="space-y-1">
            {title ? <h3 className="text-base font-semibold tracking-[-0.02em]">{title}</h3> : null}
            {description ? (
              <p className="text-sm leading-6" style={{ color: "var(--neu-text-muted)" }}>
                {description}
              </p>
            ) : null}
          </div>
          {actions ? <div className="flex flex-wrap gap-2">{actions}</div> : null}
        </div>
      )}
      <div className="min-h-0 flex-1">{children}</div>
      {footer ? (
        <>
          <NeuDivider />
          <div className="flex flex-wrap items-center justify-between gap-3">{footer}</div>
        </>
      ) : null}
    </NeuSurface>
  );
}

export function NeuBadge({
  variant = "soft",
  tone = "neutral",
  size = "sm",
  icon,
  dot = false,
  pulse = false,
  count,
  className,
  children,
}: {
  variant?: "solid" | "soft" | "outline" | "ghost";
  tone?: NeuTone;
  size?: "sm" | "md";
  icon?: ReactNode;
  dot?: boolean;
  pulse?: boolean;
  count?: ReactNode;
  className?: string;
  children: ReactNode;
}) {
  const color = toneColor(tone);
  const depthClass =
    variant === "solid"
      ? "neu-surface-accent neu-pill-solid"
      : variant === "soft"
        ? "neu-surface-raised neu-pill-soft"
        : variant === "ghost"
          ? "neu-surface-inset neu-pill-outline"
          : "neu-surface-flat neu-pill-outline";
  const background =
    variant === "solid"
      ? `linear-gradient(145deg, color-mix(in oklch, ${color} 10%, var(--neu-highlight)), color-mix(in oklch, ${color} 14%, var(--neu-surface-raised)) 56%, color-mix(in oklch, ${color} 18%, var(--neu-surface-muted)))`
      : variant === "soft"
        ? `color-mix(in oklch, ${color} 14%, var(--neu-surface-raised))`
        : variant === "ghost"
          ? `color-mix(in oklch, ${color} 8%, var(--neu-surface-muted))`
          : "color-mix(in oklch, var(--neu-surface-raised) 88%, transparent)";

  return (
    <span
      className={cn(
        "neu-surface-base inline-flex items-center rounded-[var(--neu-radius-pill)] font-semibold uppercase tracking-[0.18em]",
        depthClass,
        size === "sm"
          ? "min-h-8 gap-1.5 px-3 py-1 text-[11px]"
          : "min-h-9 gap-2 px-3.5 py-1.5 text-xs",
        className,
      )}
      style={{
        color: variant === "solid" ? "var(--neu-text-strong)" : color,
        background,
        borderColor: `color-mix(in oklch, ${color} 18%, var(--neu-stroke-soft))`,
      }}
    >
      {dot ? (
        <span
          className={cn("inline-flex rounded-full", pulse && "animate-pulse")}
          style={{
            width: size === "sm" ? 6 : 8,
            height: size === "sm" ? 6 : 8,
            background: color,
          }}
        />
      ) : null}
      {icon}
      {children}
      {count != null ? (
        <span
          className="inline-flex min-w-[1.35rem] items-center justify-center rounded-full px-1.5 py-0.5 text-[10px]"
          style={{
            background: "color-mix(in oklch, var(--neu-highlight) 36%, transparent)",
            color: variant === "solid" ? "var(--neu-text-strong)" : color,
          }}
        >
          {count}
        </span>
      ) : null}
    </span>
  );
}

export function NeuTable<Row extends Record<string, unknown>>({
  columns,
  rows,
  rowKey,
  toolbar,
  loading = false,
  emptyState,
  rowActions,
  stickyHeader = false,
}: {
  columns: Array<NeuTableColumn<Row>>;
  rows: Row[];
  rowKey: (row: Row) => string;
  toolbar?: ReactNode;
  loading?: boolean;
  emptyState?: ReactNode;
  rowActions?: (row: Row, index: number) => ReactNode;
  stickyHeader?: boolean;
}) {
  if (!rows.length && emptyState) {
    return <>{emptyState}</>;
  }

  return (
    <NeuCard
      title={toolbar ? "Table view" : undefined}
      actions={toolbar}
      description={loading ? "Loading data surface" : undefined}
      className="overflow-hidden"
    >
      <div className="neu-table-wrap hidden overflow-x-auto rounded-[var(--neu-radius-lg)] p-2 md:block">
        <table className="min-w-full text-sm">
          <thead className={cn(stickyHeader && "sticky top-0 z-10")}>
            <tr
              className="text-left text-[11px] font-semibold uppercase tracking-[0.18em]"
              style={{
                color: "var(--neu-text-muted)",
                background: "color-mix(in oklch, var(--neu-highlight) 8%, transparent)",
              }}
            >
              {columns.map((column) => (
                <th
                  key={column.id}
                  className={cn(
                    "px-4 py-3",
                    column.align === "right" && "text-right",
                    column.align === "center" && "text-center",
                    column.className,
                  )}
                >
                  {column.header}
                </th>
              ))}
              {rowActions ? <th className="px-4 py-3 text-right">Actions</th> : null}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <tr
                key={rowKey(row)}
                className="border-t transition-colors hover:bg-[color-mix(in_oklch,var(--neu-highlight)_8%,transparent)]"
                style={{ borderColor: "var(--neu-stroke-soft)" }}
              >
                {columns.map((column) => (
                  <td
                    key={column.id}
                    className={cn(
                      "px-4 py-3 align-top",
                      column.align === "right" && "text-right",
                      column.align === "center" && "text-center",
                      column.className,
                    )}
                  >
                    {column.cell ? column.cell(row, index) : String(row[column.accessor ?? column.id] ?? "")}
                  </td>
                ))}
                {rowActions ? <td className="px-4 py-3 text-right">{rowActions(row, index)}</td> : null}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="space-y-3 md:hidden">
        {rows.map((row, index) => (
          <NeuSurface key={rowKey(row)} depth="inset" radius="md" padding="sm" className="space-y-3">
            {columns.map((column) => (
              <div key={column.id} className="space-y-1">
                <p className="text-[11px] font-semibold uppercase tracking-[0.18em]" style={{ color: "var(--neu-text-muted)" }}>
                  {column.mobileLabel ?? column.header}
                </p>
                <div className="text-sm">
                  {column.cell ? column.cell(row, index) : String(row[column.accessor ?? column.id] ?? "")}
                </div>
              </div>
            ))}
            {rowActions ? (
              <>
                <NeuDivider />
                <div className="flex flex-wrap gap-2">{rowActions(row, index)}</div>
              </>
            ) : null}
          </NeuSurface>
        ))}
      </div>
    </NeuCard>
  );
}

export function NeuFilterBar({
  filters,
  search,
  actions,
  clearAll,
  sticky = false,
  collapsible = false,
  compact = false,
}: {
  filters: NeuFilterChip[];
  search?: ReactNode;
  actions?: ReactNode;
  clearAll?: () => void;
  sticky?: boolean;
  collapsible?: boolean;
  compact?: boolean;
}) {
  return (
    <NeuSurface
      depth="raised"
      radius="lg"
      padding={compact ? "sm" : "md"}
      className={cn(sticky && "sticky top-3 z-20", "space-y-3 backdrop-blur-[2px]")}
    >
      <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
        <div className="flex flex-wrap items-center gap-2">
          {filters.map((filter) => (
            <button key={filter.id} type="button" onClick={filter.onSelect}>
              <NeuBadge
                tone={filter.tone ?? "neutral"}
                variant={filter.active ? "solid" : "soft"}
                size={compact ? "sm" : "md"}
                icon={filter.icon}
                count={filter.count}
              >
                {filter.label}
              </NeuBadge>
            </button>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {search}
          {clearAll ? (
            <NeuButton variant="ghost" size="sm" onClick={clearAll}>
              Clear
            </NeuButton>
          ) : null}
          {actions}
        </div>
      </div>
      {collapsible ? (
        <p className="text-xs" style={{ color: "var(--neu-text-muted)" }}>
          Collapsible filter mode is enabled for smaller layouts.
        </p>
      ) : null}
    </NeuSurface>
  );
}

export function NeuEmptyState({
  icon,
  title,
  description,
  primaryAction,
  secondaryAction,
  centered = true,
}: {
  icon?: ReactNode;
  title: ReactNode;
  description: ReactNode;
  primaryAction?: ReactNode;
  secondaryAction?: ReactNode;
  centered?: boolean;
}) {
  return (
    <NeuSurface depth="raised" radius="lg" padding="lg" className={cn("space-y-4", centered && "text-center")}>
      {icon ? (
        <div className="mx-auto flex size-14 items-center justify-center rounded-[var(--neu-radius-md)] neu-surface-base neu-surface-accent shadow-[var(--neu-shadow-pill)]">
          {icon}
        </div>
      ) : null}
      <div className="space-y-2">
        <h3 className="text-xl font-semibold tracking-[-0.03em]">{title}</h3>
        <p className="mx-auto max-w-2xl text-sm leading-7" style={{ color: "var(--neu-text-muted)" }}>
          {description}
        </p>
      </div>
      {(primaryAction || secondaryAction) ? (
        <div className="flex flex-wrap justify-center gap-2">
          {primaryAction}
          {secondaryAction}
        </div>
      ) : null}
    </NeuSurface>
  );
}

export function NeuSkeleton({
  shape = "card",
  lines = 3,
  height,
  width,
}: {
  shape?: "text" | "card" | "chart" | "table";
  lines?: number;
  height?: number | string;
  width?: number | string;
}) {
  if (shape === "text") {
    return (
      <div className="space-y-2">
        {Array.from({ length: lines }).map((_, index) => (
          <div
            key={index}
            className="neu-skeleton-shimmer rounded-full"
            style={{
              height: index === lines - 1 ? 10 : 12,
              width: index === lines - 1 ? "68%" : "100%",
            }}
          />
        ))}
      </div>
    );
  }

  return (
    <div
      className="neu-skeleton-shimmer rounded-[var(--neu-radius-lg)]"
      style={{
        height: height ?? (shape === "chart" ? 260 : shape === "table" ? 320 : 180),
        width,
        boxShadow: "var(--neu-shadow-inset)",
      }}
    />
  );
}

export function NeuPagination({
  page,
  pageSize,
  total,
  onPageChange,
  onPageSizeChange,
  compact = false,
}: NeuPaginationState & {
  onPageChange: (page: number) => void;
  onPageSizeChange?: (pageSize: number) => void;
  compact?: boolean;
}) {
  const pageCount = Math.max(1, Math.ceil(total / pageSize));

  return (
    <NeuSurface depth="raised" radius="md" padding="sm" className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="text-sm" style={{ color: "var(--neu-text-muted)" }}>
        Page {page} of {pageCount}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <NeuButton size="sm" variant="secondary" onClick={() => onPageChange(Math.max(1, page - 1))} disabled={page <= 1}>
          <ChevronLeft className="size-4" />
          {!compact ? "Previous" : null}
        </NeuButton>
        <NeuStatusPill label={`${total} records`} tone="neutral" />
        <NeuButton size="sm" variant="secondary" onClick={() => onPageChange(Math.min(pageCount, page + 1))} disabled={page >= pageCount}>
          {!compact ? "Next" : null}
          <ChevronRight className="size-4" />
        </NeuButton>
        {onPageSizeChange ? (
          <div className="ml-2 flex items-center gap-2 text-xs font-semibold" style={{ color: "var(--neu-text-muted)" }}>
            <span>Rows</span>
            {[10, 25, 50].map((size) => (
              <button
                key={size}
                type="button"
                onClick={() => onPageSizeChange(size)}
                className={cn(
                  "neu-surface-base rounded-[var(--neu-radius-pill)] px-2.5 py-1",
                  size === pageSize ? "neu-surface-accent neu-pill-solid" : "neu-surface-raised neu-pill-soft",
                )}
              >
                {size}
              </button>
            ))}
          </div>
        ) : null}
      </div>
    </NeuSurface>
  );
}

export function NeuKpiGrid({
  items,
  columns = "responsive",
  dense = false,
}: {
  items: NeuMetric[];
  columns?: "2-up" | "4-up" | "responsive";
  dense?: boolean;
}) {
  return (
    <div
      className={cn(
        "grid gap-3",
        columns === "2-up" && "md:grid-cols-2",
        columns === "4-up" && "md:grid-cols-2 xl:grid-cols-4",
        columns === "responsive" && "md:grid-cols-2 xl:grid-cols-4",
      )}
    >
      {items.map((item) => (
        <NeuSurface key={`${item.label}-${item.value}`} depth="raised" radius="md" padding={dense ? "sm" : "md"} className="space-y-2">
          <div className="flex items-center justify-between gap-3">
            <p className="text-[11px] font-semibold uppercase tracking-[0.18em]" style={{ color: "var(--neu-text-muted)" }}>
              {item.label}
            </p>
            {item.icon}
          </div>
          <div className="text-2xl font-semibold tracking-[-0.04em]" style={{ color: toneColor(item.tone ?? "neutral") }}>
            {item.value}
          </div>
          {item.delta ? (
            <div className="text-xs font-semibold" style={{ color: "var(--neu-text-muted)" }}>
              {item.delta}
            </div>
          ) : null}
        </NeuSurface>
      ))}
    </div>
  );
}

export function NeuTickerMetric({
  icon,
  label,
  value,
  detail,
  tone = "neutral",
  compact = false,
}: {
  icon?: ReactNode;
  label: ReactNode;
  value: ReactNode;
  detail?: ReactNode;
  tone?: Extract<NeuTone, "accent" | "success" | "warning" | "danger" | "neutral">;
  compact?: boolean;
}) {
  return (
    <div
      className={compact ? "rounded-[var(--neu-radius-sm)] px-2.5 py-2" : "min-w-[9rem] rounded-[var(--neu-radius-sm)] px-3 py-2.5"}
    >
      <div className="flex items-center gap-2">
        {icon}
        <span className="text-[11px] font-semibold uppercase tracking-[0.18em]" style={{ color: "var(--neu-text-muted)" }}>
          {label}
        </span>
      </div>
      <div className="mt-2 text-base font-semibold" style={{ color: toneColor(tone) }}>
        {value}
      </div>
      {detail ? (
        <div className="mt-1 text-xs" style={{ color: "var(--neu-text-muted)" }}>
          {detail}
        </div>
      ) : null}
    </div>
  );
}

export function NeuScoreBar({
  score,
  scale = 10,
  direction = "neutral",
}: {
  score: number;
  scale?: number;
  direction?: "buy" | "sell" | "neutral";
}) {
  const width = `${Math.min(100, Math.max(0, (Math.abs(score) / scale) * 100))}%`;
  const tone = direction === "buy" ? "success" : direction === "sell" ? "danger" : "warning";

  return (
    <div className="flex items-center gap-3">
      <div className="neu-surface-base neu-surface-inset h-3.5 w-full rounded-[var(--neu-radius-pill)] p-0.5">
        <div
          className="h-full rounded-[var(--neu-radius-pill)]"
          style={{
            width,
            background: `linear-gradient(90deg, ${toneColor(tone)}, color-mix(in oklch, ${toneColor(tone)} 44%, white))`,
          }}
        />
      </div>
      <span className="w-12 text-right font-mono text-xs font-semibold">{score > 0 ? `+${score}` : score}</span>
    </div>
  );
}

export function NeuProgressTrack({
  value,
  max,
  tone = "accent",
  indeterminate = false,
  segmented = false,
}: {
  value: number;
  max: number;
  tone?: NeuTone;
  indeterminate?: boolean;
  segmented?: boolean;
}) {
  const width = `${Math.min(100, Math.max(0, (value / max) * 100))}%`;
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-xs font-semibold" style={{ color: "var(--neu-text-muted)" }}>
        <span>{indeterminate ? "Syncing" : `${value} / ${max}`}</span>
        <span>{Math.round((value / max) * 100)}%</span>
      </div>
      <div className="neu-surface-base neu-surface-inset rounded-[var(--neu-radius-pill)] p-1">
        <div
          className={cn("h-3 rounded-[var(--neu-radius-pill)]", indeterminate && "animate-pulse")}
          style={{
            width: indeterminate ? "34%" : width,
            background: segmented
              ? `repeating-linear-gradient(90deg, ${toneColor(tone)}, ${toneColor(tone)} 10px, color-mix(in oklch, ${toneColor(tone)} 34%, white) 10px, color-mix(in oklch, ${toneColor(tone)} 34%, white) 20px)`
              : `linear-gradient(90deg, ${toneColor(tone)}, color-mix(in oklch, ${toneColor(tone)} 44%, white))`,
          }}
        />
      </div>
    </div>
  );
}
