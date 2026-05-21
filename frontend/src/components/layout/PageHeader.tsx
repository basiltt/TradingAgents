import type { ReactNode } from "react";
import { AnimatedNumber } from "@/components/ui/animated-number";
import { cn } from "@/lib/utils";

interface HeaderStat {
  label: string;
  value: string;
  tone?: "accent" | "success" | "warning" | "danger" | "neutral";
}

const toneClasses: Record<NonNullable<HeaderStat["tone"]>, string> = {
  accent: "text-primary",
  success: "text-emerald-500",
  warning: "text-amber-500",
  danger: "text-destructive",
  neutral: "text-foreground",
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
        "page-hero grid gap-4 overflow-hidden rounded-[calc(var(--radius)*2)] border border-border/70 p-4 shadow-[var(--shadow-card)] backdrop-blur-xl sm:p-5 xl:grid-cols-[minmax(0,1fr)_20rem]",
        className,
      )}
    >
      <div className="pointer-events-none absolute inset-0 opacity-90">
        <div className="absolute -right-16 top-[-6rem] h-48 w-48 rounded-full bg-[radial-gradient(circle,oklch(0.72_var(--accent-chroma)_var(--accent-hue)_/_0.22),transparent_72%)] blur-3xl" />
        <div className="absolute bottom-[-7rem] left-[-4rem] h-44 w-44 rounded-full bg-[radial-gradient(circle,oklch(0.75_var(--accent-2-chroma)_var(--accent-2-hue)_/_0.18),transparent_74%)] blur-3xl" />
      </div>

      <div className="space-y-3.5">
        {eyebrow ? <p className="section-eyebrow">{eyebrow}</p> : null}
        <div className="space-y-2.5">
          <h1 className="max-w-4xl text-[1.8rem] font-semibold tracking-[-0.04em] text-foreground sm:text-[2rem] lg:text-[2.35rem]">
            {title}
          </h1>
          {description ? (
            <p className="max-w-3xl text-[0.9rem] leading-6 text-muted-foreground sm:text-[0.95rem]">
              {description}
            </p>
          ) : null}
        </div>
        {children}
      </div>

      {(actions || stats.length > 0) && (
        <div className="flex min-w-[15.5rem] flex-col gap-3.5 xl:max-w-sm">
          {actions ? (
            <div className="flex flex-wrap justify-start gap-2.5 xl:justify-end">{actions}</div>
          ) : (
            <div className="hidden xl:block" />
          )}
          {stats.length > 0 && (
            <div className="grid gap-2.5 sm:grid-cols-2 xl:grid-cols-1">
              {stats.map((stat) => (
                <div
                  key={`${stat.label}-${stat.value}`}
                  data-tone={stat.tone ?? "neutral"}
                  className={cn(
                    "page-header-stat rounded-[calc(var(--radius)*1.35)] border p-3 shadow-[var(--shadow-soft)] backdrop-blur-md",
                    toneClasses[stat.tone ?? "neutral"],
                  )}
                >
                  <p className="text-[10px] font-semibold uppercase tracking-[0.2em] opacity-80">
                    {stat.label}
                  </p>
                  <p className="mt-1.5 text-lg font-semibold tracking-tight">
                    <AnimatedNumber value={stat.value} />
                  </p>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
