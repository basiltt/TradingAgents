import type { ReactNode } from "react";
import { ChevronLeft } from "lucide-react";
import { cn } from "@/lib/utils";
import { NeuButton } from "./inputs";
import { NeuSurface } from "./foundation";
import type { NeuMetric, NeuTone } from "./types";

const toneMap: Record<NeuTone, string> = {
  neutral: "var(--neu-text-strong)",
  accent: "var(--neu-accent)",
  success: "var(--neu-success)",
  warning: "var(--neu-warning)",
  danger: "var(--neu-danger)",
};

function toneBackground(tone: NeuTone) {
  if (tone === "accent") {
    return "color-mix(in oklch, var(--neu-accent-muted) 84%, var(--neu-surface-raised))";
  }
  if (tone === "success") {
    return "color-mix(in oklch, var(--neu-success) 14%, var(--neu-surface-raised))";
  }
  if (tone === "warning") {
    return "color-mix(in oklch, var(--neu-warning) 14%, var(--neu-surface-raised))";
  }
  if (tone === "danger") {
    return "color-mix(in oklch, var(--neu-danger) 14%, var(--neu-surface-raised))";
  }
  return "color-mix(in oklch, var(--neu-surface-raised) 92%, transparent)";
}

export function NeuStatusPill({
  label,
  tone = "neutral",
  icon,
  animated = false,
}: {
  label: ReactNode;
  tone?: NeuTone;
  icon?: ReactNode;
  animated?: boolean;
}) {
  return (
    <span
      className="neu-surface-base neu-surface-raised neu-pill-soft inline-flex min-h-8 items-center gap-2 rounded-[var(--neu-radius-pill)] px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em]"
      style={{
        color: toneMap[tone],
        background: toneBackground(tone),
        borderColor: "color-mix(in oklch, currentColor 18%, var(--neu-stroke-soft))",
      }}
    >
      <span
        className={cn("inline-flex size-2.5 rounded-full", animated && "animate-pulse")}
        style={{ background: "currentColor" }}
      />
      {icon}
      {label}
    </span>
  );
}

export function NeuStatCapsule({
  label,
  value,
  tone = "neutral",
  trend = "flat",
  icon,
  delta,
}: NeuMetric) {
  const trendGlyph = trend === "up" ? "↗" : trend === "down" ? "↘" : "•";

  return (
    <div
      className="neu-surface-base neu-surface-raised flex min-w-[10rem] flex-col gap-2 rounded-[var(--neu-radius-md)] p-3.5"
      style={{
        borderColor: "color-mix(in oklch, currentColor 12%, var(--neu-stroke-soft))",
        color: toneMap[tone],
        background:
          tone === "neutral"
            ? undefined
            : `linear-gradient(145deg, color-mix(in oklch, ${toneMap[tone]} 8%, var(--neu-highlight)), color-mix(in oklch, ${toneMap[tone]} 8%, var(--neu-surface-raised)) 60%, var(--neu-surface-raised))`,
      }}
    >
      <div className="flex items-center justify-between gap-3">
        <span className="text-[11px] font-semibold uppercase tracking-[0.18em] opacity-80">
          {label}
        </span>
        {icon}
      </div>
      <div className="text-lg font-semibold tracking-[-0.03em]">{value}</div>
      {(delta || trend !== "flat") && (
        <div className="flex items-center gap-2 text-xs font-semibold">
          <span>{trendGlyph}</span>
          {delta}
        </div>
      )}
    </div>
  );
}

export function NeuPageHeader({
  eyebrow,
  title,
  description,
  actions,
  stats,
  meta,
  children,
  variant = "standard",
  className,
}: {
  eyebrow?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  stats?: NeuMetric[];
  meta?: ReactNode;
  children?: ReactNode;
  variant?: "overview" | "standard" | "dense";
  className?: string;
}) {
  const isDense = variant === "dense";

  return (
    <NeuSurface
      depth={variant === "overview" ? "accent" : "raised"}
      radius="lg"
      padding={isDense ? "md" : "lg"}
      className={cn("space-y-5", className)}
    >
      <div className="flex flex-col gap-5 xl:flex-row xl:items-start xl:justify-between">
        <div className="space-y-3">
          {eyebrow ? (
            <p className="text-[11px] font-semibold uppercase tracking-[0.26em]" style={{ color: "var(--neu-text-muted)" }}>
              {eyebrow}
            </p>
          ) : null}
          <div className="space-y-2">
            <h1 className={cn(isDense ? "text-2xl" : "text-3xl md:text-[2.4rem]", "font-semibold tracking-[-0.05em]")}>
              {title}
            </h1>
            {description ? (
              <p className="max-w-4xl text-sm leading-7 md:text-base" style={{ color: "var(--neu-text-muted)" }}>
                {description}
              </p>
            ) : null}
          </div>
          {meta}
          {children}
        </div>

        {(actions || stats?.length) && (
          <div className="flex w-full max-w-xl flex-col gap-3 xl:items-end">
            {actions ? <div className="flex flex-wrap gap-2 xl:justify-end">{actions}</div> : null}
            {stats?.length ? (
              <div className={cn("grid gap-3", variant === "dense" ? "sm:grid-cols-2" : "sm:grid-cols-2")}>
                {stats.map((stat) => (
                  <NeuStatCapsule key={`${stat.label}-${stat.value}`} {...stat} />
                ))}
              </div>
            ) : null}
          </div>
        )}
      </div>
    </NeuSurface>
  );
}

export function NeuEntityHeader({
  title,
  subtitle,
  backTo,
  status,
  actions,
  stats,
  variant = "detail",
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  backTo?: { label: string; href?: string; onBack?: () => void };
  status?: ReactNode;
  actions?: ReactNode;
  stats?: NeuMetric[];
  variant?: "detail" | "critical" | "archived";
}) {
  const tone = variant === "critical" ? "danger" : variant === "archived" ? "warning" : "accent";

  return (
    <NeuSurface
      depth="raised"
      radius="lg"
      padding="lg"
      className="space-y-5"
      style={{
        borderColor: `color-mix(in oklch, ${toneMap[tone]} 22%, var(--neu-stroke-soft))`,
        background:
          tone === "accent"
            ? "linear-gradient(145deg, color-mix(in oklch, var(--neu-highlight) 22%, transparent), transparent 46%, color-mix(in oklch, var(--neu-accent) 6%, transparent))"
            : undefined,
      }}
    >
      <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
        <div className="space-y-3">
          {backTo ? (
            <NeuButton variant="ghost" size="sm" onClick={backTo.onBack}>
              <ChevronLeft className="size-4" />
              {backTo.label}
            </NeuButton>
          ) : null}
          <div className="space-y-2">
            <h1 className="text-3xl font-semibold tracking-[-0.05em]">{title}</h1>
            {subtitle ? (
              <p className="text-sm leading-7 md:text-base" style={{ color: "var(--neu-text-muted)" }}>
                {subtitle}
              </p>
            ) : null}
          </div>
          {status}
        </div>

        {actions ? <div className="flex flex-wrap gap-2 xl:justify-end">{actions}</div> : null}
      </div>

      {stats?.length ? (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          {stats.map((stat) => (
            <NeuStatCapsule key={`${stat.label}-${stat.value}`} {...stat} />
          ))}
        </div>
      ) : null}
    </NeuSurface>
  );
}
