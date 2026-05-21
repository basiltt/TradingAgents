export const neumorphismRouteBlueprints = [
  {
    route: "/",
    template: "NeuOverviewTemplate",
    composites: ["NeuPageHeader", "NeuKpiGrid", "NeuCard", "NeuEmptyState"],
  },
  {
    route: "/analysis/new",
    template: "NeuWizardTemplate",
    composites: ["AnalysisLaunchWizard", "NeuModelPicker", "NeuMultiSelect", "NeuToggleGroup"],
  },
  {
    route: "/analysis/$runId",
    template: "NeuConsoleTemplate",
    composites: ["AnalysisRunConsole", "NeuReconnectionChip", "NeuTable", "NeuTabs"],
  },
  {
    route: "/history",
    template: "NeuArchiveTemplate",
    composites: ["NeuFilterBar", "NeuTable", "NeuPagination", "NeuStatusPill"],
  },
  {
    route: "/scanner",
    template: "NeuWorkbenchTemplate",
    composites: ["ScanWorkbench", "ScanResultsBoard", "NeuModelPicker", "NeuConfirmDialog"],
  },
  {
    route: "/scanner/history",
    template: "NeuArchiveTemplate",
    composites: ["NeuCard", "NeuFilterBar", "NeuPagination", "NeuDialog"],
  },
  {
    route: "/scanner/schedules",
    template: "NeuWorkbenchTemplate",
    composites: ["NeuDialog", "NeuSelect", "NeuDateField", "NeuToggleGroup"],
  },
  {
    route: "/scanner/$scanId",
    template: "NeuEntityDetailTemplate",
    composites: ["ScanResultsBoard", "NeuConfirmDialog", "NeuDialog", "NeuProgressTrack"],
  },
  {
    route: "/accounts",
    template: "NeuPortfolioGridTemplate",
    composites: ["AccountsGrid", "NeuFilterBar", "NeuDialog", "NeuConfirmDialog"],
  },
  {
    route: "/accounts/$accountId",
    template: "NeuEntityDetailTemplate",
    composites: ["AccountSummaryHero", "NeuTabs", "NeuTable", "NeuDialog"],
  },
  {
    route: "/analytics",
    template: "NeuAnalyticsTemplate",
    composites: ["NeuChartCard", "NeuChartToolbar", "NeuKpiGrid", "NeuConfirmDialog"],
  },
  {
    route: "/strategies",
    template: "NeuLibraryTemplate",
    composites: ["StrategyLibraryBoard", "NeuDialog", "NeuFilterBar", "NeuCard"],
  },
  {
    route: "/cycles",
    template: "NeuTableIndexTemplate",
    composites: ["CycleBoard", "NeuTable", "NeuPagination", "NeuBadge"],
  },
  {
    route: "/cycles/$cycleId",
    template: "NeuEntityDetailTemplate",
    composites: ["CycleBoard", "NeuConfirmDialog", "NeuKpiGrid", "NeuTable"],
  },
  {
    route: "/config",
    template: "NeuInspectorTemplate",
    composites: ["ConfigInspector", "NeuAppearanceStudio", "NeuTable", "NeuBanner"],
  },
  {
    route: "/memory",
    template: "NeuTableIndexTemplate",
    composites: ["MemoryRecordList", "NeuPagination", "NeuBadge", "NeuTable"],
  },
  {
    route: "/trades",
    template: "NeuTableIndexTemplate",
    composites: ["TradeDeskWorkspace", "NeuBanner", "NeuTabs", "NeuConfirmDialog"],
  },
] as const;
