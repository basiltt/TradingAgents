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
    <section className={cn("page-hero glass-card relative overflow-hidden rounded-[calc(var(--radius)*2)] p-4 sm:p-5 lg:p-6", className)}>
      <div className="relative z-10 flex flex-col gap-5">
        <div className="flex flex-col gap-5 xl:flex-row xl:items-start xl:justify-between">
          <div className="max-w-4xl space-y-3">
            {eyebrow ? <p className="section-eyebrow">{eyebrow}</p> : null}
            <div className="space-y-3">
              <h1 className="max-w-3xl text-3xl font-semibold tracking-[-0.06em] text-foreground sm:text-4xl lg:text-[2.75rem]">
                {title}
              </h1>
              {description ? (
                <p className="max-w-3xl text-sm leading-7 text-muted-foreground sm:text-[0.97rem]">
                  {description}
                </p>
              ) : null}
            </div>
          </div>

          {actions ? (
            <div className="flex w-full flex-wrap gap-2 xl:w-auto xl:max-w-[28rem] xl:justify-end">
              {actions}
            </div>
          ) : null}
        </div>

        {children ? (
          <div className="surface-lift rounded-[calc(var(--radius)*1.45)] p-3.5 sm:p-4">
            {children}
          </div>
        ) : null}

        {stats.length > 0 ? (
          <div className="grid gap-3 sm:grid-cols-2 2xl:grid-cols-4">
            {stats.map((stat) => {
              const tone = stat.tone ?? "neutral";
              return (
                <div
                  key={`${stat.label}-${stat.value}`}
                  data-tone={tone}
                  className={cn(
                    "surface-lift rounded-[calc(var(--radius)*1.35)] border p-4 sm:p-4.5",
                    toneClasses[tone],
                  )}
                >
                  <div className="space-y-2 pl-2">
                    <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                      {stat.label}
                    </p>
                    <div className="text-xl font-semibold tracking-[-0.05em] text-foreground sm:text-2xl">
                      <AnimatedNumber value={stat.value} />
                    </div>
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
