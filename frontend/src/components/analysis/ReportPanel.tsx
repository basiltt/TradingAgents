import { memo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";

interface ReportPanelProps {
  reports: Record<string, string>;
}

const SECTION_LABELS: Record<string, string> = {
  analyst_market: "Market Analysis",
  analyst_social: "Social Analysis",
  analyst_news: "News Analysis",
  analyst_fundamentals: "Fundamentals",
  research_bull: "Bull Case",
  research_bear: "Bear Case",
  research_manager: "Research Summary",
  trader: "Trader",
  risk_aggressive: "Aggressive Risk",
  risk_conservative: "Conservative Risk",
  risk_neutral: "Neutral Risk",
  portfolio_manager: "Portfolio Manager",
  final_trade_decision: "Final Decision",
};

const SECTION_COLORS: Record<string, string> = {
  research_bull: "text-emerald-500",
  research_bear: "text-red-400",
  risk_aggressive: "text-orange-400",
  risk_conservative: "text-blue-400",
  risk_neutral: "text-slate-400",
  final_trade_decision: "text-amber-400",
  trader: "text-violet-400",
  portfolio_manager: "text-amber-400",
};

const SECTION_BORDER_COLORS: Record<string, string> = {
  research_bull: "border-l-emerald-500/40",
  research_bear: "border-l-red-400/40",
  risk_aggressive: "border-l-orange-400/40",
  risk_conservative: "border-l-blue-400/40",
  risk_neutral: "border-l-slate-400/40",
  final_trade_decision: "border-l-amber-400/40",
  trader: "border-l-violet-400/40",
  portfolio_manager: "border-l-amber-400/40",
};

function MarkdownContent({ content }: { content: string }) {
  return (
    <div className="prose prose-sm dark:prose-invert max-w-none
      text-foreground/75 leading-[1.8] tracking-wide
      prose-headings:text-foreground prose-headings:tracking-normal prose-headings:font-semibold
      prose-strong:text-foreground/90 prose-strong:font-semibold
      prose-p:my-3
      prose-ul:my-3 prose-ol:my-3 prose-li:my-1
      prose-h1:text-xl prose-h1:mt-8 prose-h1:mb-3 prose-h1:pb-2 prose-h1:border-b prose-h1:border-border/50
      prose-h2:text-lg prose-h2:mt-7 prose-h2:mb-3
      prose-h3:text-base prose-h3:mt-5 prose-h3:mb-2 prose-h3:text-foreground/90
      prose-blockquote:border-l-primary/30 prose-blockquote:text-foreground/60 prose-blockquote:not-italic
      prose-hr:border-border/40 prose-hr:my-6
      prose-a:text-primary prose-a:no-underline hover:prose-a:underline
      prose-em:text-foreground/70
    ">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
    </div>
  );
}

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
  const label = SECTION_LABELS[section] ?? section;
  const colorClass = SECTION_COLORS[section] ?? "text-primary";
  const borderClass = SECTION_BORDER_COLORS[section] ?? "border-l-primary/40";

  return (
    <div className={cn("rounded-lg border border-border/60 bg-card/50 overflow-hidden border-l-[3px]", borderClass)}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between px-5 py-3.5 text-left hover:bg-muted/30 transition-colors"
      >
        <span className={cn("text-sm font-semibold tracking-wide", colorClass)}>
          {label}
        </span>
        <svg
          className={cn("w-4 h-4 text-muted-foreground transition-transform duration-200", open && "rotate-180")}
          fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      {open && (
        <div className="px-6 pb-6 pt-1">
          <MarkdownContent content={content} />
        </div>
      )}
    </div>
  );
}

export const ReportPanel = memo(function ReportPanel({ reports }: ReportPanelProps) {
  const entries = Object.entries(reports);

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base flex items-center gap-2">
          <svg className="w-4 h-4 text-muted-foreground" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
          </svg>
          Report
          {entries.length > 0 && (
            <span className="ml-auto text-xs text-muted-foreground font-normal">
              {entries.length} section{entries.length !== 1 ? "s" : ""}
            </span>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent>
        {entries.length === 0 ? (
          <div className="flex flex-col items-center py-8 text-center">
            <div className="w-10 h-10 rounded-xl bg-muted flex items-center justify-center mb-2">
              <svg className="w-5 h-5 text-muted-foreground" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
            </div>
            <p className="text-sm text-muted-foreground">No report data yet</p>
          </div>
        ) : (
          <div className="space-y-3">
            {entries.map(([section, content], i) => (
              <SectionCard
                key={section}
                section={section}
                content={content}
                defaultOpen={entries.length <= 3 || i === 0}
              />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
});
