// Tab ids are kebab-case lowercase; labels are human-readable. Single source of
// truth for the order + labels of every tabbed surface in the scanner forms.

export type ScannerConfigTab = "scan" | "analysis" | "models";
export type ScannerResultTab = "results" | "progress" | "config";
export type ScheduledTab = "schedule" | "scan" | "analysis" | "models" | "autotrade";

export const SCANNER_CONFIG_TABS: ScannerConfigTab[] = ["scan", "analysis", "models"];
export const SCANNER_RESULT_TABS: ScannerResultTab[] = ["results", "progress", "config"];
export const SCHEDULED_TABS: ScheduledTab[] = ["schedule", "scan", "analysis", "models", "autotrade"];

export const SCANNER_CONFIG_LABELS: Record<ScannerConfigTab, string> = {
  scan: "Scan",
  analysis: "Analysis",
  models: "Models & Connection",
};

export const SCANNER_RESULT_LABELS: Record<ScannerResultTab, string> = {
  results: "Results",
  progress: "Progress",
  config: "Config",
};

export const SCHEDULED_LABELS: Record<ScheduledTab, string> = {
  schedule: "Schedule",
  scan: "Scan",            // same as SCANNER_CONFIG_LABELS.scan
  analysis: "Analysis",    // same as SCANNER_CONFIG_LABELS.analysis
  models: "Models & Connection",
  autotrade: "Auto-trade",
};
