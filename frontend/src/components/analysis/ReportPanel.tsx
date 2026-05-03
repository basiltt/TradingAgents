import { memo, useState, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

interface ReportPanelProps {
  reports: Record<string, string>;
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

const GROUP_ORDER = ["Analysis", "Research", "Trading", "Risk", "Decision"];

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

/* ── Markdown renderer ──────────────────────────────────────────────── */

function MarkdownContent({ content }: { content: string }) {
  return (
    <div className="max-w-none text-[13.5px]">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={markdownComponents}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

/* ── Section card (expandable) ──────────────────────────────────────── */

function SectionCard({
  section,
  content,
  defaultOpen = false,
}: {
  section: string;
  content: string;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const meta = SECTION_META[section] ?? {
    label: section, group: "Other", icon: "", accent: "text-primary", bg: "bg-primary/10",
  };

  const isDecision = section === "final_trade_decision";

  return (
    <div
      className={cn(
        "rounded-xl border overflow-hidden transition-all",
        isDecision
          ? "border-yellow-500/30 bg-yellow-500/[0.02]"
          : "border-border/40 bg-card/30",
      )}
    >
      {/* Header button */}
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "w-full flex items-center gap-3.5 px-5 py-4 text-left transition-colors",
          open ? "bg-muted/15" : "hover:bg-muted/10",
        )}
      >
        <div className={cn("w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0", meta.bg)}>
          {meta.icon && (
            <svg className={cn("w-4 h-4", meta.accent)} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d={meta.icon} />
            </svg>
          )}
        </div>

        <span className={cn(
          "text-sm font-semibold flex-1",
          isDecision ? "text-yellow-400" : "text-foreground/90",
        )}>
          {meta.label}
        </span>

        <svg
          className={cn(
            "w-4 h-4 text-muted-foreground/40 transition-transform duration-200 flex-shrink-0",
            open && "rotate-180",
          )}
          fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {/* Content */}
      {open && (
        <div className={cn(
          "border-t",
          isDecision ? "border-yellow-500/15" : "border-border/25",
        )}>
          <div className="px-7 py-6 sm:px-8 sm:py-7">
            <MarkdownContent content={content} />
          </div>
        </div>
      )}
    </div>
  );
}

/* ── Group header ───────────────────────────────────────────────────── */

function GroupHeader({ name, count }: { name: string; count: number }) {
  return (
    <div className="flex items-center gap-2.5 pt-3 pb-1.5">
      <h3 className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground/50">
        {name}
      </h3>
      <span className="text-[10px] text-muted-foreground/35 tabular-nums">{count}</span>
      <div className="flex-1 h-px bg-border/20 ml-1.5" />
    </div>
  );
}

/* ── Main panel ─────────────────────────────────────────────────────── */

export const ReportPanel = memo(function ReportPanel({ reports }: ReportPanelProps) {
  const entries = Object.entries(reports);

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

  const finalDecision = reports.final_trade_decision;

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="w-8 h-8 rounded-xl bg-primary/10 flex items-center justify-center">
          <svg className="w-4 h-4 text-primary" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
          </svg>
        </div>
        <div>
          <h2 className="text-lg font-semibold tracking-tight">Analysis Report</h2>
          <p className="text-xs text-muted-foreground/50 mt-0.5">
            {entries.length} section{entries.length !== 1 ? "s" : ""}
          </p>
        </div>
      </div>

      {/* Final decision at top */}
      {finalDecision && (
        <SectionCard section="final_trade_decision" content={finalDecision} defaultOpen />
      )}

      {/* Grouped sections */}
      {sortedGroups.map(([group, groupEntries]) => {
        const filtered = groupEntries.filter(([s]) => s !== "final_trade_decision");
        if (filtered.length === 0) return null;

        return (
          <div key={group} className="space-y-2.5">
            <GroupHeader name={group} count={filtered.length} />
            {filtered.map(([section, content]) => (
              <SectionCard
                key={section}
                section={section}
                content={content}
                defaultOpen={filtered.length <= 2}
              />
            ))}
          </div>
        );
      })}
    </div>
  );
});
