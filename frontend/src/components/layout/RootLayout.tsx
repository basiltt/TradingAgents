import { useEffect, useMemo } from "react";
import { Link, Outlet, useLocation, useNavigate } from "@tanstack/react-router";
import {
  ChevronLeft,
  ChevronRight,
  Menu,
  Radar,
  Search,
  Sparkles,
} from "lucide-react";
import {
  NeuAppShell,
  NeuButton,
  NeuDrawer,
  NeuSidebar,
  NeuStatusPill,
  NeuSurface,
  NeuTopbar,
  setCommandPaletteOpen,
  setMobileNavOpen,
  setSidebarCollapsed,
} from "@/design-system/neumorphism";
import { useAccountWebSocket } from "@/hooks/useAccountWebSocket";
import { AppCommandPalette } from "@/components/layout/AppCommandPalette";
import { AppMarketBar } from "@/components/layout/AppMarketBar";
import { MobileDock } from "@/components/layout/MobileDock";
import { getActiveNavigation, navSections } from "@/components/layout/navigation";
import { useAppDispatch, useAppSelector } from "@/store";

export function RootLayout() {
  const pathname = useLocation({ select: (location) => location.pathname });
  const navigate = useNavigate();
  const dispatch = useAppDispatch();
  const { mobileNavOpen, commandPaletteOpen, sidebarCollapsed } = useAppSelector((state) => state.neuUi);

  useAccountWebSocket();

  useEffect(() => {
    const handleKeydown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        dispatch(setMobileNavOpen(false));
        dispatch(setCommandPaletteOpen(false));
      }

      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        dispatch(setCommandPaletteOpen(!commandPaletteOpen));
      }
    };

    document.addEventListener("keydown", handleKeydown);
    return () => document.removeEventListener("keydown", handleKeydown);
  }, [commandPaletteOpen, dispatch]);

  useEffect(() => {
    dispatch(setMobileNavOpen(false));
  }, [dispatch, pathname]);

  const { item: currentItem, sectionTitle: currentSection } = getActiveNavigation(pathname);

  const sections = useMemo(
    () =>
      navSections.map((section) => ({
        title: section.title,
        items: section.items.map((item) => ({
          id: item.id,
          label: item.label,
          description: item.description,
          icon: item.icon,
          active: item.matches(pathname),
          onSelect: () => navigate({ to: item.to as never }),
        })),
      })),
    [navigate, pathname],
  );

  const sidebar = (
    <NeuSidebar
      sections={sections}
      collapsed={sidebarCollapsed}
      headerSlot={<NeuStatusPill label="live" tone="success" animated />}
      footer={
        !sidebarCollapsed ? (
          <div className="surface-lift rounded-[calc(var(--radius)*1.25)] p-3.5">
            <div className="flex items-start gap-3">
              <div className="gradient-primary inline-flex size-10 items-center justify-center rounded-[calc(var(--radius)*1.05)] text-primary-foreground shadow-[var(--shadow-accent)]">
                <Sparkles className="size-4.5" />
              </div>
              <div className="space-y-1">
                <p className="text-sm font-semibold tracking-[-0.03em] text-foreground">Operator focus</p>
                <p className="text-xs leading-5 text-muted-foreground">
                  Use the command palette to jump between research, monitoring, and execution surfaces.
                </p>
              </div>
            </div>
          </div>
        ) : null
      }
    />
  );

  const mobileSidebar = (
    <NeuDrawer
      open={mobileNavOpen}
      onOpenChange={(open) => dispatch(setMobileNavOpen(open))}
      title="Workspace navigation"
      description="Move through research, portfolio, and system workflows from the mobile shell."
      side="left"
      size="sm"
      showHandle={false}
    >
      <div className="space-y-4">
        <NeuSidebar
          sections={sections}
          mode="mobile-sheet"
          headerSlot={<NeuStatusPill label="touch ready" tone="accent" />}
        />
      </div>
    </NeuDrawer>
  );

  const topbar = (
    <div className="mx-auto w-full max-w-[min(100%,116rem)]">
      <NeuTopbar
        section={currentSection}
        title={currentItem.label}
        description={currentItem.description}
        statusPill={<NeuStatusPill label="runtime live" tone="success" animated />}
        actions={
          <>
            <NeuButton
              variant="secondary"
              size="sm"
              className="lg:hidden"
              onClick={() => dispatch(setMobileNavOpen(true))}
            >
              <Menu className="size-4" />
              Menu
            </NeuButton>
            <NeuButton
              variant="secondary"
              size="sm"
              className="hidden lg:inline-flex"
              onClick={() => dispatch(setSidebarCollapsed(!sidebarCollapsed))}
            >
              {sidebarCollapsed ? <ChevronRight className="size-4" /> : <ChevronLeft className="size-4" />}
              {sidebarCollapsed ? "Expand nav" : "Collapse nav"}
            </NeuButton>
            <NeuButton
              variant="soft-tonal"
              size="sm"
              onClick={() => dispatch(setCommandPaletteOpen(true))}
            >
              <Search className="size-4" />
              Command menu
            </NeuButton>
          </>
        }
        toolbar={<AppMarketBar />}
      />
    </div>
  );

  return (
    <div className="min-h-screen p-3 sm:p-4 lg:p-5">
      <NeuAppShell
        sidebar={sidebar}
        sidebarWidth={sidebarCollapsed ? "6.5rem" : "19rem"}
        topbar={topbar}
        mobileSidebar={mobileSidebar}
        dock={<MobileDock pathname={pathname} onMore={() => dispatch(setMobileNavOpen(true))} />}
        contentClassName="pb-24 lg:pb-10"
      >
        <div className="mx-auto w-full max-w-[min(100%,116rem)]">
          <Outlet />
        </div>
      </NeuAppShell>

      <AppCommandPalette
        open={commandPaletteOpen}
        onOpenChange={(open) => dispatch(setCommandPaletteOpen(open))}
      />
    </div>
  );
}

export function NotFound() {
  return (
    <div className="flex min-h-[60vh] items-center justify-center py-6">
      <div className="w-full max-w-xl">
        <NeuSurface depth="raised" radius="lg" padding="lg" className="space-y-5 text-center aurora-border">
          <div className="mx-auto inline-flex size-14 items-center justify-center rounded-[var(--neu-radius-md)] neu-surface-base neu-surface-accent shadow-[var(--neu-shadow-accent)]">
            <Radar className="size-6" />
          </div>
          <div className="space-y-2">
            <p className="text-[11px] font-semibold uppercase tracking-[0.22em]" style={{ color: "var(--neu-text-muted)" }}>
              Navigation error
            </p>
            <h2 className="text-2xl font-semibold tracking-[-0.04em]">Page not found</h2>
            <p className="text-sm leading-7" style={{ color: "var(--neu-text-muted)" }}>
              This workspace route no longer exists or its backing record was removed. Return to the dashboard to continue from a stable control surface.
            </p>
          </div>
          <div className="flex justify-center">
            <NeuButton asChild variant="primary">
              <Link to="/">Return to dashboard</Link>
            </NeuButton>
          </div>
        </NeuSurface>
      </div>
    </div>
  );
}
