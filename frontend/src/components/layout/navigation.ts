import type { LucideIcon } from "lucide-react";
import {
  ActivitySquare,
  ArrowLeftRight,
  ChartColumnBig,
  Clock3,
  Database,
  Home,
  Radar,
  ScanSearch,
  Settings2,
  Sparkles,
  Wallet,
  Waypoints,
} from "lucide-react";

export interface NavItem {
  id: string;
  label: string;
  shortLabel?: string;
  to: string;
  description: string;
  icon: LucideIcon;
  keywords: string[];
  matches: (pathname: string) => boolean;
}

export interface NavSection {
  title: string;
  items: NavItem[];
}

export const navSections: NavSection[] = [
  {
    title: "Overview",
    items: [
      {
        id: "home",
        label: "Home",
        shortLabel: "Home",
        to: "/",
        description: "Command center, quick actions, and current activity.",
        icon: Home,
        keywords: ["dashboard", "overview", "command center"],
        matches: (pathname) => pathname === "/",
      },
    ],
  },
  {
    title: "Research",
    items: [
      {
        id: "analysis-new",
        label: "New Analysis",
        shortLabel: "Analysis",
        to: "/analysis/new",
        description: "Launch a fresh agent workflow with configurable depth and models.",
        icon: Sparkles,
        keywords: ["analysis", "research", "workflow", "new run"],
        matches: (pathname) => pathname.startsWith("/analysis/"),
      },
      {
        id: "history",
        label: "Analysis History",
        shortLabel: "History",
        to: "/history",
        description: "Inspect saved runs, archived reports, and completed reasoning trails.",
        icon: ActivitySquare,
        keywords: ["history", "archive", "reports", "reasoning"],
        matches: (pathname) => pathname.startsWith("/history"),
      },
      {
        id: "scanner",
        label: "New Scan",
        shortLabel: "Scanner",
        to: "/scanner",
        description: "Batch scan crypto markets with automation and filter controls.",
        icon: Radar,
        keywords: ["scanner", "market scan", "signals", "batch"],
        matches: (pathname) => pathname === "/scanner",
      },
      {
        id: "scanner-history",
        label: "Scan History",
        shortLabel: "Scans",
        to: "/scanner/history",
        description: "Review completed scans, result snapshots, and execution summaries.",
        icon: ScanSearch,
        keywords: ["scan history", "snapshots", "results", "summaries"],
        matches: (pathname) =>
          pathname.startsWith("/scanner/history") ||
          (/^\/scanner\/[^/]+$/.test(pathname) &&
            pathname !== "/scanner" &&
            pathname !== "/scanner/schedules"),
      },
      {
        id: "scanner-schedules",
        label: "Scheduled Scans",
        shortLabel: "Schedules",
        to: "/scanner/schedules",
        description: "Automate repeated scan jobs, schedules, and execution windows.",
        icon: Clock3,
        keywords: ["schedules", "cron", "automation", "repeating scans"],
        matches: (pathname) => pathname.startsWith("/scanner/schedules"),
      },
    ],
  },
  {
    title: "Portfolio",
    items: [
      {
        id: "accounts",
        label: "Accounts",
        shortLabel: "Accounts",
        to: "/accounts",
        description: "Manage trading accounts, balances, positions, and controls.",
        icon: Wallet,
        keywords: ["accounts", "wallets", "balances", "connections"],
        matches: (pathname) => pathname.startsWith("/accounts"),
      },
      {
        id: "analytics",
        label: "Performance",
        shortLabel: "Performance",
        to: "/analytics",
        description: "Track equity, drawdown, monthly performance, and portfolio health.",
        icon: ChartColumnBig,
        keywords: ["analytics", "performance", "drawdown", "equity"],
        matches: (pathname) => pathname.startsWith("/analytics"),
      },
      {
        id: "trades",
        label: "Trades",
        shortLabel: "Trades",
        to: "/trades",
        description: "Inspect trade streams, filters, statuses, and close actions.",
        icon: ArrowLeftRight,
        keywords: ["trades", "positions", "execution", "orders"],
        matches: (pathname) => pathname.startsWith("/trades"),
      },
      {
        id: "strategies",
        label: "Strategies",
        shortLabel: "Strategies",
        to: "/strategies",
        description: "Build reusable strategy definitions and execution templates.",
        icon: Waypoints,
        keywords: ["strategies", "templates", "rules", "playbooks"],
        matches: (pathname) => pathname.startsWith("/strategies"),
      },
      {
        id: "cycles",
        label: "Cycles",
        shortLabel: "Cycles",
        to: "/cycles",
        description: "Review cycle automation, progress states, and managed trade batches.",
        icon: ActivitySquare,
        keywords: ["cycles", "automation", "batches", "managed runs"],
        matches: (pathname) => pathname.startsWith("/cycles"),
      },
    ],
  },
  {
    title: "System",
    items: [
      {
        id: "config",
        label: "Config",
        shortLabel: "Config",
        to: "/config",
        description: "View resolved environment state, overrides, and UI appearance controls.",
        icon: Settings2,
        keywords: ["config", "settings", "environment", "appearance"],
        matches: (pathname) => pathname.startsWith("/config"),
      },
      {
        id: "memory",
        label: "Memory",
        shortLabel: "Memory",
        to: "/memory",
        description: "Browse long-term decision logs, confidence records, and reasoning history.",
        icon: Database,
        keywords: ["memory", "records", "reasoning", "confidence"],
        matches: (pathname) => pathname.startsWith("/memory"),
      },
    ],
  },
];

export const navItems = navSections.flatMap((section) => section.items);

export const mobileDockItems = navItems.filter((item) =>
  ["home", "analysis-new", "scanner", "trades"].includes(item.id),
);

export function getActiveNavigation(pathname: string): {
  item: NavItem;
  sectionTitle: string;
} {
  const activeItem = navItems.find((item) => item.matches(pathname)) ?? navItems[0];
  const activeSection = navSections.find((section) =>
    section.items.some((item) => item.id === activeItem.id),
  );

  return {
    item: activeItem,
    sectionTitle: activeSection?.title ?? "Overview",
  };
}
