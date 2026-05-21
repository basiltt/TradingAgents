import { useEffect } from "react";
import { Link, Outlet, useLocation } from "@tanstack/react-router";
import type { LucideIcon } from "lucide-react";
import {
  ActivitySquare,
  ArrowLeftRight,
  ChartColumnBig,
  Clock3,
  Database,
  Home,
  Menu,
  Radar,
  ScanSearch,
  Settings2,
  Sparkles,
  Wallet,
  Waypoints,
  X,
} from "lucide-react";
import { useAccountWebSocket } from "@/hooks/useAccountWebSocket";
import { useThemeEffect } from "@/hooks/useThemeEffect";
import { useAppDispatch, useAppSelector } from "@/store";
import { setSidebarOpen, toggleSidebar } from "@/store/ui-slice";
import { AppearanceControls } from "@/components/layout/AppearanceControls";
import { cn } from "@/lib/utils";

interface NavItem {
  label: string;
  to: string;
  description: string;
  icon: LucideIcon;
  matches: (pathname: string) => boolean;
}

interface NavSection {
  title: string;
  items: NavItem[];
}

const navSections: NavSection[] = [
  {
    title: "Overview",
    items: [
      {
        label: "Home",
        to: "/",
        description: "Command center, quick actions, and current activity.",
        icon: Home,
        matches: (pathname) => pathname === "/",
      },
    ],
  },
  {
    title: "Research",
    items: [
      {
        label: "New Analysis",
        to: "/analysis/new",
        description: "Launch a fresh agent workflow with configurable depth and models.",
        icon: Sparkles,
        matches: (pathname) => pathname.startsWith("/analysis/"),
      },
      {
        label: "Analysis History",
        to: "/history",
        description: "Inspect saved runs, archived reports, and completed reasoning trails.",
        icon: ActivitySquare,
        matches: (pathname) => pathname.startsWith("/history"),
      },
      {
        label: "New Scan",
        to: "/scanner",
        description: "Batch scan crypto markets with automation and filter controls.",
        icon: Radar,
        matches: (pathname) => pathname === "/scanner",
      },
      {
        label: "Scan History",
        to: "/scanner/history",
        description: "Review completed scans, result snapshots, and execution summaries.",
        icon: ScanSearch,
        matches: (pathname) =>
          pathname.startsWith("/scanner/history") ||
          (/^\/scanner\/[^/]+$/.test(pathname) &&
            pathname !== "/scanner" &&
            pathname !== "/scanner/schedules"),
      },
      {
        label: "Scheduled Scans",
        to: "/scanner/schedules",
        description: "Automate repeated scan jobs, schedules, and execution windows.",
        icon: Clock3,
        matches: (pathname) => pathname.startsWith("/scanner/schedules"),
      },
    ],
  },
  {
    title: "Portfolio",
    items: [
      {
        label: "Accounts",
        to: "/accounts",
        description: "Manage trading accounts, balances, positions, and controls.",
        icon: Wallet,
        matches: (pathname) => pathname.startsWith("/accounts"),
      },
      {
        label: "Performance",
        to: "/analytics",
        description: "Track equity, drawdown, monthly performance, and portfolio health.",
        icon: ChartColumnBig,
        matches: (pathname) => pathname.startsWith("/analytics"),
      },
      {
        label: "Trades",
        to: "/trades",
        description: "Inspect trade streams, filters, statuses, and close actions.",
        icon: ArrowLeftRight,
        matches: (pathname) => pathname.startsWith("/trades"),
      },
      {
        label: "Strategies",
        to: "/strategies",
        description: "Build reusable strategy definitions and execution templates.",
        icon: Waypoints,
        matches: (pathname) => pathname.startsWith("/strategies"),
      },
      {
        label: "Cycles",
        to: "/cycles",
        description: "Review cycle automation, progress states, and managed trade batches.",
        icon: ActivitySquare,
        matches: (pathname) => pathname.startsWith("/cycles"),
      },
    ],
  },
  {
    title: "System",
    items: [
      {
        label: "Config",
        to: "/config",
        description: "View resolved environment state, overrides, and UI appearance controls.",
        icon: Settings2,
        matches: (pathname) => pathname.startsWith("/config"),
      },
      {
        label: "Memory",
        to: "/memory",
        description: "Browse long-term decision logs, confidence records, and reasoning history.",
        icon: Database,
        matches: (pathname) => pathname.startsWith("/memory"),
      },
    ],
  },
];

const navItems = navSections.flatMap((section) => section.items);

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
        "group/nav relative flex min-h-[3.15rem] items-center gap-3 rounded-[calc(var(--radius)*1.35)] border px-3.5 py-3",
        active
          ? "border-primary/25 bg-primary/12 text-foreground shadow-[var(--shadow-accent)]"
          : "border-transparent text-muted-foreground hover:border-border/70 hover:bg-sidebar-accent/85 hover:text-foreground",
      )}
    >
      <span
        className={cn(
          "flex size-10 shrink-0 items-center justify-center rounded-2xl transition-all",
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

  useThemeEffect();
  useAccountWebSocket();

  useEffect(() => {
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        dispatch(setSidebarOpen(false));
      }
    };

    document.addEventListener("keydown", handleEscape);
    return () => document.removeEventListener("keydown", handleEscape);
  }, [dispatch]);

  useEffect(() => {
    dispatch(setSidebarOpen(false));
  }, [pathname, dispatch]);

  const currentItem =
    navItems.find((item) => item.matches(pathname)) ??
    navItems[0];
  const currentSection =
    navSections.find((section) =>
      section.items.some((item) => item.matches(pathname)),
    ) ?? navSections[0];

  return (
    <div className="app-shell animate-fade-in-up">
      <div className="relative lg:grid lg:grid-cols-[var(--app-sidebar-width)_minmax(0,1fr)]">
        <aside
          className={cn(
            "fixed inset-y-0 left-0 z-40 w-[min(92vw,var(--app-sidebar-width))] p-3 transition-transform duration-300 lg:sticky lg:top-0 lg:h-svh lg:w-auto lg:translate-x-0",
            sidebarOpen ? "translate-x-0" : "-translate-x-full",
          )}
          aria-label="Primary navigation"
        >
          <div className="glass flex h-[calc(100svh-1.5rem)] flex-col overflow-hidden rounded-[calc(var(--radius)*1.9)] p-3">
            <div className="flex items-center justify-between gap-3 border-b border-sidebar-border/70 px-3 py-3">
              <Link to="/" className="flex min-w-0 items-center gap-3">
                <span className="gradient-primary flex size-12 shrink-0 items-center justify-center rounded-[calc(var(--radius)*1.4)] text-primary-foreground shadow-[var(--shadow-accent)]">
                  <Sparkles className="size-5" />
                </span>
                <span className="min-w-0">
                  <span className="block truncate text-lg font-semibold tracking-tight text-sidebar-foreground">
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

            <div className="custom-scrollbar flex-1 space-y-7 overflow-y-auto px-2 py-4">
              {navSections.map((section) => (
                <section key={section.title} className="space-y-2.5">
                  <p className="section-eyebrow px-2.5">{section.title}</p>
                  <div className="space-y-1.5">
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

            <div className="border-t border-sidebar-border/70 px-2 pt-3">
              <AppearanceControls compact />
            </div>
          </div>
        </aside>

        <div className="min-w-0">
          <header className="sticky top-0 z-30 px-3 pt-3 sm:px-5 lg:px-6">
            <div className="glass rounded-[calc(var(--radius)*1.9)] px-3 sm:px-5">
              <div className="flex min-h-[var(--app-topbar-height)] items-center gap-3">
                <button
                  type="button"
                  className="touch-target inline-flex items-center justify-center rounded-2xl border border-border/60 bg-card/65 text-foreground shadow-[var(--shadow-soft)] lg:hidden"
                  onClick={() => dispatch(toggleSidebar())}
                  aria-label={sidebarOpen ? "Close navigation" : "Open navigation"}
                >
                  <Menu className="size-4.5" />
                </button>

                <div className="min-w-0 flex-1">
                  <p className="section-eyebrow">{currentSection.title}</p>
                  <div className="mt-1 flex items-center gap-3">
                    <h1 className="truncate text-lg font-semibold tracking-tight text-foreground sm:text-xl">
                      {currentItem.label}
                    </h1>
                    <span className="hidden rounded-full border border-border/70 bg-card/60 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground sm:inline-flex">
                      Responsive workspace
                    </span>
                  </div>
                  <p className="mt-1 hidden truncate text-sm text-muted-foreground sm:block">
                    {currentItem.description}
                  </p>
                </div>

                <div className="hidden items-center gap-2 xl:flex">
                  <span className="inline-flex items-center gap-2 rounded-full border border-emerald-500/20 bg-emerald-500/10 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-emerald-500">
                    <span className="size-2 rounded-full bg-emerald-500 animate-status-halo" />
                    Local runtime live
                  </span>
                </div>
              </div>
            </div>
          </header>

          <main className="px-3 pb-10 pt-4 sm:px-5 lg:px-6">
            <div className="mx-auto w-full max-w-[var(--app-max-width)]">
              <Outlet />
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
    </div>
  );
}

export function NotFound() {
  return (
    <div className="flex min-h-[70vh] items-center justify-center py-10">
      <div className="page-hero glass-card max-w-xl overflow-hidden rounded-[calc(var(--radius)*2)] border border-border/60 p-8 text-center">
        <div className="mx-auto flex size-18 items-center justify-center rounded-[calc(var(--radius)*1.6)] bg-primary/12 text-primary shadow-[var(--shadow-accent)]">
          <Radar className="size-8" />
        </div>
        <p className="section-eyebrow mt-6">Navigation Error</p>
        <h2 className="mt-2 text-3xl font-semibold tracking-tight">Page not found</h2>
        <p className="mx-auto mt-3 max-w-md text-sm leading-6 text-muted-foreground">
          This workspace route does not exist anymore or the underlying record was removed.
          Return to the main dashboard to continue from a stable surface.
        </p>
        <div className="mt-6 flex justify-center">
          <Link
            to="/"
            className="touch-target inline-flex items-center justify-center rounded-[calc(var(--radius)*1.2)] border border-primary/20 bg-primary px-5 py-3 text-sm font-semibold text-primary-foreground shadow-[var(--shadow-accent)]"
          >
            Return to dashboard
          </Link>
        </div>
      </div>
    </div>
  );
}
