import { useMemo } from "react";
import {
  Command,
  Contrast,
  Menu,
  Monitor,
  MoonStar,
  Search,
  SunMedium,
  SwatchBook,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { NeuSurface } from "./foundation";
import { NeuButton, NeuInput, NeuToggleGroup } from "./inputs";
import { NeuBadge, NeuTickerMetric } from "./display";
import { getNeuAccentPreview, neuAccentDefinitions, neuAccentPalettes } from "./theme";
import type {
  NeuAccentPalette,
  NeuCommandGroup,
  NeuContrastMode,
  NeuNavSection,
  NeuSurfaceMode,
  NeuTone,
} from "./types";

export function NeuNavItem({
  icon: Icon,
  label,
  description,
  active = false,
  badge,
  meta,
  href,
  onClick,
  compact = false,
  touchFriendly = false,
}: {
  icon?: React.ComponentType<{ className?: string }>;
  label: string;
  description?: string;
  active?: boolean;
  badge?: React.ReactNode;
  meta?: React.ReactNode;
  href?: string;
  onClick?: () => void;
  compact?: boolean;
  touchFriendly?: boolean;
}) {
  const content = (
    <div
      className={cn(
        "flex items-center gap-3 rounded-[var(--neu-radius-md)] transition",
        touchFriendly ? "min-h-14 px-3.5 py-3 sm:min-h-0 sm:px-3 sm:py-2.5" : "px-3 py-2.5",
        active ? "neu-surface-base neu-surface-accent" : "neu-surface-base neu-surface-raised neu-interactive",
      )}
    >
      {Icon ? (
        <span className={cn(
          "inline-flex items-center justify-center rounded-[var(--neu-radius-sm)]",
          touchFriendly ? "size-11 sm:size-10" : "size-10",
          active ? "neu-surface-base neu-surface-raised shadow-[var(--neu-shadow-pill)]" : "neu-surface-base neu-surface-inset",
        )}>
          <Icon className="size-4.5" />
        </span>
      ) : null}
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-semibold">{label}</span>
        {!compact && description ? (
          <span className="mt-1 block truncate text-xs" style={{ color: "var(--neu-text-muted)" }}>
            {description}
          </span>
        ) : null}
      </span>
      <span className="flex shrink-0 items-center gap-2">
        {meta}
        {badge}
      </span>
    </div>
  );

  if (href && !onClick) {
    return (
      <a href={href} className="block" onClick={onClick}>
        {content}
      </a>
    );
  }

  return (
    <button type="button" className="block w-full text-left" onClick={onClick}>
      {content}
    </button>
  );
}

export function NeuSidebar({
  sections,
  activePath,
  onNavigate,
  collapsed = false,
  mode = "desktop",
  footer,
  headerSlot,
}: {
  sections: NeuNavSection[];
  activePath?: string;
  onNavigate?: (href?: string) => void;
  collapsed?: boolean;
  mode?: "desktop" | "mobile-sheet";
  footer?: React.ReactNode;
  headerSlot?: React.ReactNode;
}) {
  return (
    <NeuSurface
      depth="raised"
      radius="lg"
      padding="md"
      className={cn("flex h-full min-h-0 flex-col gap-5", mode === "mobile-sheet" && "min-h-0")}
    >
      <div className="flex items-center gap-3">
        <div className="inline-flex size-12 items-center justify-center rounded-[var(--neu-radius-md)] neu-surface-base neu-surface-accent shadow-[var(--neu-shadow-pill)]">
          <Command className="size-5" />
        </div>
        {!collapsed ? (
          <div>
            <p className="text-base font-semibold tracking-[-0.03em]">TradingAgents</p>
            <p className="text-xs uppercase tracking-[0.18em]" style={{ color: "var(--neu-text-muted)" }}>
              Adaptive workspace
            </p>
          </div>
        ) : null}
        {!collapsed ? <div className="ml-auto">{headerSlot}</div> : null}
      </div>

      <div className="neu-scrollbar neu-surface-base neu-surface-inset flex-1 min-h-0 overflow-auto rounded-[var(--neu-radius-lg)] p-3 pr-2 space-y-5">
        {sections.map((section) => (
          <section key={section.title} className="space-y-2">
            {!collapsed ? (
              <p className="px-2 text-[11px] font-semibold uppercase tracking-[0.18em]" style={{ color: "var(--neu-text-muted)" }}>
                {section.title}
              </p>
            ) : null}
            <div className="space-y-2">
              {section.items.map((item) => (
                <NeuNavItem
                  key={item.id}
                  icon={item.icon}
                  label={collapsed ? item.label.slice(0, 1) : item.label}
                  description={collapsed ? undefined : item.description}
                  active={item.active || item.href === activePath}
                  badge={item.badge}
                  meta={
                    collapsed
                      ? undefined
                      : item.tone === "danger"
                        ? <NeuBadge tone="danger" variant="ghost" size="sm" dot>risk</NeuBadge>
                        : null
                  }
                  href={item.href}
                  compact={collapsed}
                  touchFriendly={mode === "mobile-sheet"}
                  onClick={() => {
                    item.onSelect?.();
                    onNavigate?.(item.href);
                  }}
                />
              ))}
            </div>
          </section>
        ))}
      </div>
      {footer ? <div className="mt-auto">{footer}</div> : null}
    </NeuSurface>
  );
}

export function NeuTopbar({
  section,
  title,
  description,
  actions,
  statusPill,
  condensed = false,
  toolbar,
}: {
  section: React.ReactNode;
  title: React.ReactNode;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  statusPill?: React.ReactNode;
  condensed?: boolean;
  toolbar?: React.ReactNode;
}) {
  return (
    <NeuSurface depth="raised" radius="lg" padding={condensed ? "sm" : "md"} className="space-y-3">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="space-y-1">
          <p className="text-[11px] font-semibold uppercase tracking-[0.18em]" style={{ color: "var(--neu-text-muted)" }}>
            {section}
          </p>
          <div className="flex flex-wrap items-center gap-3">
            <h2 className={cn(condensed ? "text-lg" : "text-xl", "font-semibold tracking-[-0.03em]")}>{title}</h2>
            {statusPill}
          </div>
          {description ? (
            <p className="text-sm leading-6" style={{ color: "var(--neu-text-muted)" }}>
              {description}
            </p>
          ) : null}
        </div>
        {actions ? <div className="flex flex-wrap gap-2">{actions}</div> : null}
      </div>
      {toolbar ? <div>{toolbar}</div> : null}
    </NeuSurface>
  );
}

export function NeuMarketStrip({
  items,
  compact = false,
  scrollable = true,
}: {
  items: Array<{
    id: string;
    label: React.ReactNode;
    value: React.ReactNode;
    detail?: React.ReactNode;
    tone?: NeuTone;
    icon?: React.ReactNode;
  }>;
  compact?: boolean;
  scrollable?: boolean;
}) {
  return (
    <div className={cn("flex gap-3", scrollable && "overflow-x-auto pb-1", compact && "gap-2")}>
      {items.map((item) => (
        <NeuTickerMetric key={item.id} {...item} />
      ))}
    </div>
  );
}

export function NeuMobileDock({
  items,
  activePath,
  onMore,
  onNavigate,
}: {
  items: Array<{
    id: string;
    label: string;
    icon?: React.ReactNode;
    href?: string;
    badge?: React.ReactNode;
    active?: boolean;
    onSelect?: () => void;
  }>;
  activePath?: string;
  onMore?: () => void;
  onNavigate?: (href?: string) => void;
}) {
  return (
    <NeuSurface
      depth="raised"
      radius="full"
      padding="sm"
      className="grid grid-cols-5 gap-2"
      style={{ paddingBottom: "max(env(safe-area-inset-bottom), 0.75rem)" }}
    >
      {items.slice(0, 4).map((item) => {
        const active = item.active || item.href === activePath;
        return (
          <button
            key={item.id}
            type="button"
            onClick={() => {
              item.onSelect?.();
              if (!item.onSelect) {
                onNavigate?.(item.href);
              }
            }}
            className={cn(
              "flex min-h-[4.5rem] flex-col items-center justify-center gap-1 rounded-[var(--neu-radius-md)] px-1.5 text-[11px] font-semibold uppercase tracking-[0.14em]",
              active ? "neu-surface-base neu-surface-accent" : "neu-surface-base neu-surface-inset",
            )}
          >
            <span className="relative inline-flex items-center justify-center">
              {item.icon}
              {item.badge ? <span className="absolute -right-3 -top-2">{item.badge}</span> : null}
            </span>
            <span className="truncate">{item.label}</span>
          </button>
        );
      })}
      <button
        type="button"
        onClick={onMore}
        className="neu-surface-base neu-surface-inset flex min-h-[4.5rem] flex-col items-center justify-center gap-1 rounded-[var(--neu-radius-md)] px-1.5 text-[11px] font-semibold uppercase tracking-[0.14em]"
      >
        <Menu className="size-4.5" />
        More
      </button>
    </NeuSurface>
  );
}

export function NeuCommandPalette({
  open,
  query,
  groups,
  onSelect,
  onOpenChange,
  onQueryChange,
}: {
  open: boolean;
  query: string;
  groups: NeuCommandGroup[];
  onSelect: (commandId: string) => void;
  onOpenChange: (open: boolean) => void;
  onQueryChange?: (query: string) => void;
}) {
  const filteredGroups = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) return groups;
    return groups
      .map((group) => ({
        ...group,
        items: group.items.filter((item) =>
          [item.label, item.description, ...(item.keywords ?? [])]
            .filter(Boolean)
            .some((candidate) => String(candidate).toLowerCase().includes(normalized)),
        ),
      }))
      .filter((group) => group.items.length > 0);
  }, [groups, query]);

  if (!open) return null;

  return (
    <div className="neu-command-overlay fixed inset-0 z-50 flex items-start justify-center px-3 py-8" onClick={() => onOpenChange(false)}>
      <div className="w-full max-w-3xl" onClick={(event) => event.stopPropagation()}>
        <NeuSurface depth="raised" radius="lg" padding="md" className="space-y-4 shadow-[var(--neu-shadow-float)]">
          <div className="flex items-center gap-3">
            <div className="inline-flex size-11 items-center justify-center rounded-[var(--neu-radius-md)] neu-surface-base neu-surface-accent shadow-[var(--neu-shadow-pill)]">
              <Command className="size-5" />
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-base font-semibold tracking-[-0.02em]">Command palette</p>
              <p className="text-sm" style={{ color: "var(--neu-text-muted)" }}>
                Search routes, actions, palettes, and adaptive shell controls.
              </p>
            </div>
            <NeuButton variant="ghost" size="sm" onClick={() => onOpenChange(false)}>
              Close
            </NeuButton>
          </div>

          <NeuInput
            value={query}
            onChange={(event) => onQueryChange?.(event.target.value)}
            placeholder="Search commands or routes"
            leadingIcon={<Search className="size-4" />}
          />

          <div className="neu-scrollbar max-h-[32rem] space-y-4 overflow-auto pr-1">
            {filteredGroups.length === 0 ? (
              <NeuSurface depth="inset" radius="md" padding="lg" className="text-center">
                <p className="text-base font-semibold tracking-[-0.02em]">No matching commands</p>
                <p className="mt-2 text-sm" style={{ color: "var(--neu-text-muted)" }}>
                  Try route names, palette labels, or operational keywords.
                </p>
              </NeuSurface>
            ) : (
              filteredGroups.map((group) => (
                <section key={group.id} className="space-y-2">
                  <p className="px-1 text-[11px] font-semibold uppercase tracking-[0.18em]" style={{ color: "var(--neu-text-muted)" }}>
                    {group.title}
                  </p>
                  <div className="space-y-2">
                    {group.items.map((item) => (
                      <button
                        key={item.id}
                        type="button"
                        onClick={() => {
                          item.onSelect();
                          onSelect(item.id);
                        }}
                        className="neu-surface-base neu-surface-raised neu-interactive flex w-full items-start gap-3 rounded-[var(--neu-radius-md)] px-3.5 py-3 text-left"
                      >
                        <span className="inline-flex size-10 items-center justify-center rounded-[var(--neu-radius-sm)] neu-surface-base neu-surface-inset">
                          {item.icon ?? <Search className="size-4" />}
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="flex flex-wrap items-center gap-2">
                            <span className="text-sm font-semibold">{item.label}</span>
                            {item.active ? <NeuBadge tone="accent" variant="soft">active</NeuBadge> : null}
                          </span>
                          {item.description ? (
                            <span className="mt-1 block text-xs leading-5" style={{ color: "var(--neu-text-muted)" }}>
                              {item.description}
                            </span>
                          ) : null}
                        </span>
                        {item.meta}
                      </button>
                    ))}
                  </div>
                </section>
              ))
            )}
          </div>
        </NeuSurface>
      </div>
    </div>
  );
}

export function NeuAppearanceStudio({
  theme,
  palette,
  contrast,
  onThemeChange,
  onPaletteChange,
  onContrastChange,
  compact = false,
}: {
  theme: NeuSurfaceMode;
  palette: NeuAccentPalette;
  contrast: NeuContrastMode;
  onThemeChange: (theme: NeuSurfaceMode) => void;
  onPaletteChange: (palette: NeuAccentPalette) => void;
  onContrastChange: (contrast: NeuContrastMode) => void;
  compact?: boolean;
}) {
  return (
    <NeuSurface depth="raised" radius="lg" padding={compact ? "sm" : "md"} className="space-y-4">
      <div className="flex items-start gap-3">
        <div className="inline-flex size-11 items-center justify-center rounded-[var(--neu-radius-md)] neu-surface-base neu-surface-accent shadow-[var(--neu-shadow-pill)]">
          <SwatchBook className="size-5" />
        </div>
        <div>
          <p className="text-base font-semibold tracking-[-0.02em]">Appearance studio</p>
          {!compact ? (
            <p className="text-sm leading-6" style={{ color: "var(--neu-text-muted)" }}>
              Switch between the Ivory and Graphite material fields, then tune accents without breaking the single-material illusion.
            </p>
          ) : null}
        </div>
      </div>

      <NeuToggleGroup
        label="Surface mode"
        value={theme}
        onChange={(value) => onThemeChange(value as NeuSurfaceMode)}
        options={[
          { value: "ivory", label: "Ivory", icon: <SunMedium className="size-4" /> },
          { value: "graphite", label: "Graphite", icon: <MoonStar className="size-4" /> },
        ]}
      />

      <div className="space-y-2">
        <p className="text-sm font-semibold tracking-[-0.01em]">Accent palette</p>
        <div className={cn("grid gap-3", compact ? "grid-cols-4" : "grid-cols-2 lg:grid-cols-4")}>
          {neuAccentPalettes.map((accent) => {
            const active = palette === accent;
            return (
              <button
                key={accent}
                type="button"
                onClick={() => onPaletteChange(accent)}
                className={cn(
                  "neu-surface-base overflow-hidden rounded-[var(--neu-radius-md)] p-1 text-left transition",
                  active ? "neu-surface-accent shadow-[var(--neu-shadow-float)]" : "neu-surface-raised neu-interactive",
                )}
              >
                <div className="h-18 rounded-[var(--neu-radius-sm)]" style={{ background: getNeuAccentPreview(theme, accent) }} />
                {!compact ? (
                  <div className="p-2.5">
                    <p className="text-sm font-semibold">{neuAccentDefinitions[accent].label}</p>
                    <p className="mt-1 text-xs leading-5" style={{ color: "var(--neu-text-muted)" }}>
                      {neuAccentDefinitions[accent].description}
                    </p>
                  </div>
                ) : null}
              </button>
            );
          })}
        </div>
      </div>

      <NeuToggleGroup
        label="Contrast"
        value={contrast}
        onChange={(value) => onContrastChange(value as NeuContrastMode)}
        options={[
          { value: "balanced", label: "Balanced", icon: <Monitor className="size-4" /> },
          { value: "high", label: "High", icon: <Contrast className="size-4" /> },
        ]}
        size="sm"
      />
    </NeuSurface>
  );
}

export function NeuAppShell({
  sidebar,
  topbar,
  dock,
  mobileSidebar,
  sidebarWidth = "18rem",
  contentClassName,
  mainClassName,
  children,
}: {
  sidebar: React.ReactNode;
  topbar: React.ReactNode;
  dock?: React.ReactNode;
  mobileSidebar?: React.ReactNode;
  sidebarWidth?: string;
  contentClassName?: string;
  mainClassName?: string;
  children: React.ReactNode;
}) {
  return (
    <div
      className="grid min-h-screen gap-4 lg:grid-cols-[var(--neu-shell-sidebar-width)_minmax(0,1fr)]"
      style={{ ["--neu-shell-sidebar-width" as string]: sidebarWidth }}
    >
      <aside className="hidden self-start lg:block" aria-label="Primary navigation">
        <div className="lg:fixed lg:left-5 lg:top-5 lg:z-20 lg:h-[calc(100vh-2.5rem)] lg:w-[var(--neu-shell-sidebar-width)]">
          {sidebar}
        </div>
      </aside>
      <div className={cn("min-w-0 space-y-4", contentClassName)}>
        {topbar}
        <main className={cn("min-w-0", mainClassName)}>{children}</main>
      </div>
      {mobileSidebar ? <div className="lg:hidden">{mobileSidebar}</div> : null}
      {dock ? <div className="fixed inset-x-3 bottom-3 z-40 lg:hidden">{dock}</div> : null}
    </div>
  );
}
