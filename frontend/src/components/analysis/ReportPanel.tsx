import { memo, useState, useMemo, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { TradingCard } from "./TradingCard";
import { parseTradeCard } from "./parseTradeCard";
import { MobileCollapse } from "./MobileCollapse";

interface ReportPanelProps {
  reports: Record<string, string>;
  isLoading?: boolean;
}

/* ── Section metadata ───────────────────────────────────────────────── */

const SECTION_META: Record<
  string,
  { label: string; group: string; icon: string; accent: string; bg: string }
> = {
  analyst_market:       { label: "Market Analysis",    group: "Analysis",  icon: "M13 7h8m0 0v8m0-8l-8 8-4-4-6 6",   accent: "text-sky-400",     bg: "bg-sky-500/10" },
  analyst_social:       { label: "Social Sentiment",   group: "Analysis",  icon: "M17 8h2a2 2 0 012 2v6a2 2 0 01-2 2h-2v4l-4-4H9a2 2 0 01-2-2V6a2 2 0 012-2h6a2 2 0 012 2v2", accent: "text-pink-400", bg: "bg-pink-500/10" },
  analyst_news:         { label: "News Analysis",      group: "Analysis",  icon: "M19 20H5a2 2 0 01-2-2V6a2 2 0 012-2h10a2 2 0 012 2v1m2 13a2 2 0 01-2-2V7m2 13a2 2 0 002-2V9a2 2 0 00-2-2h-2", accent: "text-amber-400", bg: "bg-amber-500/10" },
  analyst_fundamentals: { label: "Fundamentals",       group: "Analysis",  icon: "M9 7h6m0 10v-3m-3 3h.01M9 17v-3m3 3h.01M12 14v-3", accent: "text-teal-400", bg: "bg-teal-500/10" },
  analyst_crypto_fundamentals: { label: "Crypto Fundamentals", group: "Analysis", icon: "M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4", accent: "text-cyan-400", bg: "bg-cyan-500/10" },
  research_bull:        { label: "Bull Case",          group: "Research",  icon: "M13 7h8m0 0v8m0-8l-8 8-4-4-6 6",   accent: "text-emerald-400", bg: "bg-emerald-500/10" },
  research_bear:        { label: "Bear Case",          group: "Research",  icon: "M13 17h8m0 0V9m0 8l-8-8-4 4-6-6",  accent: "text-red-400",     bg: "bg-red-500/10" },
  research_manager:     { label: "Research Summary",   group: "Research",  icon: "M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2", accent: "text-indigo-400", bg: "bg-indigo-500/10" },
  trader:               { label: "Trader",             group: "Trading",   icon: "M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1", accent: "text-violet-400", bg: "bg-violet-500/10" },
  risk_aggressive:      { label: "Aggressive Risk",    group: "Risk",      icon: "M13 10V3L4 14h7v7l9-11h-7z",        accent: "text-orange-400",  bg: "bg-orange-500/10" },
  risk_conservative:    { label: "Conservative Risk",  group: "Risk",      icon: "M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z", accent: "text-blue-400", bg: "bg-blue-500/10" },
  risk_neutral:         { label: "Neutral Risk",       group: "Risk",      icon: "M3 6l3 1m0 0l-3 9a5.002 5.002 0 006.001 0M6 7l3 9M6 7l6-2m6 2l3-1m-3 1l-3 9a5.002 5.002 0 006.001 0M18 7l3 9m-3-9l-6-2m0-2v2m0 16V5m0 16H9m3 0h3", accent: "text-slate-400", bg: "bg-slate-500/10" },
  portfolio_manager:    { label: "Portfolio Manager",  group: "Decision",  icon: "M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4", accent: "text-amber-400", bg: "bg-amber-500/10" },
  final_trade_decision: { label: "Final Trade Decision", group: "Decision", icon: "M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z", accent: "text-yellow-400", bg: "bg-yellow-500/10" },
};

const GROUP_ORDER = ["Trading", "Decision", "Risk", "Analysis", "Research"];

/* ── Custom markdown components for better table/content rendering ─── */

const markdownComponents = {
  table: ({ children }: { children?: ReactNode }) => (
    <div className="my-6 overflow-x-auto rounded-lg border border-border/40">
      <table className="w-full text-sm">{children}</table>
    </div>
  ),
  thead: ({ children }: { children?: ReactNode }) => (
    <thead className="bg-muted/40 border-b border-border/40">{children}</thead>
  ),
  th: ({ children }: { children?: ReactNode }) => (
    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-foreground/70">
      {children}
    </th>
  ),
  td: ({ children }: { children?: ReactNode }) => (
    <td className="px-4 py-3 text-foreground/75 border-t border-border/20">
      {children}
    </td>
  ),
  hr: () => <hr className="my-8 border-border/25" />,
  h1: ({ children }: { children?: ReactNode }) => (
    <h1 className="text-lg font-bold text-foreground mt-8 mb-4 pb-2.5 border-b border-border/30">
      {children}
    </h1>
  ),
  h2: ({ children }: { children?: ReactNode }) => (
    <h2 className="text-base font-semibold text-foreground mt-8 mb-3">
      {children}
    </h2>
  ),
  h3: ({ children }: { children?: ReactNode }) => (
    <h3 className="text-sm font-semibold text-foreground/85 mt-6 mb-2.5 uppercase tracking-wider">
      {children}
    </h3>
  ),
  p: ({ children }: { children?: ReactNode }) => (
    <p className="my-4 leading-[2] text-foreground/75">{children}</p>
  ),
  ul: ({ children }: { children?: ReactNode }) => (
    <ul className="my-4 ml-1 space-y-2 list-disc list-outside pl-5 text-foreground/75 leading-[1.9]">
      {children}
    </ul>
  ),
  ol: ({ children }: { children?: ReactNode }) => (
    <ol className="my-5 ml-1 space-y-2.5 list-decimal list-outside pl-5 text-foreground/75 leading-[1.9]">
      {children}
    </ol>
  ),
  li: ({ children }: { children?: ReactNode }) => (
    <li className="pl-1.5">{children}</li>
  ),
  blockquote: ({ children }: { children?: ReactNode }) => (
    <blockquote className="my-5 border-l-2 border-primary/25 pl-5 text-foreground/55 italic">
      {children}
    </blockquote>
  ),
  strong: ({ children }: { children?: ReactNode }) => (
    <strong className="font-semibold text-foreground/95">{children}</strong>
  ),
  em: ({ children }: { children?: ReactNode }) => (
    <em className="text-foreground/60">{children}</em>
  ),
  code: ({ children, className }: { children?: ReactNode; className?: string }) => {
    if (className) {
      return (
        <code className={cn("block my-4 p-4 rounded-lg bg-muted/50 text-xs font-mono text-foreground/70 overflow-x-auto", className)}>
          {children}
        </code>
      );
    }
    return (
      <code className="px-1.5 py-0.5 rounded bg-muted/60 text-xs font-mono text-primary/80">
        {children}
      </code>
    );
  },
};

/* ── JSON detection & formatting ───────────────────────────────────── */

function formatJsonInContent(text: string): string {
  const trimmed = text.trim();
  const start = trimmed.indexOf("{");
  const end = trimmed.lastIndexOf("}");
  if (start === -1 || end === -1) return text;
  try {
    const obj = JSON.parse(trimmed.slice(start, end + 1));
    const before = trimmed.slice(0, start).trim();
    const after = trimmed.slice(end + 1).trim();
    const formatted = JSON.stringify(obj, null, 2);
    const parts: string[] = [];
    if (before) parts.push(before);
    parts.push("```json\n" + formatted + "\n```");
    if (after) parts.push(after);
    return parts.join("\n\n");
  } catch {
    return text;
  }
}

/* ── Markdown renderer ──────────────────────────────────────────────── */

function MarkdownContent({ content }: { content: string }) {
  const processed = content.trim().includes("{") ? formatJsonInContent(content) : content;
  return (
    <div className="max-w-none text-[13.5px]">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={markdownComponents}
      >
        {processed}
      </ReactMarkdown>
    </div>
  );
}

/* ── Tab button ─────────────────────────────────────────────────────── */

function TabButton({
  section,
  active,
  onClick,
}: {
  section: string;
  active: boolean;
  onClick: () => void;
}) {
  const meta = SECTION_META[section] ?? {
    label: section, group: "Other", icon: "", accent: "text-primary", bg: "bg-primary/10",
  };
  const isDecision = section === "final_trade_decision";

  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "w-full flex items-center gap-2.5 px-3 py-2.5 rounded-lg text-left transition-all text-xs font-bold uppercase tracking-wider cursor-pointer border-l-2",
        active
          ? cn("bg-primary/10 border-primary text-foreground shadow-sm")
          : "border-transparent text-muted-foreground hover:text-foreground/80 hover:bg-muted/10",
      )}
    >
      <div className={cn(
        "w-6 h-6 rounded-md flex items-center justify-center flex-shrink-0 transition-colors",
        active ? meta.bg : "bg-transparent",
      )}>
        {meta.icon && (
          <svg
            className={cn("w-3.5 h-3.5", active ? meta.accent : "text-muted-foreground/50")}
            fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}
          >
            <path strokeLinecap="round" strokeLinejoin="round" d={meta.icon} />
          </svg>
        )}
      </div>
      <span className="truncate">{meta.label}</span>
      {isDecision && (
        <span className="ml-auto w-1.5 h-1.5 rounded-full bg-yellow-400 flex-shrink-0 animate-pulse" />
      )}
    </button>
  );
}

/* ── Group label in sidebar ─────────────────────────────────────────── */

function SidebarGroupLabel({ name }: { name: string }) {
  return (
    <div className="px-3 pt-4 pb-1.5 first:pt-0">
      <span className="text-[10px] font-semibold uppercase tracking-[0.18em] text-muted-foreground/40">
        {name}
      </span>
    </div>
  );
}

/* ── Main panel ─────────────────────────────────────────────────────── */

export const ReportPanel = memo(function ReportPanel({ reports, isLoading }: ReportPanelProps) {
  // Parse data_warnings (JSON array of error strings) before filtering
  const dataWarnings = useMemo(() => {
    const raw = reports.data_warnings;
    if (!raw) return [];
    try { return JSON.parse(raw) as string[]; } catch { return []; }
  }, [reports]);

  const entries = Object.entries(reports).filter(
    ([k]) => !k.startsWith("_") && k !== "data_warnings",
  );
  const [activeTab, setActiveTab] = useState<string | null>(null);
  const tradeCardData = useMemo(() => parseTradeCard(reports), [reports]);

  // Auto-select trader tab, then final_trade_decision, then first available
  const effectiveTab = activeTab && reports[activeTab]
    ? activeTab
    : reports.trader
      ? "trader"
      : reports.final_trade_decision
        ? "final_trade_decision"
      : entries[0]?.[0] ?? null;

  if (isLoading) {
    return (
      <div className="space-y-4">
        <div className="flex items-center gap-3">
          <Skeleton className="w-8 h-8 rounded-xl" />
          <Skeleton className="h-6 w-40 rounded-lg" />
        </div>
        {/* Mobile: stacked section skeletons */}
        <div className="md:hidden space-y-2">
          {[1, 2, 3].map((i) => (
            <div key={i} className="rounded-xl border border-border overflow-hidden">
              <Skeleton className="h-12 w-full rounded-none" />
            </div>
          ))}
        </div>
        {/* Desktop: sidebar + content skeleton */}
        <div className="hidden md:flex rounded-xl border border-border/40 overflow-hidden min-h-[500px]">
          <div className="w-52 shrink-0 border-r border-border/30 p-3 space-y-2">
            {[1, 2, 3, 4, 5].map((i) => (
              <Skeleton key={i} className="h-9 rounded-lg" />
            ))}
          </div>
          <div className="flex-1 p-6 space-y-4">
            <Skeleton className="h-7 w-48 rounded-lg" />
            <Skeleton className="h-4 w-full rounded" />
            <Skeleton className="h-4 w-5/6 rounded" />
            <Skeleton className="h-4 w-4/6 rounded" />
            <Skeleton className="h-4 w-full rounded" />
            <Skeleton className="h-4 w-3/4 rounded" />
          </div>
        </div>
      </div>
    );
  }

  if (entries.length === 0) {
    return (
      <Card className="border-dashed border-border/30">
        <CardContent className="py-14">
          <div className="flex flex-col items-center text-center">
            <div className="w-12 h-12 rounded-2xl bg-muted/30 flex items-center justify-center mb-3">
              <svg className="w-6 h-6 text-muted-foreground/30" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
            </div>
            <p className="text-sm text-muted-foreground/50">Report sections appear as agents complete their analysis</p>
          </div>
        </CardContent>
      </Card>
    );
  }

  // Group entries for sidebar
  const grouped = new Map<string, Array<[string, string]>>();
  for (const [section, content] of entries) {
    const group = SECTION_META[section]?.group ?? "Other";
    if (!grouped.has(group)) grouped.set(group, []);
    grouped.get(group)!.push([section, content]);
  }

  const sortedGroups = [...grouped.entries()].sort(([a], [b]) => {
    const ai = GROUP_ORDER.indexOf(a);
    const bi = GROUP_ORDER.indexOf(b);
    return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi);
  });

  const activeContent = effectiveTab ? reports[effectiveTab] : null;
  const activeMeta = effectiveTab
    ? SECTION_META[effectiveTab] ?? { label: effectiveTab, accent: "text-primary", bg: "bg-primary/10", icon: "" }
    : null;

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center gap-3 pb-2">
        <div className="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center shadow-inner">
          <svg className="w-5 h-5 text-primary" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
          </svg>
        </div>
        <div>
          <h2 className="text-sm font-bold uppercase tracking-wider text-foreground">Analysis Reports Workspace</h2>
          <p className="text-[10px] text-muted-foreground font-semibold uppercase tracking-wider mt-0.5">
            {entries.length} Compiled agent phase{entries.length !== 1 ? "s" : ""}
          </p>
        </div>
      </div>

      {/* Data quality warnings banner */}
      {dataWarnings.length > 0 && (
        <div className="rounded-2xl border border-amber-500/25 bg-amber-500/5 px-5 py-4 shadow-sm animate-pulse-slow">
          <div className="flex items-start gap-3">
            <div className="w-9 h-9 rounded-xl bg-amber-500/10 flex items-center justify-center shrink-0 border border-amber-500/20">
              <svg className="w-5 h-5 text-amber-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4.5c-.77-.833-2.694-.833-3.464 0L3.34 16.5c-.77.833.192 2.5 1.732 2.5z" />
              </svg>
            </div>
            <div>
              <p className="text-xs font-bold text-amber-500 uppercase tracking-wider">Market Feeds Quality Alert</p>
              <p className="text-[11px] text-amber-500/75 mt-1 leading-relaxed">
                Some third-party market data feeds failed to fetch in parallel. Fallbacks were automatically queried, but review specific sections for coverage.
              </p>
              <ul className="mt-2.5 space-y-1 pl-1">
                {dataWarnings.map((w, i) => (
                  <li key={i} className="text-[10px] font-mono text-amber-500/70 flex items-center gap-1.5">
                    <span className="w-1 h-1 rounded-full bg-amber-500" />
                    {w.replace(/\[ERROR\]\s*/g, "")}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      )}

      {/* Mobile: collapsible report sections */}
      <div className="md:hidden space-y-2">
        {sortedGroups.flatMap(([, groupEntries]) =>
          groupEntries.map(([section, content]) => {
            const meta = SECTION_META[section] ?? { label: section, accent: "text-primary", bg: "bg-primary/10", icon: "", group: "Other" };
            const isDecision = section === "final_trade_decision";
            const isTrader = section === "trader";
            return (
              <MobileCollapse
                key={section}
                defaultOpen={isDecision || isTrader}
                storageKey={`collapse:report:${section}`}
                title={
                  <span className={cn("text-xs font-bold uppercase tracking-wider flex items-center gap-2", isDecision ? "text-yellow-400" : "text-foreground")}>
                    <div className={cn("w-6 h-6 rounded-md flex items-center justify-center shrink-0 border border-current/10", meta.bg)}>
                      {meta.icon && (
                        <svg className={cn("w-3.5 h-3.5", meta.accent)} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                          <path strokeLinecap="round" strokeLinejoin="round" d={meta.icon} />
                        </svg>
                      )}
                    </div>
                    {meta.label}
                    {isDecision && <span className="w-1.5 h-1.5 rounded-full bg-yellow-400 shrink-0" />}
                  </span>
                }
              >
                <div className="px-4 py-4">
                  {isTrader && tradeCardData && (
                    <div className="mb-5">
                      <TradingCard data={tradeCardData} />
                    </div>
                  )}
                  <MarkdownContent content={content} />
                </div>
              </MobileCollapse>
            );
          })
        )}
      </div>

      {/* Desktop: sidebar + content layout */}
      <div className="hidden md:flex rounded-2xl border border-border/50 bg-card/65 glass shadow-sm overflow-hidden h-[600px]">
        {/* Sidebar tabs */}
        <div className="w-56 flex-shrink-0 border-r border-border/30 bg-muted/5 py-3 overflow-y-auto">
          {sortedGroups.map(([group, groupEntries]) => (
            <div key={group}>
              <SidebarGroupLabel name={group} />
              {groupEntries.map(([section]) => (
                <div key={section} className="px-2 py-0.5">
                  <TabButton
                    section={section}
                    active={effectiveTab === section}
                    onClick={() => setActiveTab(section)}
                  />
                </div>
              ))}
            </div>
          ))}
        </div>

        {/* Content area */}
        <div className="flex-1 overflow-y-auto flex flex-col">
          {activeContent && activeMeta ? (
            <div className="flex-1 flex flex-col min-h-0">
              <div className="sticky top-0 z-10 bg-card/85 backdrop-blur-md border-b border-border/35 px-8 py-4 flex items-center gap-3 shrink-0">
                <div className={cn("w-8 h-8 rounded-lg flex items-center justify-center border border-current/15 shadow-sm", activeMeta.bg)}>
                  {activeMeta.icon && (
                    <svg className={cn("w-4.5 h-4.5", activeMeta.accent)} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                      <path strokeLinecap="round" strokeLinejoin="round" d={activeMeta.icon} />
                    </svg>
                  )}
                </div>
                <h3 className={cn(
                  "text-sm font-bold uppercase tracking-wider",
                  effectiveTab === "final_trade_decision" ? "text-yellow-400" : "text-foreground/90",
                )}>
                  {activeMeta.label}
                </h3>
              </div>
              
              <div className="flex-1 overflow-y-auto">
                {effectiveTab === "trader" && tradeCardData && (
                  <div className="px-8 pt-6 sm:px-10 sm:pt-8">
                    <TradingCard data={tradeCardData} />
                  </div>
                )}
                <div className="px-8 py-6 sm:px-10 sm:py-8">
                  <MarkdownContent content={activeContent} />
                </div>
              </div>
            </div>
          ) : (
            <div className="flex-1 flex flex-col items-center justify-center text-muted-foreground/50 text-xs font-bold uppercase tracking-wider">
              Select a section to view reports
            </div>
          )}
        </div>
      </div>
    </div>
  );
});
