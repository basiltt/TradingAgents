import { useEffect, useState } from "react";
import { Link, Outlet, useLocation } from "@tanstack/react-router";
import {
  Menu,
  Radar,
  Search,
  Sparkles,
  X,
} from "lucide-react";
import { useAccountWebSocket } from "@/hooks/useAccountWebSocket";
import { useThemeEffect } from "@/hooks/useThemeEffect";
import { useAppDispatch, useAppSelector } from "@/store";
import { setSidebarOpen, toggleSidebar } from "@/store/ui-slice";
import { AppCommandPalette } from "@/components/layout/AppCommandPalette";
import { AppMarketBar } from "@/components/layout/AppMarketBar";
import { AppearanceControls } from "@/components/layout/AppearanceControls";
import { MobileDock } from "@/components/layout/MobileDock";
import { getActiveNavigation, navSections, type NavItem } from "@/components/layout/navigation";
import { cn } from "@/lib/utils";

function SidebarLink({
  item,
  active,
  onNavigate,
}: {
  item: NavItem;
  active: boolean;
  onNavigate: () => void;
}) {
  const Icon = item.icon;

  return (
    <Link
      to={item.to}
      onClick={onNavigate}
      className={cn(
        "group/nav relative flex min-h-[2.8rem] items-center gap-2.5 rounded-[calc(var(--radius)*1.25)] border px-3 py-2.5",
        active
          ? "border-primary/25 bg-primary/12 text-foreground shadow-[var(--shadow-accent)]"
          : "border-transparent text-muted-foreground hover:border-border/70 hover:bg-sidebar-accent/85 hover:text-foreground",
      )}
    >
      <span
        className={cn(
          "flex size-9 shrink-0 items-center justify-center rounded-[calc(var(--radius)*1.15)] transition-all",
          active
            ? "gradient-primary text-primary-foreground shadow-[var(--shadow-accent)]"
            : "bg-card/80 text-muted-foreground group-hover/nav:text-foreground",
        )}
      >
        <Icon className="size-4.5" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-semibold tracking-tight">
          {item.label}
        </span>
        <span className="mt-0.5 block truncate text-xs text-muted-foreground">
          {item.description}
        </span>
      </span>
      {active && (
        <span className="h-8 w-1 rounded-full bg-primary shadow-[var(--shadow-accent)]" />
      )}
    </Link>
  );
}

export function RootLayout() {
  const pathname = useLocation({ select: (location) => location.pathname });
  const sidebarOpen = useAppSelector((s) => s.ui.sidebarOpen);
  const dispatch = useAppDispatch();
  const [commandOpen, setCommandOpen] = useState(false);
  const shortcutLabel =
    typeof navigator !== "undefined" && /mac/i.test(navigator.platform)
      ? "Cmd K"
      : "Ctrl K";

  useThemeEffect();
  useAccountWebSocket();

  useEffect(() => {
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        dispatch(setSidebarOpen(false));
        setCommandOpen(false);
      }

      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setCommandOpen((current) => !current);
      }
    };

    document.addEventListener("keydown", handleEscape);
    return () => document.removeEventListener("keydown", handleEscape);
  }, [dispatch]);

  useEffect(() => {
    dispatch(setSidebarOpen(false));
  }, [pathname, dispatch]);

  const { item: currentItem, sectionTitle: currentSection } = getActiveNavigation(pathname);

  return (
    <div className="app-shell animate-fade-in-up">
      <div className="relative lg:grid lg:grid-cols-[var(--app-sidebar-width)_minmax(0,1fr)]">
        <aside
          className={cn(
            "fixed inset-y-0 left-0 z-40 w-[min(92vw,var(--app-sidebar-width))] p-2.5 transition-transform duration-300 lg:sticky lg:top-0 lg:h-svh lg:w-auto lg:translate-x-0",
            sidebarOpen ? "translate-x-0" : "-translate-x-full",
          )}
          aria-label="Primary navigation"
        >
          <div className="glass flex h-[calc(100svh-1.25rem)] flex-col overflow-hidden rounded-[calc(var(--radius)*1.75)] p-2.5">
            <div className="flex items-center justify-between gap-3 border-b border-sidebar-border/70 px-3 py-2.5">
              <Link to="/" className="flex min-w-0 items-center gap-3">
                <span className="gradient-primary flex size-10 shrink-0 items-center justify-center rounded-[calc(var(--radius)*1.25)] text-primary-foreground shadow-[var(--shadow-accent)]">
                  <Sparkles className="size-4.5" />
                </span>
                <span className="min-w-0">
                  <span className="block truncate text-base font-semibold tracking-tight text-sidebar-foreground">
                    TradingAgents
                  </span>
                  <span className="section-eyebrow block text-sidebar-foreground/70">
                    Adaptive Trading Workspace
                  </span>
                </span>
              </Link>
              <button
                type="button"
                className="touch-target inline-flex items-center justify-center rounded-2xl border border-border/60 bg-card/65 text-muted-foreground lg:hidden"
                onClick={() => dispatch(setSidebarOpen(false))}
                aria-label="Close navigation"
              >
                <X className="size-4.5" />
              </button>
            </div>

            <div className="px-2 pt-2.5">
              <button
                type="button"
                onClick={() => setCommandOpen(true)}
                className="flex w-full items-center gap-2.5 rounded-[calc(var(--radius)*1.25)] border border-sidebar-border/80 bg-card/68 px-3 py-2.5 text-left shadow-[var(--shadow-soft)] hover:border-primary/20 hover:bg-card/82"
              >
                <span className="flex size-9 shrink-0 items-center justify-center rounded-[calc(var(--radius)*1.15)] border border-primary/18 bg-primary/10 text-primary">
                  <Search className="size-4.5" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[0.84rem] font-semibold tracking-tight text-sidebar-foreground">
                    Command Menu
                  </span>
                  <span className="mt-0.5 block truncate text-[0.72rem] text-muted-foreground">
                    Search routes, themes, and quick actions.
                  </span>
                </span>
                <span className="command-kbd hidden xl:inline-flex">{shortcutLabel}</span>
              </button>
            </div>

            <div className="custom-scrollbar flex-1 space-y-6 overflow-y-auto px-2 py-3.5">
              {navSections.map((section) => (
                <section key={section.title} className="space-y-2">
                  <p className="section-eyebrow px-2.5">{section.title}</p>
                  <div className="space-y-1.25">
                    {section.items.map((item) => (
                      <SidebarLink
                        key={item.to}
                        item={item}
                        active={item.matches(pathname)}
                        onNavigate={() => dispatch(setSidebarOpen(false))}
                      />
                    ))}
                  </div>
                </section>
              ))}
            </div>

            <div className="border-t border-sidebar-border/70 px-2 pt-2.5">
              <AppearanceControls compact />
            </div>
          </div>
        </aside>

        <div className="min-w-0">
          <header className="sticky top-0 z-30 px-3 pt-2.5 sm:px-4 lg:px-5">
            <div className="glass overflow-hidden rounded-[calc(var(--radius)*1.75)] px-3 py-2.5 sm:px-4">
              <div className="flex min-h-[var(--app-topbar-height)] flex-col gap-3">
                <div className="flex items-center gap-3">
                <button
                  type="button"
                  className="touch-target inline-flex items-center justify-center rounded-2xl border border-border/60 bg-card/65 text-foreground shadow-[var(--shadow-soft)] lg:hidden"
                  onClick={() => dispatch(toggleSidebar())}
                  aria-label={sidebarOpen ? "Close navigation" : "Open navigation"}
                >
                  <Menu className="size-4.5" />
                </button>

                <div className="min-w-0 flex-1">
                  <p className="section-eyebrow">{currentSection}</p>
                  <div className="mt-1 flex items-center gap-2.5">
                    <h1 className="truncate text-base font-semibold tracking-tight text-foreground sm:text-lg">
                      {currentItem.label}
                    </h1>
                    <span className="hidden rounded-full border border-border/70 bg-card/60 px-2.5 py-0.75 text-[10px] font-semibold uppercase tracking-[0.18em] text-muted-foreground sm:inline-flex">
                      Responsive workspace
                    </span>
                  </div>
                  <p className="mt-1 hidden truncate text-[0.82rem] text-muted-foreground sm:block">
                    {currentItem.description}
                  </p>
                </div>

                <button
                  type="button"
                  onClick={() => setCommandOpen(true)}
                  className="hidden items-center gap-2.5 rounded-full border border-border/70 bg-card/72 px-3.5 py-1.75 text-left shadow-[var(--shadow-soft)] md:inline-flex"
                >
                  <Search className="size-4 text-muted-foreground" />
                  <span className="text-[0.82rem] text-muted-foreground">Search routes or commands</span>
                  <span className="command-kbd">{shortcutLabel}</span>
                </button>

                <div className="hidden items-center gap-2 xl:flex">
                  <span className="inline-flex items-center gap-2 rounded-full border border-emerald-500/20 bg-emerald-500/10 px-2.5 py-0.75 text-[10px] font-semibold uppercase tracking-[0.18em] text-emerald-500">
                    <span className="size-2 rounded-full bg-emerald-500 animate-status-halo" />
                    Local runtime live
                  </span>
                </div>
                </div>

                <AppMarketBar />
              </div>
            </div>
          </header>

          <main className="px-3 pb-26 pt-3.5 sm:px-4 lg:px-5 lg:pb-9">
            <div className="mx-auto w-full max-w-[var(--app-max-width)]">
              <div className="route-stage">
                <Outlet />
              </div>
            </div>
          </main>
        </div>
      </div>

      <div
        className={cn(
          "fixed inset-0 z-30 bg-[oklch(0.16_0.012_var(--surface-hue)_/_0.52)] backdrop-blur-sm transition-opacity duration-300 lg:hidden",
          sidebarOpen ? "pointer-events-auto opacity-100" : "pointer-events-none opacity-0",
        )}
        onClick={() => dispatch(setSidebarOpen(false))}
        aria-hidden="true"
      />

      <MobileDock pathname={pathname} onMore={() => dispatch(setSidebarOpen(true))} />
      <AppCommandPalette open={commandOpen} onOpenChange={setCommandOpen} />
    </div>
  );
}

export function NotFound() {
  return (
    <div className="flex min-h-[60vh] items-center justify-center py-6">
      <div className="page-hero glass-card max-w-xl overflow-hidden rounded-[calc(var(--radius)*1.8)] border border-border/60 p-5 text-center">
        <div className="mx-auto flex size-12 items-center justify-center rounded-[calc(var(--radius)*1.3)] bg-primary/12 text-primary shadow-[var(--shadow-accent)]">
          <Radar className="size-5.5" />
        </div>
        <p className="section-eyebrow mt-5">Navigation Error</p>
        <h2 className="mt-2 text-xl font-semibold tracking-tight">Page not found</h2>
        <p className="mx-auto mt-2.5 max-w-md text-[0.9rem] leading-6 text-muted-foreground">
          This workspace route does not exist anymore or the underlying record was removed.
          Return to the main dashboard to continue from a stable surface.
        </p>
        <div className="mt-5 flex justify-center">
          <Link
            to="/"
            className="touch-target inline-flex items-center justify-center rounded-[calc(var(--radius)*1.15)] border border-primary/20 bg-primary px-4 py-2.5 text-sm font-semibold text-primary-foreground shadow-[var(--shadow-accent)]"
          >
            Return to dashboard
          </Link>
        </div>
      </div>
    </div>
  );
}
