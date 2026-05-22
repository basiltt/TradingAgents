import { useMemo } from "react";
import {
  ChevronLeft,
  ChevronRight,
  Command,
  Contrast,
  Menu,
  Monitor,
  MoonStar,
  Search,
  SunMedium,
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
        active ? "neu-surface-base neu-surface-inset" : "hover:opacity-80",
      )}
    >
      {Icon ? (
        <span className={cn(
          "inline-flex items-center justify-center rounded-[var(--neu-radius-sm)]",
          touchFriendly ? "size-9 sm:size-8" : "size-8",
          active ? "text-[var(--neu-accent)]" : "opacity-70",
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
  onCollapse,
  darkMode = false,
  onDarkModeToggle,
}: {
  sections: NeuNavSection[];
  activePath?: string;
  onNavigate?: (href?: string) => void;
  collapsed?: boolean;
  mode?: "desktop" | "mobile-sheet";
  footer?: React.ReactNode;
  headerSlot?: React.ReactNode;
  onCollapse?: () => void;
  darkMode?: boolean;
  onDarkModeToggle?: () => void;
}) {
  return (
    <NeuSurface
      depth="raised"
      radius="lg"
      padding="md"
      className={cn("flex h-full min-h-0 flex-col", mode === "mobile-sheet" && "min-h-0")}
    >
      {/* Logo + brand */}
      <div className={cn("flex items-center", collapsed ? "justify-center py-1" : "gap-3 pb-4")}>
        <div className="inline-flex size-10 items-center justify-center rounded-[var(--neu-radius-md)] neu-surface-base neu-surface-inset">
          <Command className="size-4.5" />
        </div>
        {!collapsed ? (
          <p className="text-sm font-bold tracking-[-0.03em]">TradingAgents</p>
        ) : null}
      </div>

      {/* Divider */}
      <div className="mx-1 h-px bg-[var(--neu-border)]" />

      {/* Navigation items */}
      <div className="neu-scrollbar mt-3 flex-1 min-h-0 overflow-auto space-y-3">
        {sections.map((section) => (
          <section key={section.title} className="space-y-1">
            {!collapsed ? (
              <p className="px-2 pb-1 text-[10px] font-semibold uppercase tracking-[0.2em]" style={{ color: "var(--neu-text-muted)" }}>
                {section.title}
              </p>
            ) : null}
            <div className="space-y-0.5">
              {section.items.map((item) => (
                <NeuNavItem
                  key={item.id}
                  icon={item.icon}
                  label={collapsed ? "" : item.label}
                  active={!!item.active}
                  badge={!collapsed ? item.badge : undefined}
                  href={item.href}
                  compact
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

      {/* Divider */}
      <div className="mx-1 mt-3 h-px bg-[var(--neu-border)]" />

      {/* Footer controls */}
      <div className={cn("pt-3 space-y-2", collapsed && "flex flex-col items-center")}>
        {/* Dark mode toggle */}
        {onDarkModeToggle ? (
          <button
            type="button"
            onClick={onDarkModeToggle}
            className={cn(
              "flex items-center gap-2.5 rounded-[var(--neu-radius-md)] px-3 py-2 transition-all",
              "neu-surface-base neu-surface-inset hover:opacity-80",
              collapsed && "size-9 justify-center px-0",
            )}
            title={darkMode ? "Switch to light" : "Switch to dark"}
          >
            {darkMode ? (
              <SunMedium className="size-4" />
            ) : (
              <MoonStar className="size-4" />
            )}
            {!collapsed ? (
              <span className="text-xs font-semibold">{darkMode ? "Light mode" : "Dark mode"}</span>
            ) : null}
          </button>
        ) : null}

        {/* Collapse toggle */}
        {onCollapse && mode === "desktop" ? (
          <button
            type="button"
            onClick={onCollapse}
            className={cn(
              "flex items-center gap-2.5 rounded-[var(--neu-radius-md)] px-3 py-2 transition-all",
              "neu-surface-base neu-surface-inset hover:opacity-80",
              collapsed && "size-9 justify-center px-0",
            )}
            title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          >
            {collapsed ? (
              <ChevronRight className="size-4" />
            ) : (
              <ChevronLeft className="size-4" />
            )}
            {!collapsed ? (
              <span className="text-xs font-semibold">Collapse</span>
            ) : null}
          </button>
        ) : null}
      </div>
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
      <p className="text-base font-semibold tracking-[-0.02em]">Appearance</p>

      <NeuToggleGroup
        label="Surface mode"
        value={theme}
        onChange={(value) => onThemeChange(value as NeuSurfaceMode)}
        options={[
          { value: "ivory", label: "Light", icon: <SunMedium className="size-4" /> },
          { value: "graphite", label: "Dark", icon: <MoonStar className="size-4" /> },
        ]}
      />

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
