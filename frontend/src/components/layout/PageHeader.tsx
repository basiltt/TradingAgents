import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

interface HeaderStat {
  label: string;
  value: string;
  tone?: "accent" | "success" | "warning" | "danger" | "neutral";
}

const toneClasses: Record<NonNullable<HeaderStat["tone"]>, string> = {
  accent: "border-primary/25 bg-primary/10 text-primary",
  success: "border-emerald-500/20 bg-emerald-500/10 text-emerald-500",
  warning: "border-amber-500/20 bg-amber-500/10 text-amber-500",
  danger: "border-destructive/20 bg-destructive/10 text-destructive",
  neutral: "border-border/70 bg-background/80 text-foreground shadow-[var(--shadow-soft)]",
};

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
  stats = [],
  children,
  className,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  actions?: ReactNode;
  stats?: HeaderStat[];
  children?: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={cn(
        "page-hero grid gap-5 overflow-hidden rounded-[calc(var(--radius)*2.2)] border border-border/70 p-5 shadow-[var(--shadow-card)] backdrop-blur-xl sm:p-6 xl:grid-cols-[minmax(0,1fr)_auto]",
        className,
      )}
    >
      <div className="space-y-4">
        {eyebrow ? <p className="section-eyebrow">{eyebrow}</p> : null}
        <div className="space-y-2">
          <h1 className="text-3xl font-semibold tracking-tight text-foreground sm:text-4xl">
            {title}
          </h1>
          {description ? (
            <p className="max-w-3xl text-sm leading-6 text-muted-foreground sm:text-base">
              {description}
            </p>
          ) : null}
        </div>
        {children}
      </div>

      {(actions || stats.length > 0) && (
        <div className="flex min-w-[18rem] flex-col justify-between gap-4 xl:max-w-sm">
          {actions ? <div className="flex flex-wrap justify-start gap-3 xl:justify-end">{actions}</div> : <div />}
          {stats.length > 0 && (
            <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-1">
              {stats.map((stat) => (
                <div
                  key={`${stat.label}-${stat.value}`}
                  className={cn(
                    "rounded-[calc(var(--radius)*1.5)] border p-3 shadow-[var(--shadow-soft)] backdrop-blur-md",
                    toneClasses[stat.tone ?? "neutral"],
                  )}
                >
                  <p className="text-[11px] font-semibold uppercase tracking-[0.22em] opacity-80">
                    {stat.label}
                  </p>
                  <p className="mt-2 text-xl font-semibold tracking-tight">{stat.value}</p>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
