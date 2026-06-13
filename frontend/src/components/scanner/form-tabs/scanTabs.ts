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
  // scan/analysis/models are DERIVED from SCANNER_CONFIG_LABELS, not re-typed, so the
  // two forms can never drift (the redesign's cross-form consistency goal): rename a
  // shared label in one place and both forms follow. tsc also guarantees the keys exist.
  scan: SCANNER_CONFIG_LABELS.scan,
  analysis: SCANNER_CONFIG_LABELS.analysis,
  models: SCANNER_CONFIG_LABELS.models,
  autotrade: "Auto-trade",
};
