import type { CSSProperties, ReactNode } from "react";
import {
  BellRing,
  Hand,
  LayoutTemplate,
  Monitor,
  PanelBottom,
  PanelRight,
  Smartphone,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { NeuBadge, NeuCard } from "./display";
import { NeuDivider, NeuSurface, NeuWell } from "./foundation";
import type { NeuRouteLayoutModel, NeuTone } from "./types";

function emphasisTone(
  emphasis?: "primary" | "secondary" | "supporting" | "actions",
): NeuTone {
  if (emphasis === "primary") return "accent";
  if (emphasis === "secondary") return "success";
  if (emphasis === "actions") return "warning";
  return "neutral";
}

function zoneIcon(label: string) {
  if (label.toLowerCase().includes("drawer")) return <PanelRight className="size-4" />;
  if (label.toLowerCase().includes("dock")) return <PanelBottom className="size-4" />;
  return <LayoutTemplate className="size-4" />;
}

export function NeuPageSection({
  eyebrow,
  title,
  description,
  badge,
  actions,
  tone = "neutral",
  dense = false,
  footer,
  className,
  children,
}: {
  eyebrow?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  badge?: ReactNode;
  actions?: ReactNode;
  tone?: NeuTone;
  dense?: boolean;
  footer?: ReactNode;
  className?: string;
  children?: ReactNode;
}) {
  return (
    <NeuSurface
      depth="raised"
      tone={tone}
      radius="lg"
      padding={dense ? "sm" : "md"}
      className={cn("space-y-4", className)}
    >
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div className="space-y-2">
          {(eyebrow || badge) && (
            <div className="flex flex-wrap items-center gap-2">
              {eyebrow ? (
                <span
                  className="text-[11px] font-semibold uppercase tracking-[0.18em]"
                  style={{ color: "var(--neu-text-muted)" }}
                >
                  {eyebrow}
                </span>
              ) : null}
              {badge}
            </div>
          )}
          <div className="space-y-1">
            <h3 className="text-lg font-semibold tracking-[-0.03em]">{title}</h3>
            {description ? (
              <p className="max-w-3xl text-sm leading-7" style={{ color: "var(--neu-text-muted)" }}>
                {description}
              </p>
            ) : null}
          </div>
        </div>
        {actions ? <div className="flex flex-wrap gap-2">{actions}</div> : null}
      </div>
      {children}
      {footer ? (
        <>
          <NeuDivider />
          <div className="flex flex-wrap items-center justify-between gap-3">{footer}</div>
        </>
      ) : null}
    </NeuSurface>
  );
}

export function NeuFormGrid({
  columns = "responsive",
  className,
  children,
}: {
  columns?: "2-up" | "3-up" | "responsive";
  className?: string;
  children?: ReactNode;
}) {
  return (
    <div
      className={cn(
        "grid gap-4",
        columns === "2-up" && "md:grid-cols-2",
        columns === "3-up" && "md:grid-cols-2 xl:grid-cols-3",
        columns === "responsive" && "md:grid-cols-2 xl:grid-cols-3",
        className,
      )}
    >
      {children}
    </div>
  );
}

export function NeuFormSection({
  title,
  description,
  actions,
  footer,
  columns = "responsive",
  className,
  children,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  footer?: ReactNode;
  columns?: "2-up" | "3-up" | "responsive";
  className?: string;
  children?: ReactNode;
}) {
  return (
    <NeuPageSection
      eyebrow="Form group"
      title={title}
      description={description}
      actions={actions}
      className={className}
      footer={footer}
    >
      <NeuWell padding="sm" className="space-y-4">
        <NeuFormGrid columns={columns}>{children}</NeuFormGrid>
      </NeuWell>
    </NeuPageSection>
  );
}

export function NeuSplitLayout({
  primary,
  secondary,
  aside,
  asideWidth = "22rem",
  stickyAside = false,
  className,
}: {
  primary: ReactNode;
  secondary?: ReactNode;
  aside?: ReactNode;
  asideWidth?: `${number}rem`;
  stickyAside?: boolean;
  className?: string;
}) {
  return (
    <div
      className={cn("grid gap-5", aside ? "xl:grid-cols-[minmax(0,1fr)_var(--neu-aside-width)]" : "grid-cols-1", className)}
      style={{ ["--neu-aside-width" as string]: asideWidth } as CSSProperties}
    >
      <div className="space-y-5">
        {primary}
        {secondary}
      </div>
      {aside ? (
        <div className={cn("space-y-5", stickyAside && "xl:sticky xl:top-5 self-start")}>
          {aside}
        </div>
      ) : null}
    </div>
  );
}

export interface NeuAlertItem {
  id: string;
  tone?: NeuTone;
  title: ReactNode;
  description?: ReactNode;
  badge?: ReactNode;
  meta?: ReactNode;
  actions?: ReactNode;
}

export function NeuAlertStack({
  items,
  compact = false,
}: {
  items: NeuAlertItem[];
  compact?: boolean;
}) {
  return (
    <div className="space-y-3">
      {items.map((item) => (
        <NeuSurface
          key={item.id}
          depth="raised"
          tone={item.tone ?? "neutral"}
          radius="md"
          padding={compact ? "sm" : "md"}
          className="space-y-3"
        >
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div className="flex min-w-0 gap-3">
              <span className="inline-flex size-11 shrink-0 items-center justify-center rounded-[var(--neu-radius-md)] neu-surface-base neu-surface-accent shadow-[var(--neu-shadow-pill)]">
                <BellRing className="size-4.5" />
              </span>
              <div className="min-w-0 space-y-1">
                <div className="flex flex-wrap items-center gap-2">
                  <p className="text-sm font-semibold">{item.title}</p>
                  {item.badge}
                </div>
                {item.description ? (
                  <p className="text-sm leading-6" style={{ color: "var(--neu-text-muted)" }}>
                    {item.description}
                  </p>
                ) : null}
              </div>
            </div>
            {item.meta ? <div className="text-xs font-semibold" style={{ color: "var(--neu-text-muted)" }}>{item.meta}</div> : null}
          </div>
          {item.actions ? <div className="flex flex-wrap gap-2">{item.actions}</div> : null}
        </NeuSurface>
      ))}
    </div>
  );
}

export function NeuTouchActionBar({
  title,
  description,
  actions,
  meta,
  fixed = false,
}: {
  title?: ReactNode;
  description?: ReactNode;
  actions: ReactNode;
  meta?: ReactNode;
  fixed?: boolean;
}) {
  return (
    <div
      className={cn(fixed && "sticky bottom-0 z-30")}
      style={fixed ? { paddingBottom: "max(env(safe-area-inset-bottom), 0.75rem)" } : undefined}
    >
      <NeuSurface
        depth="raised"
        radius="lg"
        padding="sm"
        className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between"
      >
        <div className="min-w-0 space-y-1">
          {title ? <p className="text-sm font-semibold">{title}</p> : null}
          {description ? (
            <p className="text-xs leading-6" style={{ color: "var(--neu-text-muted)" }}>
              {description}
            </p>
          ) : null}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {meta}
          {actions}
        </div>
      </NeuSurface>
    </div>
  );
}

function renderZoneList(
  title: ReactNode,
  tone: NeuTone,
  icon: ReactNode,
  zones: NeuRouteLayoutModel["desktopZones"],
) {
  return (
    <NeuWell padding="sm" className="space-y-3">
      <div className="flex items-center gap-2">
        <span className="inline-flex size-8 items-center justify-center rounded-[var(--neu-radius-sm)] neu-surface-base neu-surface-raised">
          {icon}
        </span>
        <p className="text-sm font-semibold">{title}</p>
      </div>
      <div className="space-y-2">
        {zones.map((zone) => (
          <div key={zone.id} className="rounded-[var(--neu-radius-md)] neu-surface-base neu-surface-raised p-3">
            <div className="flex flex-wrap items-center gap-2">
              <p className="text-sm font-semibold">{zone.label}</p>
              <NeuBadge tone={emphasisTone(zone.emphasis)} variant="soft" size="sm" icon={zoneIcon(zone.label)}>
                {zone.emphasis ?? "support"}
              </NeuBadge>
            </div>
            {zone.description ? (
              <p className="mt-1 text-xs leading-6" style={{ color: "var(--neu-text-muted)" }}>
                {zone.description}
              </p>
            ) : null}
          </div>
        ))}
      </div>
      <div className="text-[11px] font-semibold uppercase tracking-[0.18em]" style={{ color: tone === "accent" ? "var(--neu-accent)" : "var(--neu-text-muted)" }}>
        {tone === "accent" ? "Desktop hierarchy" : "Mobile stacking"}
      </div>
    </NeuWell>
  );
}

export function NeuRouteModelCard({
  model,
}: {
  model: NeuRouteLayoutModel;
}) {
  return (
    <NeuCard
      title={model.title}
      description={model.route}
      actions={
        <div className="flex flex-wrap gap-2">
          <NeuBadge tone="accent" variant="soft" size="sm">
            {model.template}
          </NeuBadge>
          <NeuBadge tone="neutral" variant="outline" size="sm">
            {model.navSection}
          </NeuBadge>
        </div>
      }
      footer={
        <>
          <div className="flex flex-wrap gap-2">
            <NeuBadge tone="warning" variant="soft" size="sm" icon={<Hand className="size-3.5" />}>
              {model.touchActions?.length ?? 0} touch actions
            </NeuBadge>
            <NeuBadge tone="success" variant="soft" size="sm" icon={<PanelRight className="size-3.5" />}>
              {model.drawers?.length ?? 0} drawers
            </NeuBadge>
          </div>
          <NeuBadge tone="accent" variant="outline" size="sm">
            {model.headerVariant} header
          </NeuBadge>
        </>
      }
      className="space-y-4"
    >
      <div className="grid gap-4 xl:grid-cols-2">
        {renderZoneList("Desktop", "accent", <Monitor className="size-4" />, model.desktopZones)}
        {renderZoneList("Mobile", "neutral", <Smartphone className="size-4" />, model.mobileZones)}
      </div>

      {(model.alerts?.length || model.drawers?.length || model.touchActions?.length) ? (
        <div className="grid gap-3 md:grid-cols-3">
          <NeuWell padding="sm" className="space-y-2">
            <p className="text-[11px] font-semibold uppercase tracking-[0.18em]" style={{ color: "var(--neu-text-muted)" }}>
              Alerts
            </p>
            <div className="flex flex-wrap gap-2">
              {model.alerts?.map((entry) => (
                <NeuBadge key={entry} tone="warning" variant="soft" size="sm">
                  {entry}
                </NeuBadge>
              ))}
            </div>
          </NeuWell>
          <NeuWell padding="sm" className="space-y-2">
            <p className="text-[11px] font-semibold uppercase tracking-[0.18em]" style={{ color: "var(--neu-text-muted)" }}>
              Drawers
            </p>
            <div className="flex flex-wrap gap-2">
              {model.drawers?.map((entry) => (
                <NeuBadge key={entry} tone="accent" variant="outline" size="sm">
                  {entry}
                </NeuBadge>
              ))}
            </div>
          </NeuWell>
          <NeuWell padding="sm" className="space-y-2">
            <p className="text-[11px] font-semibold uppercase tracking-[0.18em]" style={{ color: "var(--neu-text-muted)" }}>
              Touch
            </p>
            <div className="flex flex-wrap gap-2">
              {model.touchActions?.map((entry) => (
                <NeuBadge key={entry} tone="success" variant="soft" size="sm">
                  {entry}
                </NeuBadge>
              ))}
            </div>
          </NeuWell>
        </div>
      ) : null}
    </NeuCard>
  );
}
