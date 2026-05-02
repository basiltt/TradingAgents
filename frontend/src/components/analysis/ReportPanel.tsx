import { memo } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";

interface ReportPanelProps {
  reports: Record<string, string>;
}

const SECTION_LABELS: Record<string, string> = {
  analyst_market: "Market Analysis",
  analyst_social: "Social Analysis",
  analyst_news: "News Analysis",
  analyst_fundamentals: "Fundamentals Analysis",
  research_bull: "Bull Research",
  research_bear: "Bear Research",
  research_manager: "Research Manager",
  trader: "Trader",
  risk_aggressive: "Aggressive Risk",
  risk_conservative: "Conservative Risk",
  risk_neutral: "Neutral Risk",
  portfolio_manager: "Portfolio Manager",
};

export const ReportPanel = memo(function ReportPanel({ reports }: ReportPanelProps) {
  const entries = Object.entries(reports);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Report</CardTitle>
      </CardHeader>
      <CardContent>
        {entries.length === 0 ? (
          <p className="text-sm text-muted-foreground">No report data yet</p>
        ) : (
          <div className="space-y-4">
            {entries.map(([section, content]) => (
              <div key={section}>
                <h4 className="text-sm font-semibold mb-1">
                  {SECTION_LABELS[section] ?? section}
                </h4>
                <p className="text-sm whitespace-pre-wrap">{content}</p>
                <Separator className="mt-3" />
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
});
