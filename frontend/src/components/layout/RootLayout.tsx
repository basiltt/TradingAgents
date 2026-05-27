import { useEffect, useMemo } from "react";
import { Link, Outlet, useLocation, useNavigate } from "@tanstack/react-router";
import {
  Menu,
  Radar,
  Search,
} from "lucide-react";
import {
  NeuAppShell,
  NeuButton,
  NeuSidebar,
  NeuSurface,
  NeuTopbar,
  setCommandPaletteOpen,
  setMobileNavOpen,
  setNeuMode,
  setSidebarCollapsed,
} from "@/design-system/neumorphism";
import { MobileDragDrawer } from "@/components/layout/MobileDragDrawer";
import { useAccountWebSocket } from "@/hooks/useAccountWebSocket";
import { AppCommandPalette } from "@/components/layout/AppCommandPalette";
import { AppMarketBar } from "@/components/layout/AppMarketBar";
import { MobileDock } from "@/components/layout/MobileDock";
import { getActiveNavigation, navSections } from "@/components/layout/navigation";
import { useAppDispatch, useAppSelector } from "@/store";
import { motion, AnimatePresence } from "framer-motion";

export function RootLayout() {
  const pathname = useLocation({ select: (location) => location.pathname });
  const navigate = useNavigate();
  const dispatch = useAppDispatch();
  const { mobileNavOpen, commandPaletteOpen, sidebarCollapsed, mode: neuMode } = useAppSelector((state) => state.neuUi);

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
      onCollapse={() => dispatch(setSidebarCollapsed(!sidebarCollapsed))}
      darkMode={neuMode === "graphite"}
      onDarkModeToggle={() => dispatch(setNeuMode(neuMode === "graphite" ? "ivory" : "graphite"))}
    />
  );

  const mobileSidebar = (
    <MobileDragDrawer
      open={mobileNavOpen}
      onOpenChange={(open) => dispatch(setMobileNavOpen(open))}
    >
      <div className="h-full">
        <NeuSidebar
          sections={sections}
          mode="mobile-sheet"
          darkMode={neuMode === "graphite"}
          onDarkModeToggle={() => dispatch(setNeuMode(neuMode === "graphite" ? "ivory" : "graphite"))}
        />
      </div>
    </MobileDragDrawer>
  );

  const topbar = (
    <div className="mx-auto w-full max-w-[min(100%,116rem)]">
      <NeuTopbar
        section={currentSection}
        title={currentItem.label}
        description=""
        statusPill={null}
        actions={
          <>
            <NeuButton
              variant="secondary"
              size="sm"
              className="lg:hidden"
              onClick={() => dispatch(setMobileNavOpen(true))}
              aria-label="Open navigation menu"
            >
              <Menu className="size-4" />
            </NeuButton>
            <NeuButton
              variant="secondary"
              size="sm"
              onClick={() => dispatch(setCommandPaletteOpen(true))}
            >
              <Search className="size-4" />
              <span className="hidden sm:inline">Search</span>
            </NeuButton>
          </>
        }
        toolbar={<AppMarketBar />}
      />
    </div>
  );

  return (
    <div className="min-h-screen p-1.5 sm:p-3 lg:p-5">
      <NeuAppShell
        sidebar={sidebar}
        sidebarWidth={sidebarCollapsed ? "6.5rem" : "19rem"}
        topbar={topbar}
        mobileSidebar={mobileSidebar}
        dock={<MobileDock pathname={pathname} onMore={() => dispatch(setMobileNavOpen(true))} />}
        contentClassName="pb-24 lg:pb-10"
      >
        <div className="mx-auto w-full max-w-[min(100%,116rem)]">
          <AnimatePresence mode="wait">
            <motion.div
              key={pathname}
              initial={{ opacity: 0, y: 10, filter: "blur(4px)" }}
              animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
              exit={{ opacity: 0, y: -6, filter: "blur(2px)" }}
              transition={{ type: "spring", stiffness: 300, damping: 28, mass: 0.8 }}
            >
              <Outlet />
            </motion.div>
          </AnimatePresence>
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
