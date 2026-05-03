import { useEffect, useCallback } from "react";
import { Outlet, Link, useMatchRoute } from "@tanstack/react-router";
import { useAppSelector, useAppDispatch } from "@/store";
import { toggleSidebar, setSidebarOpen, setTheme } from "@/store/ui-slice";
import { useThemeEffect } from "@/hooks/useThemeEffect";

function NavLink({
  to,
  icon,
  children,
}: {
  to: string;
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  const dispatch = useAppDispatch();
  const matchRoute = useMatchRoute();
  const isActive = matchRoute({ to, fuzzy: to !== "/" }) || (to === "/" && matchRoute({ to: "/" }));
  const closeSidebar = useCallback(
    () => dispatch(setSidebarOpen(false)),
    [dispatch],
  );

  return (
    <Link
      to={to}
      className={`flex items-center gap-3 px-3 py-2 rounded-lg text-[13px] font-medium transition-all duration-200
        ${isActive
          ? "bg-primary text-primary-foreground shadow-sm shadow-primary/20"
          : "text-sidebar-foreground/60 hover:text-sidebar-foreground hover:bg-sidebar-accent"
        }`}
      activeProps={{
        "aria-current": "page" as const,
      }}
      activeOptions={{ exact: to === "/" }}
      onClick={closeSidebar}
    >
      <span className="w-5 h-5 flex items-center justify-center shrink-0">{icon}</span>
      {children}
    </Link>
  );
}

function ThemeToggle() {
  const theme = useAppSelector((s) => s.ui.theme);
  const dispatch = useAppDispatch();

  const nextTheme = () => {
    const order = ["light", "dark", "system"] as const;
    const idx = order.indexOf(theme);
    dispatch(setTheme(order[(idx + 1) % order.length]));
  };

  return (
    <button
      onClick={nextTheme}
      className="flex items-center gap-2 px-3 py-2 rounded-lg text-sm text-sidebar-foreground/60 hover:text-sidebar-foreground hover:bg-sidebar-accent transition-colors"
      aria-label={`Theme: ${theme}. Click to change.`}
    >
      {theme === "dark" ? (
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
        </svg>
      ) : theme === "light" ? (
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" />
        </svg>
      ) : (
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
        </svg>
      )}
      <span className="capitalize">{theme}</span>
    </button>
  );
}

export function RootLayout() {
  const sidebarOpen = useAppSelector((s) => s.ui.sidebarOpen);
  const dispatch = useAppDispatch();

  useThemeEffect();

  useEffect(() => {
    if (!sidebarOpen) return;
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === "Escape") dispatch(setSidebarOpen(false));
    };
    document.addEventListener("keydown", handleEscape);
    return () => document.removeEventListener("keydown", handleEscape);
  }, [sidebarOpen, dispatch]);

  return (
    <div className="flex h-screen bg-background">
      {/* Mobile hamburger */}
      <button
        className="md:hidden fixed top-4 left-4 z-50 p-2 rounded-lg bg-card border shadow-sm hover:bg-accent transition-colors"
        onClick={() => dispatch(toggleSidebar())}
        aria-label={sidebarOpen ? "Close navigation" : "Open navigation"}
      >
        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          {sidebarOpen ? (
            <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
          ) : (
            <path strokeLinecap="round" strokeLinejoin="round" d="M4 6h16M4 12h16M4 18h16" />
          )}
        </svg>
      </button>

      {/* Sidebar */}
      <nav
        aria-label="Main navigation"
        className={`w-64 border-r border-sidebar-border bg-sidebar flex flex-col shrink-0
          ${sidebarOpen ? "flex" : "hidden"} md:flex
          fixed md:static inset-y-0 left-0 z-40
          transition-transform duration-300`}
      >
        {/* Logo / Brand */}
        <div className="px-5 py-5 border-b border-sidebar-border">
          <Link to="/" className="flex items-center gap-3 group">
            <div className="w-9 h-9 rounded-xl flex items-center justify-center shadow-sm group-hover:shadow-md transition-shadow" style={{background: 'linear-gradient(135deg, oklch(0.45 0.24 285), oklch(0.50 0.18 310)'}}>
              <svg className="w-5 h-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
              </svg>
            </div>
            <div>
              <h1 className="text-base font-bold text-sidebar-foreground leading-tight">TradingAgents</h1>
              <p className="text-[11px] text-sidebar-foreground/50 font-medium">AI-Powered Analysis</p>
            </div>
          </Link>
        </div>

        {/* Nav links */}
        <div className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
          <p className="px-3 mb-2 text-[11px] font-semibold uppercase tracking-wider text-sidebar-foreground/40">
            Dashboard
          </p>
          <NavLink
            to="/"
            icon={
              <svg fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} className="w-full h-full">
                <path strokeLinecap="round" strokeLinejoin="round" d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" />
              </svg>
            }
          >
            Home
          </NavLink>
          <NavLink
            to="/history"
            icon={
              <svg fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} className="w-full h-full">
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            }
          >
            History
          </NavLink>

          <p className="px-3 mt-5 mb-2 text-[11px] font-semibold uppercase tracking-wider text-sidebar-foreground/40">
            Analysis
          </p>
          <NavLink
            to="/analysis/new"
            icon={
              <svg fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} className="w-full h-full">
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
              </svg>
            }
          >
            New Analysis
          </NavLink>
          <NavLink
            to="/scanner"
            icon={
              <svg fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} className="w-full h-full">
                <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
              </svg>
            }
          >
            Market Scanner
          </NavLink>

          <p className="px-3 mt-5 mb-2 text-[11px] font-semibold uppercase tracking-wider text-sidebar-foreground/40">
            Settings
          </p>
          <NavLink
            to="/config"
            icon={
              <svg fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} className="w-full h-full">
                <path strokeLinecap="round" strokeLinejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
              </svg>
            }
          >
            Config
          </NavLink>
          <NavLink
            to="/memory"
            icon={
              <svg fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} className="w-full h-full">
                <path strokeLinecap="round" strokeLinejoin="round" d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4m0 5c0 2.21-3.582 4-8 4s-8-1.79-8-4" />
              </svg>
            }
          >
            Memory
          </NavLink>
        </div>

        {/* Footer */}
        <div className="px-3 py-3 border-t border-sidebar-border space-y-1">
          <ThemeToggle />
        </div>
      </nav>

      {/* Mobile overlay */}
      {sidebarOpen && (
        <div
          className="md:hidden fixed inset-0 bg-black/40 backdrop-blur-sm z-30 transition-opacity"
          role="button"
          tabIndex={0}
          aria-label="Close navigation"
          onClick={() => dispatch(setSidebarOpen(false))}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ")
              dispatch(setSidebarOpen(false));
          }}
        />
      )}

      {/* Main content */}
      <main className="flex-1 overflow-auto">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <Outlet />
        </div>
      </main>
    </div>
  );
}

export function NotFound() {
  return (
    <div className="flex items-center justify-center h-[60vh]">
      <div className="text-center space-y-4">
        <div className="w-16 h-16 mx-auto rounded-2xl bg-muted flex items-center justify-center">
          <svg className="w-8 h-8 text-muted-foreground" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M9.172 16.172a4 4 0 015.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
        </div>
        <h2 className="text-2xl font-bold">Page Not Found</h2>
        <p className="text-muted-foreground">
          The page you're looking for doesn't exist.
        </p>
        <Link
          to="/"
          className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-primary text-primary-foreground font-medium text-sm hover:opacity-90 transition-opacity"
        >
          Go home
        </Link>
      </div>
    </div>
  );
}
