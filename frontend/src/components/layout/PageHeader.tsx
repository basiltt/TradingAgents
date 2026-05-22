import type { ReactNode } from "react";
import { AnimatedNumber } from "@/components/ui/animated-number";
import { cn } from "@/lib/utils";

interface HeaderStat {
  label: string;
  value: string;
  tone?: "accent" | "success" | "warning" | "danger" | "neutral";
}

const toneClasses: Record<NonNullable<HeaderStat["tone"]>, string> = {
  accent: "page-header-stat text-primary",
  success: "page-header-stat text-[var(--success)]",
  warning: "page-header-stat text-[var(--warning)]",
  danger: "page-header-stat text-destructive",
  neutral: "page-header-stat text-foreground",
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
    <section className={cn("rounded-[calc(var(--radius)*1.5)] sm:rounded-[calc(var(--radius)*2)] p-3.5 sm:p-5 lg:p-7 shadow-[var(--shadow-card)]", className)}>
      <div className="flex flex-col gap-3 sm:gap-5">
        <div className="flex flex-col gap-3 sm:gap-4 xl:flex-row xl:items-center xl:justify-between">
          <div className="space-y-1">
            {eyebrow ? <p className="section-eyebrow hidden sm:block">{eyebrow}</p> : null}
            <h1 className="text-lg sm:text-2xl font-bold tracking-[-0.04em] text-foreground">
              {title}
            </h1>
            {description ? (
              <p className="text-xs sm:text-sm text-muted-foreground leading-relaxed">{description}</p>
            ) : null}
          </div>

          {actions ? (
            <div className="flex flex-wrap gap-2 sm:gap-2.5 xl:justify-end">
              {actions}
            </div>
          ) : null}
        </div>

        {children}

        {stats.length > 0 ? (
          <div className="grid grid-cols-2 gap-2 sm:gap-3.5 lg:grid-cols-4">
            {stats.map((stat) => {
              const tone = stat.tone ?? "neutral";
              return (
                <div
                  key={`${stat.label}-${stat.value}`}
                  data-tone={tone}
                  className={cn(
                    "rounded-[calc(var(--radius)*1.1)] sm:rounded-[calc(var(--radius)*1.3)] p-2.5 sm:p-4 shadow-[var(--shadow-inset)]",
                    toneClasses[tone],
                  )}
                >
                  <p className="text-[9px] sm:text-[10px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                    {stat.label}
                  </p>
                  <div className="mt-1 sm:mt-2 text-base sm:text-xl font-bold tracking-[-0.04em] text-foreground">
                    <AnimatedNumber value={stat.value} />
                  </div>
                </div>
              );
            })}
          </div>
        ) : null}
      </div>
    </section>
  );
}
