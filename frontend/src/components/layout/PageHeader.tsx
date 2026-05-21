import type { ReactNode } from "react";
import { AnimatedNumber } from "@/components/ui/animated-number";
import { NeuPageHeader } from "@/design-system/neumorphism";

interface HeaderStat {
  label: string;
  value: string;
  tone?: "accent" | "success" | "warning" | "danger" | "neutral";
}

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
    <NeuPageHeader
      eyebrow={eyebrow}
      title={title}
      description={description}
      actions={actions}
      variant="overview"
      className={className}
      stats={stats.map((stat) => ({
        label: stat.label,
        value: <AnimatedNumber value={stat.value} />,
        tone: stat.tone ?? "neutral",
      }))}
    >
      {children}
    </NeuPageHeader>
  );
}
