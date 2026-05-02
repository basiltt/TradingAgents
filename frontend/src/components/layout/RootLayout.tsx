import { useEffect, useCallback } from "react";
import { Outlet, Link } from "@tanstack/react-router";
import { useAppSelector, useAppDispatch } from "@/store";
import { toggleSidebar, setSidebarOpen } from "@/store/ui-slice";
import { useThemeEffect } from "@/hooks/useThemeEffect";

const linkClass = "block px-2 py-1 rounded hover:bg-accent";
const activeLinkClass = "block px-2 py-1 rounded bg-accent font-medium";

function NavLink({
  to,
  children,
}: {
  to: string;
  children: React.ReactNode;
}) {
  const dispatch = useAppDispatch();
  const closeSidebar = useCallback(
    () => dispatch(setSidebarOpen(false)),
    [dispatch],
  );

  return (
    <Link
      to={to}
      className={linkClass}
      activeProps={{
        className: activeLinkClass,
        "aria-current": "page" as const,
      }}
      activeOptions={{ exact: to === "/" }}
      onClick={closeSidebar}
    >
      {children}
    </Link>
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
    <div className="flex h-screen">
      <button
        className="md:hidden fixed top-3 left-3 z-50 p-2 rounded bg-background border"
        onClick={() => dispatch(toggleSidebar())}
        aria-label={sidebarOpen ? "Close navigation" : "Open navigation"}
      >
        ☰
      </button>
      <nav
        aria-label="Main navigation"
        className={`w-56 border-r bg-sidebar p-4 flex flex-col gap-2 shrink-0
          ${sidebarOpen ? "flex" : "hidden"} md:flex
          fixed md:static inset-y-0 left-0 z-40`}
      >
        <h1 className="text-lg font-bold mb-4">TradingAgents</h1>
        <NavLink to="/">Home</NavLink>
        <NavLink to="/analysis/new">New Analysis</NavLink>
        <NavLink to="/history">History</NavLink>
        <NavLink to="/config">Config</NavLink>
        <NavLink to="/memory">Memory</NavLink>
      </nav>
      {sidebarOpen && (
        <div
          className="md:hidden fixed inset-0 bg-black/30 z-30"
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
      <main className="flex-1 overflow-auto p-6 md:ml-0">
        <Outlet />
      </main>
    </div>
  );
}

export function NotFound() {
  return (
    <div className="flex items-center justify-center h-full">
      <div className="text-center">
        <h2 className="text-2xl font-bold">Page Not Found</h2>
        <p className="text-muted-foreground mt-2">
          The page you're looking for doesn't exist.
        </p>
        <Link to="/" className="text-primary underline mt-4 inline-block">
          Go home
        </Link>
      </div>
    </div>
  );
}
