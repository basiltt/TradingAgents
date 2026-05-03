import { memo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ScrollArea } from "@/components/ui/scroll-area";

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
  final_trade_decision: "Final Trade Decision",
};

function MarkdownContent({ content }: { content: string }) {
  return (
    <div className="prose prose-sm dark:prose-invert max-w-none text-foreground/80 leading-relaxed prose-headings:text-foreground prose-strong:text-foreground prose-p:my-2 prose-ul:my-2 prose-ol:my-2 prose-li:my-0.5 prose-h2:text-lg prose-h2:mt-6 prose-h2:mb-2 prose-h3:text-base prose-h3:mt-4 prose-h3:mb-1">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
    </div>
  );
}

const SECTION_ICONS: Record<string, string> = {
  analyst_market: "M13 7h8m0 0v8m0-8l-8 8-4-4-6 6",
  analyst_social: "M17 8h2a2 2 0 012 2v6a2 2 0 01-2 2h-2v4l-4-4H9a1.994 1.994 0 01-1.414-.586m0 0L11 14h4a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2v4l.586-.586z",
  analyst_news: "M19 20H5a2 2 0 01-2-2V6a2 2 0 012-2h10a2 2 0 012 2v1m2 13a2 2 0 01-2-2V7m2 13a2 2 0 002-2V9a2 2 0 00-2-2h-2m-4-3H9M7 16h6M7 8h6v4H7V8z",
  analyst_fundamentals: "M9 7h6m0 10v-3m-3 3h.01M9 17v-3m3 3h.01M9 14v-3m3 3h.01M12 14v-3m3 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z",
  research_bull: "M13 7h8m0 0v8m0-8l-8 8-4-4-6 6",
  research_bear: "M13 17h8m0 0V9m0 8l-8-8-4 4-6-6",
};

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
        ) : entries.length <= 3 ? (
          <div className="space-y-4">
            {entries.map(([section, content]) => (
              <div key={section} className="rounded-lg border bg-muted/30 p-4">
                <h4 className="text-sm font-semibold mb-2 flex items-center gap-2">
                  {SECTION_ICONS[section] && (
                    <svg className="w-4 h-4 text-primary" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d={SECTION_ICONS[section]} />
                    </svg>
                  )}
                  {SECTION_LABELS[section] ?? section}
                </h4>
                <MarkdownContent content={content} />
              </div>
            ))}
          </div>
        ) : (
          <Tabs defaultValue={entries[0][0]} className="w-full">
            <ScrollArea className="w-full">
              <TabsList className="w-full justify-start h-auto flex-wrap gap-1 bg-muted/50 p-1">
                {entries.map(([section]) => (
                  <TabsTrigger key={section} value={section} className="text-xs px-3 py-1.5">
                    {SECTION_LABELS[section] ?? section}
                  </TabsTrigger>
                ))}
              </TabsList>
            </ScrollArea>
            {entries.map(([section, content]) => (
              <TabsContent key={section} value={section} className="mt-4">
                <div className="rounded-lg border bg-muted/30 p-4">
                  <MarkdownContent content={content} />
                </div>
              </TabsContent>
            ))}
          </Tabs>
        )}
      </CardContent>
    </Card>
  );
});
