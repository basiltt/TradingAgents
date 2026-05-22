import { useMemo, useState, type ReactNode } from "react";
import { Provider } from "react-redux";
import {
  Activity,
  AlertTriangle,
  ArrowUpRight,
  BarChart3,
  Bot,
  BriefcaseBusiness,
  ChartCandlestick,
  Database,
  Download,
  LayoutDashboard,
  MemoryStick,
  PanelRight,
  Radar,
  RefreshCcw,
  Search,
  Settings2,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Wallet,
  Workflow,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { NeuChartCard, NeuChartToolbar, NeuLegendChip } from "../charts";
import {
  AccountSummaryHero,
  AccountsGrid,
  AnalysisLaunchWizard,
  AnalysisRunConsole,
  ConfigInspector,
  CycleBoard,
  MemoryRecordList,
  ScanResultsBoard,
  ScanWorkbench,
  StrategyLibraryBoard,
  TradeDeskWorkspace,
} from "../composites";
import {
  NeuBadge,
  NeuCard,
  NeuEmptyState,
  NeuFilterBar,
  NeuKpiGrid,
  NeuPagination,
  NeuProgressTrack,
  NeuScoreBar,
  NeuSkeleton,
  NeuTable,
  NeuTickerMetric,
} from "../display";
import {
  NeuDivider,
  NeuGlowAccent,
  NeuPanel,
  NeuSurface,
  NeuThemeScope,
  NeuWell,
} from "../foundation";
import {
  NeuEntityHeader,
  NeuPageHeader,
  NeuStatCapsule,
  NeuStatusPill,
} from "../headers";
import {
  NeuAccountPicker,
  type NeuAccountPickerOption,
  NeuButton,
  NeuCheckbox,
  NeuCombobox,
  NeuDateField,
  NeuIconButton,
  NeuInput,
  NeuModelPicker,
  NeuMultiSelect,
  NeuRadioGroup,
  NeuSelect,
  NeuSlider,
  NeuSwitch,
  NeuTabs,
  NeuTextArea,
  NeuToggleGroup,
} from "../inputs";
import {
  NeuBanner,
  NeuConfirmDialog,
  NeuDialog,
  NeuDrawer,
  NeuReconnectionChip,
  NeuToast,
} from "../overlays";
import { neumorphismComponentChecklist } from "../registry";
import { neumorphismRouteBlueprints } from "../route-blueprints";
import { neumorphismRouteLayoutModels } from "../route-models";
import {
  setCommandPaletteOpen,
  setNeuAccent,
  setNeuContrast,
  setNeuMode,
} from "../state/neu-ui-slice";
import {
  createNeuPreviewStore,
  useNeuPreviewDispatch,
  useNeuPreviewSelector,
} from "../state/preview-store";
import {
  NeuAppShell,
  NeuAppearanceStudio,
  NeuCommandPalette,
  NeuMarketStrip,
  NeuMobileDock,
  NeuNavItem,
  NeuSidebar,
  NeuTopbar,
} from "../shell";
import {
  NeuAlertStack,
  NeuFormGrid,
  NeuFormSection,
  NeuPageSection,
  NeuRouteModelCard,
  NeuSplitLayout,
  NeuTouchActionBar,
} from "../structure";
import {
  NeuAnalyticsTemplate,
  NeuArchiveTemplate,
  NeuConsoleTemplate,
  NeuEntityDetailTemplate,
  NeuInspectorTemplate,
  NeuLibraryTemplate,
  NeuOverviewTemplate,
  NeuPortfolioGridTemplate,
  NeuTableIndexTemplate,
  NeuWizardTemplate,
  NeuWorkbenchTemplate,
} from "../templates";
import type { NeuMetric, NeuOption } from "../types";

type ChecklistSection = keyof typeof neumorphismComponentChecklist;
type AuditComponentName = (typeof neumorphismComponentChecklist)[ChecklistSection][number];
type AuditSample = {
  description: string;
  content: ReactNode;
  panelClassName?: string;
  bodyClassName?: string;
};

const providerOptions: NeuOption[] = [
  { value: "openai", label: "OpenAI", description: "Primary hosted reasoning suite", group: "Hosted" },
  { value: "anthropic", label: "Anthropic", description: "Long-context fallback", group: "Hosted" },
  { value: "google", label: "Google", description: "Realtime multimodal branch", group: "Hosted" },
];

const modelOptions: NeuOption[] = [
  { value: "gpt-5", label: "GPT-5", description: "High-confidence portfolio orchestration", group: "Frontier" },
  { value: "gpt-5-mini", label: "GPT-5 Mini", description: "Lower-latency sweep passes", group: "Frontier" },
  { value: "claude-sonnet", label: "Claude Sonnet", description: "Narrative and policy synthesis", group: "Fallback" },
  { value: "gemini-2.5-pro", label: "Gemini 2.5 Pro", description: "Deep research cross-check", group: "Fallback" },
];

const analystOptions: NeuOption[] = [
  { value: "market", label: "Market", description: "Technical structure and breadth" },
  { value: "news", label: "News", description: "Macro and catalyst sweep" },
  { value: "social", label: "Social", description: "Sentiment dispersion and flow" },
  { value: "fundamentals", label: "Fundamentals", description: "Balance sheet and filings" },
];

const watchlistOptions: NeuOption[] = [
  { value: "growth", label: "Growth leaders", description: "AI and software leaders" },
  { value: "crypto-core", label: "Crypto core", description: "BTC, ETH, SOL, ecosystem beta" },
  { value: "swing", label: "Swing board", description: "High-conviction tactical setups" },
  { value: "event", label: "Event drive", description: "Earnings and catalysts" },
];

const shellSections = [
  {
    title: "Overview",
    items: [
      {
        id: "dashboard",
        label: "Dashboard",
        description: "System overview",
        href: "/",
        icon: LayoutDashboard,
        active: true,
      },
    ],
  },
  {
    title: "Research",
    items: [
      {
        id: "analysis",
        label: "Analysis",
        description: "Launch research",
        href: "/analysis/new",
        icon: Bot,
      },
      {
        id: "scanner",
        label: "Scanner",
        description: "Batch scans",
        href: "/scanner",
        icon: Radar,
      },
    ],
  },
  {
    title: "Portfolio",
    items: [
      {
        id: "accounts",
        label: "Accounts",
        description: "Portfolio view",
        href: "/accounts",
        icon: Wallet,
      },
      {
        id: "analytics",
        label: "Analytics",
        description: "Curve and attribution",
        href: "/analytics",
        icon: BarChart3,
      },
    ],
  },
  {
    title: "System",
    items: [
      {
        id: "config",
        label: "Config",
        description: "Runtime settings",
        href: "/config",
        icon: Settings2,
      },
      {
        id: "memory",
        label: "Memory",
        description: "Decision records",
        href: "/memory",
        icon: MemoryStick,
        badge: <NeuBadge tone="accent" variant="soft">4</NeuBadge>,
      },
    ],
  },
];

const accountPickerSeed: NeuAccountPickerOption[] = [
  { id: "acc-1", label: "Prime Futures", subtitle: "Live · Binance · cross margin", included: true, meta: "Live" },
  { id: "acc-2", label: "Demo Momentum", subtitle: "Demo · Bybit · sandbox", included: true, meta: "Demo" },
  { id: "acc-3", label: "Archive Arb", subtitle: "Read only · Hyperliquid snapshots", included: false, meta: "Archive" },
];

const tradeRows = [
  { id: "t-1", symbol: "NVDA", side: "Long", status: "Open", pnl: "+$842" },
  { id: "t-2", symbol: "ETHUSD", side: "Short", status: "Open", pnl: "+$214" },
  { id: "t-3", symbol: "TSLA", side: "Long", status: "Exited", pnl: "-$98" },
];

const routeCommandGroups = [
  {
    id: "routes",
    title: "Routes",
    items: neumorphismRouteBlueprints.slice(0, 10).map((entry) => ({
      id: entry.route,
      label: entry.route,
      description: entry.template,
      keywords: [...entry.composites],
      active: entry.route === "/",
      onSelect: () => {},
      meta: <NeuBadge tone="accent" variant="soft">{entry.composites.length} comps</NeuBadge>,
    })),
  },
];

const sectionMeta: Record<
  ChecklistSection,
  { title: string; description: string; gridClassName: string }
> = {
  foundations: {
    title: "Foundations",
    description: "Material primitives that set the depth hierarchy, shadow language, and soft geometry.",
    gridClassName: "xl:grid-cols-2",
  },
  structure: {
    title: "Structure",
    description: "Responsive sections, forms, alert rails, touch action bars, and route-level layout models for every page family.",
    gridClassName: "grid-cols-1",
  },
  shell: {
    title: "Shell",
    description: "App frame, navigation, mobility, and theme controls that define the overall spatial system.",
    gridClassName: "xl:grid-cols-2",
  },
  headers: {
    title: "Headers",
    description: "Page-level orientation, state signaling, and compact statistical summaries.",
    gridClassName: "xl:grid-cols-2",
  },
  inputs: {
    title: "Inputs",
    description: "Interactive controls with explicit raised, inset, selected, disabled, and feedback states.",
    gridClassName: "xl:grid-cols-2",
  },
  display: {
    title: "Display",
    description: "Core data presentation surfaces for cards, tables, filters, pagination, and progress readouts.",
    gridClassName: "xl:grid-cols-2",
  },
  charts: {
    title: "Charts",
    description: "Analytics wrappers that keep dense charting readable inside the neumorphic material field.",
    gridClassName: "xl:grid-cols-2",
  },
  overlays: {
    title: "Overlays",
    description: "Dialogs, drawers, toasts, banners, and connection chips that float above the primary surface.",
    gridClassName: "xl:grid-cols-2",
  },
  composites: {
    title: "Composites",
    description: "TradingAgents-specific workflows assembled from the shared component vocabulary.",
    gridClassName: "grid-cols-1",
  },
  templates: {
    title: "Templates",
    description: "Layout scaffolds for complete route families before the real routes are migrated.",
    gridClassName: "grid-cols-1",
  },
};

function AuditCard({ name, sample }: { name: AuditComponentName; sample: AuditSample }) {
  return (
    <NeuPanel
      title={name}
      description={sample.description}
      dense
      className={cn("h-full", sample.panelClassName)}
    >
      <div className={cn("space-y-4", sample.bodyClassName)}>{sample.content}</div>
    </NeuPanel>
  );
}

function AuditSection({
  section,
  count,
  children,
}: {
  section: ChecklistSection;
  count: number;
  children: ReactNode;
}) {
  const meta = sectionMeta[section];

  return (
    <section id={`audit-${section}`} className="scroll-mt-4">
      <NeuSurface depth="flat" radius="lg" padding="lg" className="space-y-5">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="space-y-1">
            <p
              className="text-[11px] font-semibold uppercase tracking-[0.18em]"
              style={{ color: "var(--neu-text-muted)" }}
            >
              Component audit
            </p>
            <h2 className="text-2xl font-semibold tracking-[-0.04em]">{meta.title}</h2>
            <p className="max-w-4xl text-sm leading-7" style={{ color: "var(--neu-text-muted)" }}>
              {meta.description}
            </p>
          </div>
          <NeuStatusPill label={`${count} components`} tone="accent" />
        </div>
        <div className={cn("grid gap-5", meta.gridClassName)}>{children}</div>
      </NeuSurface>
    </section>
  );
}

function PlaceholderCard({
  title,
  eyebrow,
  detail,
  tone = "neutral",
}: {
  title: string;
  eyebrow?: string;
  detail?: string;
  tone?: "neutral" | "accent" | "success" | "warning" | "danger";
}) {
  return (
    <NeuSurface depth="raised" tone={tone} radius="md" padding="md" className="space-y-3">
      {eyebrow ? (
        <p
          className="text-[11px] font-semibold uppercase tracking-[0.18em]"
          style={{ color: "var(--neu-text-muted)" }}
        >
          {eyebrow}
        </p>
      ) : null}
      <div className="space-y-2">
        <p className="text-sm font-semibold">{title}</p>
        <NeuSkeleton shape="text" lines={2} />
      </div>
      {detail ? (
        <p className="text-xs leading-6" style={{ color: "var(--neu-text-muted)" }}>
          {detail}
        </p>
      ) : null}
    </NeuSurface>
  );
}

function TemplatePreviewHeader({
  eyebrow,
  title,
  description,
}: {
  eyebrow: string;
  title: string;
  description: string;
}) {
  return (
    <NeuPageHeader
      eyebrow={eyebrow}
      title={title}
      description={description}
      variant="dense"
      actions={
        <div className="flex flex-wrap gap-2">
          <NeuButton size="sm" variant="secondary">
            Review
          </NeuButton>
          <NeuButton size="sm" variant="soft-tonal">
            Promote
          </NeuButton>
        </div>
      }
      stats={[
        { label: "Signals", value: "14", tone: "accent" },
        { label: "Latency", value: "42 ms", tone: "success" },
      ]}
    />
  );
}

function PreviewWorkspace() {
  const dispatch = useNeuPreviewDispatch();
  const ui = useNeuPreviewSelector((state) => state.neuUi);

  const [commandQuery, setCommandQuery] = useState("");
  const [previewSearch, setPreviewSearch] = useState("");
  const [thesis, setThesis] = useState(
    "Favor resilient, contrast-safe neumorphic surfaces for dense analyst workflows.",
  );
  const [selectedProvider, setSelectedProvider] = useState("openai");
  const [selectedAnalysts, setSelectedAnalysts] = useState<string[]>(["market", "news"]);
  const [comboValue, setComboValue] = useState("NVDA");
  const [executionMode, setExecutionMode] = useState("assisted");
  const [coverageMix, setCoverageMix] = useState<string[]>(["market", "fundamentals"]);
  const [tabValue, setTabValue] = useState("summary");
  const [riskLocked, setRiskLocked] = useState(true);
  const [notificationsEnabled, setNotificationsEnabled] = useState(false);
  const [switchActive, setSwitchActive] = useState(true);
  const [switchSuccess, setSwitchSuccess] = useState(true);
  const [switchWarning, setSwitchWarning] = useState(false);
  const [horizon, setHorizon] = useState("swing");
  const [confidenceValue, setConfidenceValue] = useState(68);
  const [riskRange, setRiskRange] = useState<[number, number]>([25, 80]);
  const [evaluationDate, setEvaluationDate] = useState("2026-05-21");
  const [selectedModel, setSelectedModel] = useState("gpt-5");
  const [selectedAccount, setSelectedAccount] = useState("acc-1");
  const [pickerAccounts, setPickerAccounts] = useState(accountPickerSeed);
  const [chartPeriod, setChartPeriod] = useState("1M");
  const [chartScope, setChartScope] = useState("all");
  const [activeLegends, setActiveLegends] = useState<string[]>(["equity", "benchmark"]);
  const [paginationPage, setPaginationPage] = useState(2);
  const [pageSize, setPageSize] = useState(25);
  const [accountFilter, setAccountFilter] = useState("all");
  const [strategyFilter, setStrategyFilter] = useState("all");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerSide, setDrawerSide] = useState<"left" | "right" | "bottom">("right");
  const [confirmOpen, setConfirmOpen] = useState(false);

  const totalComponents = useMemo(
    () => Object.values(neumorphismComponentChecklist).reduce((total, names) => total + names.length, 0),
    [],
  );

  const topLevelMetrics: NeuMetric[] = [
    { label: "Audited components", value: totalComponents, tone: "accent", icon: <Workflow className="size-4" /> },
    { label: "Route blueprints", value: neumorphismRouteBlueprints.length, tone: "success", icon: <ShieldCheck className="size-4" /> },
    { label: "Composite boards", value: neumorphismComponentChecklist.composites.length, tone: "warning", icon: <Radar className="size-4" /> },
    { label: "Template families", value: neumorphismComponentChecklist.templates.length, tone: "neutral", icon: <PanelRight className="size-4" /> },
  ];

  const commandGroups = useMemo(
    () =>
      routeCommandGroups.map((group) => ({
        ...group,
        items: group.items.map((item) => ({
          ...item,
          onSelect: () => dispatch(setCommandPaletteOpen(false)),
        })),
      })),
    [dispatch],
  );

  const filterChips = [
    { id: "all", label: "All", active: accountFilter === "all", tone: "accent" as const, onSelect: () => setAccountFilter("all") },
    { id: "live", label: "Live", active: accountFilter === "live", tone: "success" as const, onSelect: () => setAccountFilter("live") },
    { id: "demo", label: "Demo", active: accountFilter === "demo", tone: "warning" as const, onSelect: () => setAccountFilter("demo") },
  ];

  const strategyChips = [
    { id: "all", label: "All", active: strategyFilter === "all", tone: "accent" as const, onSelect: () => setStrategyFilter("all") },
    { id: "active", label: "Active", active: strategyFilter === "active", tone: "success" as const, onSelect: () => setStrategyFilter("active") },
    { id: "draft", label: "Draft", active: strategyFilter === "draft", tone: "warning" as const, onSelect: () => setStrategyFilter("draft") },
  ];

  const tableRows = [
    { id: "r-1", symbol: "AAPL", regime: "Trend continuation", score: 8.2, updatedAt: "08:42 UTC" },
    { id: "r-2", symbol: "BTCUSD", regime: "Breakout retest", score: 7.6, updatedAt: "08:44 UTC" },
    { id: "r-3", symbol: "NVDA", regime: "Range compression", score: 6.9, updatedAt: "08:49 UTC" },
  ];

  const walletMetrics: NeuMetric[] = [
    { label: "Wallet equity", value: "$128,440", tone: "accent", delta: "+3.2%", trend: "up" },
    { label: "Available margin", value: "$42,118", tone: "success", delta: "Room for 3 more trades", trend: "up" },
  ];

  const pnlMetrics: NeuMetric[] = [
    { label: "Day PnL", value: "+$1,142", tone: "success", delta: "6 winners / 1 loser", trend: "up" },
    { label: "Open risk", value: "$812", tone: "warning", delta: "Risk lock active", trend: "flat" },
  ];

  const templateSummary = (
    <NeuKpiGrid
      dense
      columns="4-up"
      items={[
        { label: "Widgets", value: "12", tone: "accent" },
        { label: "Alerts", value: "3", tone: "warning" },
        { label: "Latency", value: "42 ms", tone: "success" },
        { label: "Coverage", value: "98%", tone: "neutral" },
      ]}
    />
  );

  const templateToolbar = (
    <NeuFilterBar
      compact
      filters={strategyChips}
      search={
        <NeuInput
          value={previewSearch}
          onChange={(event) => setPreviewSearch(event.target.value)}
          placeholder="Filter samples"
          leadingIcon={<Search className="size-4" />}
        />
      }
      actions={
        <NeuButton size="sm" variant="secondary">
          <SlidersHorizontal className="size-4" />
          Refine
        </NeuButton>
      }
    />
  );

  const routeModelGrid = (
    <div className="grid gap-4 2xl:grid-cols-2">
      {neumorphismRouteLayoutModels.map((model) => (
        <NeuRouteModelCard key={model.route} model={model} />
      ))}
    </div>
  );

  const auditSamples: Record<AuditComponentName, AuditSample> = {
    NeuSurface: {
      description: "Raised, inset, accent, and disabled depths all share the same light source and radius system.",
      content: (
        <div className="grid gap-3 md:grid-cols-2">
          <NeuSurface depth="raised" radius="md" padding="md" interactive className="space-y-2">
            <p className="text-sm font-semibold">Raised</p>
            <p className="text-xs leading-6" style={{ color: "var(--neu-text-muted)" }}>
              Default container depth for cards and action groups.
            </p>
          </NeuSurface>
          <NeuSurface depth="inset" radius="md" padding="md" className="space-y-2">
            <p className="text-sm font-semibold">Inset</p>
            <p className="text-xs leading-6" style={{ color: "var(--neu-text-muted)" }}>
              Recessed wells for inputs, charts, and pressed states.
            </p>
          </NeuSurface>
          <NeuSurface depth="accent" radius="md" padding="md" className="space-y-2">
            <p className="text-sm font-semibold">Accent</p>
            <p className="text-xs leading-6" style={{ color: "var(--neu-text-muted)" }}>
              Reserved for selected, primary, and high-attention material.
            </p>
          </NeuSurface>
          <NeuSurface depth="disabled" radius="md" padding="md" className="space-y-2">
            <p className="text-sm font-semibold">Disabled</p>
            <p className="text-xs leading-6" style={{ color: "var(--neu-text-muted)" }}>
              Reduced relief and contrast without collapsing the geometry.
            </p>
          </NeuSurface>
        </div>
      ),
    },
    NeuPanel: {
      description: "Structured panel with header, actions, footer, and a scroll-safe content well.",
      content: (
        <NeuPanel
          title="Execution notes"
          description="Panels provide the macro structure used across settings, boards, and inspectors."
          actions={
            <NeuButton size="sm" variant="secondary">
              <RefreshCcw className="size-4" />
              Refresh
            </NeuButton>
          }
          footer={
            <>
              <NeuStatusPill label="Stable" tone="success" />
              <NeuButton size="sm" variant="soft-tonal">
                View log
              </NeuButton>
            </>
          }
        >
          <NeuWell padding="sm" className="space-y-3">
            <PlaceholderCard title="Signal digest" detail="Nested wells stay visibly inset relative to the parent panel." />
          </NeuWell>
        </NeuPanel>
      ),
    },
    NeuWell: {
      description: "Inset receptacle for chart bodies, text areas, pressed states, and low-emphasis groupings.",
      content: (
        <div className="grid gap-3 md:grid-cols-3">
          <NeuWell padding="sm" className="space-y-2">
            <p className="text-sm font-semibold">Default</p>
            <NeuSkeleton shape="text" lines={2} />
          </NeuWell>
          <NeuWell padding="sm" focused className="space-y-2">
            <p className="text-sm font-semibold">Focused</p>
            <NeuSkeleton shape="text" lines={2} />
          </NeuWell>
          <NeuWell padding="sm" disabled className="space-y-2">
            <p className="text-sm font-semibold">Disabled</p>
            <NeuSkeleton shape="text" lines={2} />
          </NeuWell>
        </div>
      ),
    },
    NeuDivider: {
      description: "Soft separators retain the single-material illusion instead of switching to hard flat lines.",
      content: (
        <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_12rem]">
          <NeuSurface depth="raised" radius="md" padding="md" className="space-y-4">
            <p className="text-sm font-semibold">Horizontal rhythm</p>
            <NeuDivider />
            <p className="text-xs leading-6" style={{ color: "var(--neu-text-muted)" }}>
              Dividers are intentionally low-contrast so the surfaces stay pillowy instead of harsh.
            </p>
            <NeuDivider inset />
            <p className="text-xs leading-6" style={{ color: "var(--neu-text-muted)" }}>
              Inset spacing prevents hard edge collisions.
            </p>
          </NeuSurface>
          <NeuSurface depth="raised" radius="md" padding="md" className="flex items-stretch justify-between gap-4">
            <div className="flex-1 text-xs" style={{ color: "var(--neu-text-muted)" }}>
              Left zone
            </div>
            <NeuDivider orientation="vertical" decorative={false} />
            <div className="flex-1 text-right text-xs" style={{ color: "var(--neu-text-muted)" }}>
              Right zone
            </div>
          </NeuSurface>
        </div>
      ),
    },
    NeuGlowAccent: {
      description: "Ambient glow accents stay soft and blurred so they support the surface instead of becoming the surface.",
      content: (
        <div className="relative overflow-hidden rounded-[var(--neu-radius-lg)]">
          <NeuSurface depth="flat" radius="lg" padding="lg" className="relative min-h-44 overflow-hidden">
            <NeuGlowAccent tone="accent" size="lg" className="absolute left-0 top-0" />
            <NeuGlowAccent tone="success" size="md" subtle className="absolute bottom-0 right-0" />
            <NeuGlowAccent tone="warning" size="sm" subtle className="absolute right-12 top-12" />
            <div className="relative grid gap-3 md:grid-cols-3">
              <PlaceholderCard title="Accent glow" eyebrow="Cobalt" />
              <PlaceholderCard title="Success glow" eyebrow="Sage" />
              <PlaceholderCard title="Warning glow" eyebrow="Amber" />
            </div>
          </NeuSurface>
        </div>
      ),
    },
    NeuPageSection: {
      description: "Page sections create calmer route rhythm with clear hierarchy, actions, and supporting badges.",
      content: (
        <NeuPageSection
          eyebrow="Route section"
          title="Scanner execution controls"
          description="Use page sections to break long operational pages into tactile macro-zones before dense data begins."
          badge={<NeuBadge tone="accent" variant="soft" size="sm">Primary zone</NeuBadge>}
          actions={
            <div className="flex flex-wrap gap-2">
              <NeuButton size="sm" variant="secondary">Clone</NeuButton>
              <NeuButton size="sm" variant="soft-tonal">Run now</NeuButton>
            </div>
          }
          footer={
            <>
              <NeuStatusPill label="Touch safe" tone="success" />
              <NeuBadge tone="warning" variant="outline" size="sm">2 drawers</NeuBadge>
            </>
          }
        >
          <div className="grid gap-3 md:grid-cols-3">
            <PlaceholderCard title="Primary inputs" eyebrow="Zone A" detail="Universe, model, and analysts." />
            <PlaceholderCard title="Execution toggles" eyebrow="Zone B" detail="Concurrency, timing, and safeguards." />
            <PlaceholderCard title="Automation notes" eyebrow="Zone C" detail="Explain why the next action matters." />
          </div>
        </NeuPageSection>
      ),
    },
    NeuFormGrid: {
      description: "Responsive form grids keep complex configuration pages readable while remaining thumb-safe on smaller devices.",
      content: (
        <NeuSurface depth="raised" radius="lg" padding="md" className="space-y-4">
          <NeuFormGrid columns="responsive">
            <NeuInput label="Asset universe" value="Crypto majors" onChange={() => {}} helperText="Primary scan scope" />
            <NeuSelect label="Provider" options={providerOptions} value={selectedProvider} onChange={setSelectedProvider} />
            <NeuCombobox label="Focus symbol" options={["BTC", "ETH", "SOL", "NVDA"]} value={comboValue} onChange={setComboValue} />
            <NeuDateField label="Evaluation date" value={evaluationDate} onChange={setEvaluationDate} />
            <NeuSlider label="Confidence threshold" value={confidenceValue} min={0} max={100} onValueChange={(value) => setConfidenceValue(Number(value))} />
            <NeuToggleGroup
              label="Execution mode"
              value={executionMode}
              onChange={(value) => setExecutionMode(value as string)}
              options={[
                { value: "assisted", label: "Assisted" },
                { value: "auto", label: "Auto" },
                { value: "hybrid", label: "Hybrid" },
              ]}
            />
          </NeuFormGrid>
        </NeuSurface>
      ),
    },
    NeuFormSection: {
      description: "Form sections bundle dense fields, helper copy, and CTA rows into one route-ready surface.",
      content: (
        <NeuFormSection
          title="Execution policy"
          description="Group related controls so a wizard or settings page stays legible in both desktop and stacked mobile mode."
          columns="2-up"
          footer={
            <div className="flex w-full flex-wrap justify-between gap-2">
              <NeuBadge tone="success" variant="soft" size="sm">Autosave healthy</NeuBadge>
              <div className="flex gap-2">
                <NeuButton size="sm" variant="secondary">Save draft</NeuButton>
                <NeuButton size="sm" variant="soft-tonal">Apply</NeuButton>
              </div>
            </div>
          }
        >
          <NeuSelect label="Primary provider" options={providerOptions} value={selectedProvider} onChange={setSelectedProvider} />
          <NeuModelPicker
            provider={selectedProvider}
            label="Execution model"
            options={modelOptions}
            value={selectedModel}
            onChange={setSelectedModel}
            recents={["gpt-5", "gpt-5-mini"]}
          />
          <NeuMultiSelect label="Coverage mix" options={analystOptions} value={coverageMix} onChange={setCoverageMix} />
          <NeuTextArea label="Risk memo" value={thesis} onChange={(event) => setThesis(event.target.value)} rows={4} />
        </NeuFormSection>
      ),
    },
    NeuSplitLayout: {
      description: "Split layouts standardize the main-plus-aside pattern used by dashboards, workbenches, and detail pages.",
      content: (
        <NeuSplitLayout
          primary={
            <NeuPageSection
              title="Primary canvas"
              description="Dense tables, charts, or workflow content live here without losing macro-structure."
              badge={<NeuBadge tone="accent" variant="soft" size="sm">Primary</NeuBadge>}
            >
              <div className="grid gap-3 md:grid-cols-2">
                <PlaceholderCard title="KPI group" eyebrow="Summary" />
                <PlaceholderCard title="Activity board" eyebrow="Live" />
              </div>
            </NeuPageSection>
          }
          secondary={
            <NeuPageSection
              title="Secondary zone"
              description="Supplementary controls, helper notes, or smaller reports can sit below the main payload."
              badge={<NeuBadge tone="neutral" variant="outline" size="sm">Secondary</NeuBadge>}
            >
              <PlaceholderCard title="Context helper" detail="Good for archive filters and low-frequency admin tools." />
            </NeuPageSection>
          }
          aside={
            <NeuPageSection
              title="Sticky aside"
              description="Good for alerts, summaries, filters, and high-priority calls to action."
              badge={<NeuBadge tone="warning" variant="soft" size="sm">Aside</NeuBadge>}
              dense
            >
              <div className="space-y-3">
                <PlaceholderCard title="Alert rail" eyebrow="Support" />
                <PlaceholderCard title="Action drawer shortcuts" eyebrow="Mobile" />
              </div>
            </NeuPageSection>
          }
          stickyAside
        />
      ),
    },
    NeuAlertStack: {
      description: "Alert stacks replace ad hoc status clutter with consistent alert cards, badges, and recovery actions.",
      content: (
        <NeuAlertStack
          items={[
            {
              id: "alert-1",
              tone: "warning",
              title: "Latency expanded above target",
              description: "The scanner worker crossed 85 ms for the last three refresh windows. Keep the alert visible but non-destructive.",
              badge: <NeuBadge tone="warning" variant="soft" size="sm" dot pulse>runtime</NeuBadge>,
              meta: "Updated 2m ago",
              actions: (
                <>
                  <NeuButton size="sm" variant="secondary">Inspect</NeuButton>
                  <NeuButton size="sm" variant="soft-tonal">Retry worker</NeuButton>
                </>
              ),
            },
            {
              id: "alert-2",
              tone: "danger",
              title: "Credentials need rotation",
              description: "Account detail routes should surface sensitive account issues without flattening the shell hierarchy.",
              badge: <NeuBadge tone="danger" variant="ghost" size="sm" dot>security</NeuBadge>,
              meta: "High priority",
              actions: <NeuButton size="sm" variant="danger">Open credentials drawer</NeuButton>,
            },
          ]}
        />
      ),
    },
    NeuTouchActionBar: {
      description: "Touch action bars keep the highest-frequency controls in the lower reach zone on mobile layouts.",
      content: (
        <NeuTouchActionBar
          title="Scanner controls"
          description="Use this on smaller screens where the primary actions would otherwise scroll out of reach."
          meta={<NeuBadge tone="accent" variant="soft" size="sm">Mobile first</NeuBadge>}
          actions={
            <>
              <NeuButton size="sm" variant="secondary">Save</NeuButton>
              <NeuButton size="sm" variant="soft-tonal">Schedule</NeuButton>
              <NeuButton size="sm" variant="primary">Run scan</NeuButton>
            </>
          }
        />
      ),
    },
    NeuRouteModelCard: {
      description: "Every audited route now has a desktop/mobile layout model so the redesign covers page structure, not only isolated widgets.",
      panelClassName: "overflow-hidden",
      bodyClassName: "space-y-5",
      content: routeModelGrid,
    },
    NeuAppShell: {
      description: "The entire preview page is running inside NeuAppShell; this specimen calls out the live shell zones.",
      content: (
        <div className="grid gap-3 md:grid-cols-4">
          <PlaceholderCard title="Sidebar rail" eyebrow="Zone 1" detail="Persistent navigation and identity" />
          <PlaceholderCard title="Topbar stack" eyebrow="Zone 2" detail="Context, actions, and market strip" />
          <PlaceholderCard title="Main canvas" eyebrow="Zone 3" detail="Checklist-driven audit sections" />
          <PlaceholderCard title="Mobile dock" eyebrow="Zone 4" detail="Compact touch navigation" />
        </div>
      ),
    },
    NeuSidebar: {
      description: "Full and collapsed rails keep the same depth hierarchy while scaling typography and icon emphasis.",
      panelClassName: "overflow-hidden",
      content: (
        <div className="grid gap-4 xl:grid-cols-[18rem_7rem_minmax(0,1fr)]">
          <div className="h-[32rem]">
            <NeuSidebar
              sections={[...shellSections]}
              activePath="/"
              footer={<NeuAlertStack compact items={[{ id: "sidebar-warning", tone: "warning", title: "2 live alerts", description: "Queue and auth warnings remain visible in the rail." }]} />}
            />
          </div>
          <div className="h-[32rem]">
            <NeuSidebar sections={[...shellSections]} activePath="/" collapsed />
          </div>
          <div className="max-w-md">
            <NeuSidebar
              sections={[...shellSections]}
              activePath="/scanner"
              mode="mobile-sheet"
              headerSlot={<NeuBadge tone="accent" variant="soft" size="sm">Sheet</NeuBadge>}
              footer={
                <NeuTouchActionBar
                  title="Mobile shell"
                  description="Primary actions stay near the thumb zone."
                  actions={<NeuButton size="sm" variant="soft-tonal">Open scanner</NeuButton>}
                />
              }
            />
          </div>
        </div>
      ),
    },
    NeuNavItem: {
      description: "Navigation items show the raised-versus-accent relationship that sells interaction at a glance.",
      content: (
        <div className="space-y-3">
          <NeuNavItem icon={LayoutDashboard} label="Dashboard" description="Overview workspace" active />
          <NeuNavItem icon={Radar} label="Scanner" description="Batch opportunity sweeps" />
          <NeuNavItem
            icon={MemoryStick}
            label="Memory"
            description="Decision archive"
            badge={<NeuBadge tone="warning" variant="soft" size="sm" count={2} dot>alerts</NeuBadge>}
          />
        </div>
      ),
    },
    NeuTopbar: {
      description: "Topbars compress without losing hierarchy because the title, section label, and status pill remain distinct.",
      content: (
        <NeuTopbar
          section="Audit sample"
          title="Condensed control frame"
          description="The topbar stays readable even when the content density rises."
          condensed
          statusPill={<NeuStatusPill label="Realtime" tone="success" animated />}
          toolbar={
            <NeuMarketStrip
              compact
              items={[
                { id: "build", label: "Build", value: "Live", detail: "preview store", tone: "success", icon: <ShieldCheck className="size-4" /> },
                { id: "alerts", label: "Alerts", value: "3", detail: "visible", tone: "warning", icon: <AlertTriangle className="size-4" /> },
              ]}
            />
          }
          actions={
            <div className="flex flex-wrap gap-2">
              <NeuButton size="sm" variant="secondary">
                Sync
              </NeuButton>
              <NeuButton size="sm" variant="soft-tonal">
                Export
              </NeuButton>
            </div>
          }
        />
      ),
    },
    NeuMarketStrip: {
      description: "Ticker metrics stay raised and pillowy while preserving strong value contrast for scanning.",
      content: (
        <NeuMarketStrip
          items={[
            { id: "btc", label: "BTC/USD", value: "$108,223", detail: "+2.9%", tone: "success", icon: <ChartCandlestick className="size-4" /> },
            { id: "eth", label: "ETH/USD", value: "$5,422", detail: "+1.4%", tone: "accent", icon: <ChartCandlestick className="size-4" /> },
            { id: "latency", label: "Latency", value: "42 ms", detail: "build worker", tone: "warning", icon: <Database className="size-4" /> },
            { id: "health", label: "Runtime", value: "Healthy", detail: "2 services live", tone: "success", icon: <ShieldCheck className="size-4" /> },
          ]}
        />
      ),
    },
    NeuMobileDock: {
      description: "Dock actions rely on inset off-states and accent selected states rather than flat pills.",
      content: (
        <div className="max-w-md">
          <NeuMobileDock
            activePath="/scanner"
            items={[
              { id: "home", label: "Home", icon: <LayoutDashboard className="size-4.5" />, href: "/" },
              { id: "analysis", label: "Analysis", icon: <Bot className="size-4.5" />, href: "/analysis/new" },
              { id: "scanner", label: "Scanner", icon: <Radar className="size-4.5" />, href: "/scanner", badge: <NeuBadge tone="warning" variant="soft" size="sm" count={2}>q</NeuBadge> },
              { id: "accounts", label: "Accounts", icon: <Wallet className="size-4.5" />, href: "/accounts", badge: <NeuBadge tone="danger" variant="ghost" size="sm" dot>risk</NeuBadge> },
            ]}
          />
        </div>
      ),
    },
    NeuCommandPalette: {
      description: "The palette stays floating and deeply raised; the trigger here opens the real overlay instance.",
      content: (
        <NeuSurface depth="inset" radius="md" padding="md" className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="space-y-1">
              <p className="text-sm font-semibold">Open the live palette</p>
              <p className="text-xs leading-6" style={{ color: "var(--neu-text-muted)" }}>
                Route names, template labels, and component keywords are all searchable.
              </p>
            </div>
            <NeuButton variant="secondary" onClick={() => dispatch(setCommandPaletteOpen(true))}>
              Open palette
            </NeuButton>
          </div>
          <div className="flex flex-wrap gap-2">
            <NeuBadge tone="accent" variant="soft">analysis</NeuBadge>
            <NeuBadge tone="neutral" variant="soft">scanner</NeuBadge>
            <NeuBadge tone="warning" variant="soft">history</NeuBadge>
          </div>
        </NeuSurface>
      ),
    },
    NeuAppearanceStudio: {
      description: "Theme, accent, and contrast controls are wired into the preview store so every sample updates live.",
      content: (
        <NeuAppearanceStudio
          theme={ui.mode}
          palette={ui.accent}
          contrast={ui.contrast}
          onThemeChange={(mode) => dispatch(setNeuMode(mode))}
          onPaletteChange={(accent) => dispatch(setNeuAccent(accent))}
          onContrastChange={(contrast) => dispatch(setNeuContrast(contrast))}
        />
      ),
    },
    NeuPageHeader: {
      description: "Overview headers use a larger depth shift, but the stats still sit inside the same soft material family.",
      content: (
        <NeuPageHeader
          eyebrow="Headers"
          title="System coverage overview"
          description="Use page headers for section-level framing where the route needs both context and action density."
          variant="overview"
          actions={
            <div className="flex flex-wrap gap-2">
              <NeuButton variant="secondary">
                <Download className="size-4" />
                Export
              </NeuButton>
              <NeuButton variant="soft-tonal">
                Compare
              </NeuButton>
            </div>
          }
          stats={topLevelMetrics.slice(0, 2)}
          meta={<NeuStatusPill label="Reviewed" tone="success" />}
        />
      ),
    },
    NeuEntityHeader: {
      description: "Entity headers tighten the hierarchy for object-specific routes while preserving status prominence.",
      content: (
        <NeuEntityHeader
          title="AAPL momentum cycle"
          subtitle="Critical trade orchestration surface"
          variant="critical"
          backTo={{ label: "Back to cycles", onBack: () => {} }}
          status={<NeuStatusPill label="Requires review" tone="danger" animated />}
          actions={
            <div className="flex flex-wrap gap-2">
              <NeuButton variant="secondary">
                Journal
              </NeuButton>
              <NeuButton variant="danger">
                Stop cycle
              </NeuButton>
            </div>
          }
          stats={[
            { label: "Confidence", value: "81%", tone: "accent", delta: "+5 pts", trend: "up" },
            { label: "Open trades", value: 3, tone: "warning", delta: "2 hedged", trend: "flat" },
            { label: "PnL", value: "+$1,142", tone: "success", delta: "today", trend: "up" },
            { label: "Risk", value: "$812", tone: "danger", delta: "above target", trend: "up" },
          ]}
        />
      ),
    },
    NeuStatCapsule: {
      description: "Compact statistics stay readable because tone is applied to values, not to the entire information density.",
      content: (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <NeuStatCapsule label="Win rate" value="63%" tone="success" delta="+4%" trend="up" />
          <NeuStatCapsule label="Sharpe" value="2.41" tone="accent" delta="+0.18" trend="up" />
          <NeuStatCapsule label="Drawdown" value="-4.2%" tone="danger" delta="stabilizing" trend="down" />
          <NeuStatCapsule label="Throughput" value="18 runs" tone="warning" delta="queue warm" trend="flat" />
        </div>
      ),
    },
    NeuStatusPill: {
      description: "Status pills combine a dot, tone, and optional pulse so state is never signaled by shadow alone.",
      content: (
        <div className="flex flex-wrap gap-2">
          <NeuStatusPill label="Neutral" tone="neutral" />
          <NeuStatusPill label="Running" tone="accent" animated />
          <NeuStatusPill label="Healthy" tone="success" />
          <NeuStatusPill label="Caution" tone="warning" />
          <NeuStatusPill label="Blocked" tone="danger" />
        </div>
      ),
    },
    NeuButton: {
      description: "Default, tonal, ghost, pressed, danger, and loading states all preserve tactile depth shifts.",
      content: (
        <div className="flex flex-wrap gap-3">
          <NeuButton variant="primary">Run analysis</NeuButton>
          <NeuButton variant="secondary">Secondary</NeuButton>
          <NeuButton variant="soft-tonal" pressed>
            Pressed
          </NeuButton>
          <NeuButton variant="ghost">Ghost</NeuButton>
          <NeuButton variant="danger">
            <AlertTriangle className="size-4" />
            Close all
          </NeuButton>
          <NeuButton variant="secondary" loading>
            Launching
          </NeuButton>
        </div>
      ),
    },
    NeuIconButton: {
      description: "Icon buttons use the same raised/accent/danger material treatment as the full buttons.",
      content: (
        <div className="flex flex-wrap gap-3">
          <NeuIconButton icon={<Search className="size-4" />} label="Search" />
          <NeuIconButton icon={<RefreshCcw className="size-4" />} label="Refresh" tone="accent" />
          <NeuIconButton icon={<PanelRight className="size-4" />} label="Open drawer" onClick={() => setDrawerOpen(true)} />
          <NeuIconButton icon={<AlertTriangle className="size-4" />} label="Delete" tone="danger" />
        </div>
      ),
    },
    NeuInput: {
      description: "Inputs stay inset and readable, with errors expressed by border tone rather than destroying the material.",
      content: (
        <div className="grid gap-4 xl:grid-cols-2">
          <NeuInput
            label="Search symbol"
            value={previewSearch}
            onChange={(event) => setPreviewSearch(event.target.value)}
            placeholder="Type a ticker or theme"
            leadingIcon={<Search className="size-4" />}
            trailing={<NeuBadge tone="accent" variant="soft">kbd</NeuBadge>}
            helperText="Inset field with assistive tag."
          />
          <NeuInput
            label="Risk limit"
            value="2.50%"
            onChange={() => {}}
            error="Outside approved band"
            helperText="This error state keeps the same geometry."
          />
        </div>
      ),
    },
    NeuTextArea: {
      description: "Long-form reasoning fields keep the same recessed treatment while scaling vertically.",
      content: (
        <NeuTextArea
          label="Strategy thesis"
          value={thesis}
          onChange={(event) => setThesis(event.target.value)}
          helperText="Use the textarea for notes, prompts, and policy rationale."
          rows={5}
        />
      ),
    },
    NeuSelect: {
      description: "Select menus inherit the inset trigger and raised menu stack, preserving the same light direction.",
      content: (
        <NeuSelect
          label="Provider"
          options={providerOptions}
          value={selectedProvider}
          onChange={setSelectedProvider}
          searchable
          helperText="Searchable grouped options."
        />
      ),
    },
    NeuMultiSelect: {
      description: "Selected tags stay softly raised while the choice list remains visibly inset below them.",
      content: (
        <NeuMultiSelect
          label="Analyst coverage"
          options={analystOptions}
          value={selectedAnalysts}
          onChange={setSelectedAnalysts}
          helperText="Blend multiple analyst passes for a run."
        />
      ),
    },
    NeuCombobox: {
      description: "Comboboxes are kept neutral and inset so async or free-form search stays legible.",
      content: (
        <NeuCombobox
          label="Primary symbol"
          options={["AAPL", "NVDA", "MSFT", "BTCUSD", "ETHUSD"]}
          value={comboValue}
          onChange={setComboValue}
          allowCustom
          helperText="Supports both search and direct entry."
        />
      ),
    },
    NeuToggleGroup: {
      description: "Toggle clusters use inset containers with clearly raised active chips so selection never feels ambiguous.",
      content: (
        <div className="space-y-4">
          <NeuToggleGroup
            label="Execution mode"
            value={executionMode}
            onChange={(value) => setExecutionMode(value as string)}
            options={[
              { value: "manual", label: "Manual" },
              { value: "assisted", label: "Assisted" },
              { value: "auto", label: "Auto" },
            ]}
          />
          <NeuToggleGroup
            label="Coverage mix"
            value={coverageMix}
            onChange={(value) => setCoverageMix(value as string[])}
            size="sm"
            options={[
              { value: "market", label: "Market" },
              { value: "news", label: "News" },
              { value: "fundamentals", label: "Fundamentals" },
            ]}
          />
        </div>
      ),
    },
    NeuTabs: {
      description: "Tabs use accent depth for the active state while leaving the rail itself tactile and subdued.",
      content: (
        <NeuTabs
          value={tabValue}
          onValueChange={setTabValue}
          variant="inset"
          items={[
            {
              value: "summary",
              label: "Summary",
              content: <NeuBanner tone="accent" title="Summary view" description="Primary insight digest lives in the active tab surface." />,
            },
            {
              value: "signals",
              label: "Signals",
              content: <NeuKpiGrid dense items={walletMetrics} columns="2-up" />,
            },
            {
              value: "risks",
              label: "Risks",
              content: <NeuProgressTrack value={68} max={100} tone="warning" segmented />,
            },
          ]}
        />
      ),
    },
    NeuCheckbox: {
      description: "Checkboxes need explicit labels and descriptive copy because shadows alone are never sufficient cues.",
      content: (
        <div className="grid gap-3 md:grid-cols-2">
          <NeuCheckbox
            label="Risk lock"
            checked={riskLocked}
            onCheckedChange={(checked) => setRiskLocked(checked === true)}
            description="Prevent strategy edits once the cycle goes live."
            accent="accent"
          />
          <NeuCheckbox
            label="Auto-trade safeguards"
            checked={notificationsEnabled}
            onCheckedChange={(checked) => setNotificationsEnabled(checked === true)}
            description="Enable automated exit rules (Success accent)."
            accent="success"
          />
          <NeuCheckbox
            label="Override margin checks"
            checked={switchWarning}
            onCheckedChange={(checked) => setSwitchWarning(checked === true)}
            description="Bypass critical margin verification (Warning accent)."
            accent="warning"
          />
          <NeuCheckbox
            label="Archived switch"
            checked={false}
            onCheckedChange={() => {}}
            description="Disabled specimen."
            disabled
          />
        </div>
      ),
    },
    NeuRadioGroup: {
      description: "Radio groups lean on the same raised-versus-accent contrast used elsewhere in the system.",
      content: (
        <div className="space-y-6">
          <NeuRadioGroup
            label="Time horizon (Default accent)"
            value={horizon}
            onChange={setHorizon}
            orientation="horizontal"
            options={[
              { value: "intraday", label: "Intraday", description: "Fast decision cycle" },
              { value: "swing", label: "Swing", description: "Multi-day hold" },
              { value: "position", label: "Position", description: "Longer thesis horizon" },
            ]}
          />
          <NeuRadioGroup
            label="Risk profile (Warning accent)"
            value={executionMode}
            onChange={setExecutionMode}
            orientation="horizontal"
            accent="warning"
            options={[
              { value: "assisted", label: "Conservative", description: "Low drawdown limit" },
              { value: "auto", label: "Aggressive", description: "Expanded volatility tolerance" },
            ]}
          />
        </div>
      ),
    },
    NeuSlider: {
      description: "Tracks stay inset while the active fill and thumb remain clearly raised and color-assisted.",
      content: (
        <div className="space-y-6">
          <NeuSlider
            label="Confidence threshold (Default accent)"
            value={confidenceValue}
            min={0}
            max={100}
            step={1}
            marks={[0, 25, 50, 75, 100]}
            onValueChange={(value) => setConfidenceValue(value as number)}
            accent="accent"
          />
          <NeuSlider
            label="Risk band (Warning accent)"
            value={riskRange}
            min={0}
            max={100}
            step={5}
            marks={[0, 50, 100]}
            onValueChange={(value) => setRiskRange(value as [number, number])}
            accent="warning"
          />
          <NeuSlider
            label="Target buffer (Success accent)"
            value={35}
            min={0}
            max={100}
            step={5}
            onValueChange={() => {}}
            accent="success"
          />
        </div>
      ),
    },
    NeuSwitch: {
      description: "Tactile sliding switches representing boolean selections, featuring recessed tracks and raised solid thumbs.",
      content: (
        <div className="grid gap-3 md:grid-cols-2">
          <NeuSwitch
            label="Live execution desk"
            checked={switchActive}
            onChange={setSwitchActive}
            description="Route orders to live liquidity streams (Default accent)."
            accent="accent"
          />
          <NeuSwitch
            label="Automated safety loops"
            checked={switchSuccess}
            onChange={setSwitchSuccess}
            description="Enable continuous heartbeats (Success accent)."
            accent="success"
          />
          <NeuSwitch
            label="Bypass circuit breakers"
            checked={switchWarning}
            onChange={setSwitchWarning}
            description="Allow trade executions during market stress (Warning accent)."
            accent="warning"
          />
          <NeuSwitch
            label="Simulated environment"
            checked={false}
            onChange={() => {}}
            description="Disabled toggle specimen."
            disabled
          />
        </div>
      ),
    },
    NeuDateField: {
      description: "Date inputs retain the inset form treatment while using the calendar icon for extra affordance.",
      content: (
        <NeuDateField
          label="Evaluation date"
          value={evaluationDate}
          onChange={setEvaluationDate}
          min="2026-01-01"
          max="2026-12-31"
        />
      ),
    },
    NeuModelPicker: {
      description: "Model pickers combine provider context, recents, and searchable model selection in one raised module.",
      content: (
        <NeuModelPicker
          label="Execution model"
          provider={selectedProvider}
          options={modelOptions}
          value={selectedModel}
          onChange={setSelectedModel}
          remote
          recents={["gpt-5", "gpt-5-mini"]}
        />
      ),
    },
    NeuAccountPicker: {
      description: "Account pickers use an inset list, a selected accent row, and an inclusion pill for group curation.",
      content: (
        <NeuAccountPicker
          accounts={pickerAccounts}
          selectedAccount={selectedAccount}
          onSelect={setSelectedAccount}
          onToggleInclusion={(accountId) =>
            setPickerAccounts((current) =>
              current.map((account) =>
                account.id === accountId
                  ? { ...account, included: !account.included }
                  : account,
              ),
            )
          }
        />
      ),
    },
    NeuCard: {
      description: "Cards are the default data vessel: raised, readable, and slightly more contrast-safe than decorative surfaces.",
      content: (
        <NeuCard
          title="Exposure snapshot"
          description="Cards in a trading workspace must keep text contrast high enough for fast scanning."
          actions={<NeuStatusPill label="Live" tone="success" />}
          footer={
            <>
              <span className="text-xs font-semibold" style={{ color: "var(--neu-text-muted)" }}>
                Updated 2 minutes ago
              </span>
              <NeuButton size="sm" variant="secondary">
                Details
              </NeuButton>
            </>
          }
        >
          <NeuKpiGrid dense columns="2-up" items={walletMetrics} />
        </NeuCard>
      ),
    },
    NeuBadge: {
      description: "Badges reserve solid treatment for high-emphasis states; soft and outline variants handle secondary labeling.",
      content: (
        <div className="flex flex-wrap gap-2">
          <NeuBadge tone="accent" variant="solid">Primary</NeuBadge>
          <NeuBadge tone="neutral" variant="soft">Neutral</NeuBadge>
          <NeuBadge tone="success" variant="soft">Healthy</NeuBadge>
          <NeuBadge tone="warning" variant="outline">Watch</NeuBadge>
          <NeuBadge tone="danger" variant="ghost">Risk</NeuBadge>
        </div>
      ),
    },
    NeuTable: {
      description: "Tables keep the chrome subdued so symbols, regimes, and actions read before the decoration.",
      content: (
        <NeuTable
          stickyHeader
          columns={[
            { id: "symbol", header: "Symbol", accessor: "symbol" },
            { id: "regime", header: "Regime", accessor: "regime" },
            {
              id: "score",
              header: "Score",
              align: "right",
              cell: (row: (typeof tableRows)[number]) => <span className="font-semibold">{row.score.toFixed(1)}</span>,
            },
            { id: "updatedAt", header: "Updated", accessor: "updatedAt", align: "right" },
          ]}
          rows={tableRows}
          rowKey={(row) => row.id}
          toolbar={<NeuButton size="sm" variant="secondary">Export CSV</NeuButton>}
          rowActions={() => (
            <div className="flex justify-end gap-2">
              <NeuButton size="sm" variant="ghost">
                View
              </NeuButton>
              <NeuButton size="sm" variant="soft-tonal">
                Trade
              </NeuButton>
            </div>
          )}
        />
      ),
    },
    NeuFilterBar: {
      description: "Filter bars act as a soft control shelf, not as a hard toolbar, so the page remains materially coherent.",
      content: (
        <NeuFilterBar
          sticky
          filters={filterChips}
          clearAll={() => setPreviewSearch("")}
          search={
            <NeuInput
              value={previewSearch}
              onChange={(event) => setPreviewSearch(event.target.value)}
              placeholder="Filter accounts"
              leadingIcon={<Search className="size-4" />}
            />
          }
          actions={
            <NeuButton size="sm" variant="secondary">
              <SlidersHorizontal className="size-4" />
              Advanced
            </NeuButton>
          }
        />
      ),
    },
    NeuEmptyState: {
      description: "Empty states use an accent icon capsule and restrained copy so the surface stays calm instead of loud.",
      content: (
        <NeuEmptyState
          icon={<Sparkles className="size-6" />}
          title="No archived studies yet"
          description="When a route is empty, the state still needs a tactile container, a clear title, and obvious next actions."
          primaryAction={<NeuButton variant="primary">Create study</NeuButton>}
          secondaryAction={<NeuButton variant="secondary">Import snapshot</NeuButton>}
        />
      ),
    },
    NeuSkeleton: {
      description: "Skeletons sit inside inset wells so loading never looks detached from the same material system.",
      content: (
        <div className="grid gap-3 md:grid-cols-2">
          <NeuSurface depth="inset" radius="md" padding="md">
            <NeuSkeleton shape="text" lines={4} />
          </NeuSurface>
          <NeuSkeleton shape="card" />
          <NeuSkeleton shape="chart" />
          <NeuSkeleton shape="table" />
        </div>
      ),
    },
    NeuPagination: {
      description: "Pagination keeps controls raised and status compact, which matters on dense archive and memory screens.",
      content: (
        <NeuPagination
          page={paginationPage}
          pageSize={pageSize}
          total={126}
          onPageChange={setPaginationPage}
          onPageSizeChange={setPageSize}
        />
      ),
    },
    NeuKpiGrid: {
      description: "KPI tiles lean on typography and tone before shadow, which keeps analytic dashboards readable.",
      content: <NeuKpiGrid items={topLevelMetrics} columns="4-up" />,
    },
    NeuTickerMetric: {
      description: "Ticker metrics are compact enough for strips but still read like distinct raised objects.",
      content: (
        <div className="flex flex-wrap gap-3">
          <NeuTickerMetric label="BTC/USD" value="$108,223" detail="+2.9%" tone="success" icon={<ChartCandlestick className="size-4" />} />
          <NeuTickerMetric label="Max DD" value="-4.2%" detail="30d" tone="danger" icon={<Activity className="size-4" />} />
          <NeuTickerMetric label="Queue" value="7 jobs" detail="warm" tone="warning" icon={<Database className="size-4" />} />
        </div>
      ),
    },
    NeuScoreBar: {
      description: "Score bars keep the track inset and use color only as a secondary cue for directionality.",
      content: (
        <div className="space-y-4">
          <NeuScoreBar score={7.8} scale={10} direction="buy" />
          <NeuScoreBar score={-5.2} scale={10} direction="sell" />
          <NeuScoreBar score={2.4} scale={10} direction="neutral" />
        </div>
      ),
    },
    NeuProgressTrack: {
      description: "Progress tracks support determinate, segmented, and indeterminate states inside the same inset rail.",
      content: (
        <div className="space-y-4">
          <NeuProgressTrack value={68} max={100} tone="accent" />
          <NeuProgressTrack value={41} max={100} tone="warning" segmented />
          <NeuProgressTrack value={32} max={100} tone="success" indeterminate />
        </div>
      ),
    },
    NeuChartCard: {
      description: "Charts stay readable by pushing the strongest neumorphic depth to the frame while keeping the plot well restrained.",
      content: (
        <NeuChartCard
          title="Portfolio curve"
          description="The chart body sits inside a subdued inset well instead of fighting the data."
          toolbar={
            <NeuChartToolbar
              period={chartPeriod}
              scope={chartScope}
              onPeriodChange={setChartPeriod}
              onScopeChange={setChartScope}
              actions={<NeuButton size="sm" variant="secondary">Compare</NeuButton>}
            />
          }
          legend={
            <>
              <NeuLegendChip
                label="Equity"
                color="var(--neu-accent)"
                active={activeLegends.includes("equity")}
                onToggle={() =>
                  setActiveLegends((current) =>
                    current.includes("equity")
                      ? current.filter((entry) => entry !== "equity")
                      : [...current, "equity"],
                  )
                }
              />
              <NeuLegendChip
                label="Benchmark"
                color="var(--neu-success)"
                active={activeLegends.includes("benchmark")}
                onToggle={() =>
                  setActiveLegends((current) =>
                    current.includes("benchmark")
                      ? current.filter((entry) => entry !== "benchmark")
                      : [...current, "benchmark"],
                  )
                }
              />
            </>
          }
          footer={
            <div className="flex w-full items-center justify-between gap-3">
              <span className="text-xs font-semibold" style={{ color: "var(--neu-text-muted)" }}>
                Updated from 4 live accounts
              </span>
              <NeuButton size="sm" variant="ghost">
                <ArrowUpRight className="size-4" />
                Open analytics
              </NeuButton>
            </div>
          }
        >
          <div className="flex h-full items-end gap-3">
            {[42, 56, 48, 70, 84, 92].map((bar, index) => (
              <div
                key={index}
                className="flex-1 rounded-t-[var(--neu-radius-sm)]"
                style={{
                  height: `${bar}%`,
                  background:
                    "linear-gradient(180deg, color-mix(in oklch, var(--neu-accent) 72%, white), var(--neu-accent))",
                  opacity: activeLegends.includes("equity") ? 1 : 0.3,
                }}
              />
            ))}
          </div>
        </NeuChartCard>
      ),
    },
    NeuChartToolbar: {
      description: "Toolbar groups remain softer than the chart frame so controls do not overpower the plot.",
      content: (
        <NeuChartToolbar
          period={chartPeriod}
          scope={chartScope}
          onPeriodChange={setChartPeriod}
          onScopeChange={setChartScope}
          actions={
            <div className="flex flex-wrap gap-2">
              <NeuButton size="sm" variant="secondary">
                <RefreshCcw className="size-4" />
                Refresh
              </NeuButton>
              <NeuButton size="sm" variant="soft-tonal">
                Save view
              </NeuButton>
            </div>
          }
          inline={false}
        />
      ),
    },
    NeuLegendChip: {
      description: "Legend chips toggle between raised and inset states instead of disappearing into flat chart chrome.",
      content: (
        <div className="flex flex-wrap gap-2">
          {[
            { id: "equity", label: "Equity", color: "var(--neu-accent)" },
            { id: "benchmark", label: "Benchmark", color: "var(--neu-success)" },
            { id: "drawdown", label: "Drawdown", color: "var(--neu-danger)" },
          ].map((legend) => (
            <NeuLegendChip
              key={legend.id}
              label={legend.label}
              color={legend.color}
              active={activeLegends.includes(legend.id)}
              onToggle={() =>
                setActiveLegends((current) =>
                  current.includes(legend.id)
                    ? current.filter((entry) => entry !== legend.id)
                    : [...current, legend.id],
                )
              }
            />
          ))}
        </div>
      ),
    },
    NeuDialog: {
      description: "Dialogs use a floating raised shell with enough contrast to avoid the typical washed-out soft UI failure.",
      content: (
        <NeuSurface depth="inset" radius="md" padding="md" className="space-y-3">
          <p className="text-sm font-semibold">Open the live dialog overlay</p>
          <p className="text-xs leading-6" style={{ color: "var(--neu-text-muted)" }}>
            The real overlay specimen can be opened here and from the topbar actions, including the mobile fullscreen treatment.
          </p>
          <NeuButton variant="secondary" onClick={() => setDialogOpen(true)}>
            Open dialog
          </NeuButton>
        </NeuSurface>
      ),
    },
    NeuDrawer: {
      description: "Drawers keep the same shadow direction as dialogs, but stretch into a side or bottom sheet.",
      content: (
        <div className="space-y-4">
          <NeuToggleGroup
            label="Drawer side"
            size="sm"
            value={drawerSide}
            onChange={(value) => setDrawerSide(value as "left" | "right" | "bottom")}
            options={[
              { value: "left", label: "Left" },
              { value: "right", label: "Right" },
              { value: "bottom", label: "Bottom" },
            ]}
          />
          <NeuButton variant="secondary" onClick={() => setDrawerOpen(true)}>
            Open drawer
          </NeuButton>
          <NeuBadge tone="accent" variant="soft" size="sm">
            Bottom drawers can expand into mobile-first sheets.
          </NeuBadge>
        </div>
      ),
    },
    NeuToast: {
      description: "Toasts float with a lighter raised shell and a tone dot, not with a flat system-style banner.",
      content: (
        <NeuToast
          title="Latency spike resolved"
          description="Queue pressure normalized after the worker recovered."
          tone="success"
          action={<NeuButton size="sm" variant="soft-tonal">View log</NeuButton>}
        />
      ),
    },
    NeuBanner: {
      description: "Banners use restrained color and a raised capsule marker so alerts read clearly without shouting.",
      content: (
        <div className="space-y-3">
          <NeuBanner tone="accent" title="Blueprint isolation" description="All samples remain in the isolated design-system module." />
          <NeuBanner tone="warning" title="Dense surfaces" description="Tables and charts keep higher text contrast than decorative cards." />
          <NeuBanner tone="danger" title="Risk threshold" description="Two accounts exceed the configured soft stop." />
        </div>
      ),
    },
    NeuReconnectionChip: {
      description: "Connection chips pair iconography and label text so state is readable even if color is missed.",
      content: (
        <div className="flex flex-wrap gap-3">
          <NeuReconnectionChip status="connected" />
          <NeuReconnectionChip status="reconnecting" attempt={2} onRetry={() => {}} />
          <NeuReconnectionChip status="offline" onRetry={() => {}} />
        </div>
      ),
    },
    NeuConfirmDialog: {
      description: "Confirm flows preserve the same overlay system while strengthening tone for high-risk actions.",
      content: (
        <NeuSurface depth="inset" radius="md" padding="md" className="space-y-3">
          <p className="text-sm font-semibold">Open the live confirm overlay</p>
          <NeuButton variant="danger" onClick={() => setConfirmOpen(true)}>
            Destructive confirm
          </NeuButton>
        </NeuSurface>
      ),
    },
    AnalysisLaunchWizard: {
      description: "Multi-step analysis launcher with inset rails, raised step buttons, and a summary column.",
      panelClassName: "overflow-hidden",
      content: (
        <AnalysisLaunchWizard
          initialValues={{ symbol: "AAPL", analysts: ["market", "news"] }}
          providers={providerOptions}
          models={modelOptions}
          symbols={["AAPL", "NVDA", "MSFT", "BTCUSD", "ETHUSD"]}
          watchlists={watchlistOptions}
          onSubmit={() => setDialogOpen(true)}
          onSaveDraft={() => setDialogOpen(true)}
        />
      ),
    },
    AnalysisRunConsole: {
      description: "Run console checks alternating message depths, stat capsules, reports, and websocket health.",
      panelClassName: "overflow-hidden",
      content: (
        <AnalysisRunConsole
          run={{ runId: "run_812", symbol: "NVDA", status: "running", duration: "04:12" }}
          agents={[
            { name: "Market analyst", status: "done", activity: "Trend and breadth complete" },
            { name: "News analyst", status: "running", activity: "Catalyst sweep in progress" },
            { name: "Risk analyst", status: "queued", activity: "Waiting on final signals" },
          ]}
          messages={[
            { sender: "System", content: "Run seeded with portfolio context and macro memory.", at: "08:41" },
            { sender: "Market analyst", content: "Momentum and participation remain aligned on the hourly frame.", at: "08:43" },
            { sender: "News analyst", content: "No fresh adverse filings or headline risk detected so far.", at: "08:44" },
          ]}
          reports={[
            { id: "brief", title: "Brief", body: "Short narrative summary of the current opportunity set." },
            { id: "risk", title: "Risk", body: "Risk budget remains acceptable if volatility compression continues." },
          ]}
          stats={[
            { label: "Confidence", value: "78%", tone: "accent" },
            { label: "Tokens", value: "58k", tone: "neutral" },
            { label: "Latency", value: "42 ms", tone: "success" },
          ]}
          wsState={{ status: "connected" }}
          configSummary={[
            { label: "Provider", value: "OpenAI" },
            { label: "Model", value: "GPT-5" },
            { label: "Risk mode", value: "Assisted" },
          ]}
        />
      ),
    },
    ScanWorkbench: {
      description: "Scanner workbench combines controls, active progress, result boards, and scheduling affordances.",
      panelClassName: "overflow-hidden",
      content: (
        <ScanWorkbench
          settings={
            <NeuPanel title="Scan controls" description="Universe, cadence, and analyst mix.">
              <div className="grid gap-3 md:grid-cols-2">
                <NeuSelect label="Universe" options={watchlistOptions} value="growth" onChange={() => {}} />
                <NeuToggleGroup
                  label="Cadence"
                  value="hourly"
                  onChange={() => {}}
                  options={[
                    { value: "hourly", label: "Hourly" },
                    { value: "daily", label: "Daily" },
                    { value: "manual", label: "Manual" },
                  ]}
                />
              </div>
            </NeuPanel>
          }
          activeScan={{ phase: "ranking", progress: 68, summary: "Ranking 38 symbols after analyst passes." }}
          results={{
            buy: [
              { symbol: "AAPL", score: 8.5, runId: "r_aapl" },
              { symbol: "NVDA", score: 8.2, runId: "r_nvda" },
            ],
            sell: [{ symbol: "TSLA", score: -7.4, runId: "r_tsla" }],
            hold: [{ symbol: "MSFT", score: 3.1, runId: "r_msft" }],
          }}
          filters={templateToolbar}
          onStart={() => {}}
          onCancel={() => {}}
          onSchedule={() => setDrawerOpen(true)}
        />
      ),
    },
    ScanResultsBoard: {
      description: "Actionable scan groups use tone-specific headers but keep row density clean and high contrast.",
      panelClassName: "overflow-hidden",
      content: (
        <ScanResultsBoard
          buy={[
            { symbol: "AAPL", score: 8.5, runId: "r_aapl" },
            { symbol: "NVDA", score: 8.2, runId: "r_nvda" },
          ]}
          sell={[{ symbol: "TSLA", score: -7.4, runId: "r_tsla" }]}
          hold={[{ symbol: "MSFT", score: 3.1, runId: "r_msft" }]}
          filters={templateToolbar}
          onTrade={() => {}}
          onViewAnalysis={() => setDialogOpen(true)}
        />
      ),
    },
    AccountsGrid: {
      description: "Account cards use soft raised shells, status pills, and clear equity/PnL emphasis.",
      panelClassName: "overflow-hidden",
      content: (
        <AccountsGrid
          filter={accountFilter}
          onFilterChange={setAccountFilter}
          onAdd={() => setDrawerOpen(true)}
          onResetDemo={() => setConfirmOpen(true)}
          onCloseAll={() => setConfirmOpen(true)}
          accounts={[
            { id: "acc-1", label: "Bybit Demo 01", type: "demo", equity: "$25,000", pnl: "+$482", positions: 5 },
            { id: "acc-2", label: "Live Futures", type: "live", equity: "$78,114", pnl: "-$91", positions: 2 },
            { id: "acc-3", label: "Options Sandbox", type: "demo", equity: "$14,220", pnl: "+$41", positions: 1 },
          ]}
        />
      ),
    },
    AccountSummaryHero: {
      description: "Entity hero for a single account with summary metrics and action affordances.",
      panelClassName: "overflow-hidden",
      content: (
        <AccountSummaryHero
          account={{ label: "Prime Futures", type: "live", status: "live" }}
          wallet={walletMetrics}
          pnl={pnlMetrics}
          actions={
            <div className="flex flex-wrap gap-2">
              <NeuButton variant="secondary">Reconcile</NeuButton>
              <NeuButton variant="soft-tonal">Transfer</NeuButton>
            </div>
          }
        />
      ),
    },
    TradeDeskWorkspace: {
      description: "Trade desk uses tabs, reconnection state, stats, and dense tables without breaking the material language.",
      panelClassName: "overflow-hidden",
      content: (
        <TradeDeskWorkspace
          activeTrades={tradeRows.filter((trade) => trade.status === "Open")}
          historyTrades={tradeRows}
          filters={templateToolbar}
          stats={[
            { label: "Open trades", value: 2, tone: "accent" },
            { label: "Gross exposure", value: "$41k", tone: "warning" },
            { label: "Realized", value: "+$214", tone: "success" },
          ]}
          wsConnected
          onCloseTrade={() => setConfirmOpen(true)}
          onCloseAll={() => setConfirmOpen(true)}
        />
      ),
    },
    StrategyLibraryBoard: {
      description: "Strategy cards keep category/status signaling soft enough to stay cohesive with the rest of the system.",
      panelClassName: "overflow-hidden",
      content: (
        <StrategyLibraryBoard
          strategies={[
            { id: "s-1", name: "Momentum swing", category: "Swing", status: "active", description: "Multi-factor swing strategy with catalyst filters." },
            { id: "s-2", name: "Mean reversion", category: "Intraday", status: "draft", description: "Short-horizon volatility compression strategy." },
            { id: "s-3", name: "Funding arb", category: "Crypto", status: "active", description: "Perpetual funding dispersion capture." },
          ]}
          filters={templateToolbar}
          search={
            <NeuInput
              value={previewSearch}
              onChange={(event) => setPreviewSearch(event.target.value)}
              placeholder="Search strategies"
              leadingIcon={<Search className="size-4" />}
            />
          }
          onCreate={() => setDrawerOpen(true)}
          onDelete={() => setConfirmOpen(true)}
          onImport={() => setDialogOpen(true)}
          onExport={() => setDialogOpen(true)}
        />
      ),
    },
    CycleBoard: {
      description: "Cycle list-detail board calls attention to the selected cycle without over-accenting the whole screen.",
      panelClassName: "overflow-hidden",
      content: (
        <CycleBoard
          selectedCycle="cycle-2"
          cycles={[
            { id: "cycle-1", label: "AAPL opening drive", status: "running", trades: 2, symbol: "AAPL" },
            { id: "cycle-2", label: "ETH funding squeeze", status: "focused", trades: 1, symbol: "ETHUSD" },
            { id: "cycle-3", label: "NVDA trend follow", status: "complete", trades: 4, symbol: "NVDA" },
          ]}
          onRefresh={() => {}}
          onStop={() => setConfirmOpen(true)}
        />
      ),
    },
    ConfigInspector: {
      description: "Inspector route keeps secret masking, override emphasis, and appearance tuning in a readable hierarchy.",
      panelClassName: "overflow-hidden",
      content: (
        <ConfigInspector
          resolved={[
            { key: "OPENAI_API_KEY", value: "sk-live-123" },
            { key: "EXECUTION_MODE", value: executionMode },
            { key: "SCAN_UNIVERSE", value: "growth" },
          ]}
          overrides={[
            { key: "RISK_LOCK", value: String(riskLocked) },
            { key: "MODEL_PROVIDER", value: selectedProvider },
          ]}
          maskedKeys={["OPENAI_API_KEY"]}
          appearance={
            <NeuAppearanceStudio
              theme={ui.mode}
              palette={ui.accent}
              contrast={ui.contrast}
              compact
              onThemeChange={(mode) => dispatch(setNeuMode(mode))}
              onPaletteChange={(accent) => dispatch(setNeuAccent(accent))}
              onContrastChange={(contrast) => dispatch(setNeuContrast(contrast))}
            />
          }
        />
      ),
    },
    MemoryRecordList: {
      description: "Archive-grade list with paginated records, confidence states, and a table index layout.",
      panelClassName: "overflow-hidden",
      content: (
        <MemoryRecordList
          page={paginationPage}
          total={48}
          onPageChange={setPaginationPage}
          items={[
            { id: "m-1", summary: "Raised table contrast for the graphite theme.", confidence: "High", status: "accepted", createdAt: "2026-05-20" },
            { id: "m-2", summary: "Reduced accent usage on strategy chips.", confidence: "Medium", status: "review", createdAt: "2026-05-19" },
            { id: "m-3", summary: "Aligned shell icon capsules to the top-left light source.", confidence: "High", status: "accepted", createdAt: "2026-05-18" },
          ]}
        />
      ),
    },
    NeuOverviewTemplate: {
      description: "Overview scaffold for dashboards with hero metrics, primary modules, secondary content, and an aside rail.",
      panelClassName: "overflow-hidden",
      content: (
        <NeuOverviewTemplate
          header={
            <TemplatePreviewHeader
              eyebrow="Overview template"
              title="Macro route scaffold"
              description="The overview frame gives primary canvas ownership to dense widgets while keeping an aside rail for supporting context."
            />
          }
          hero={templateSummary}
          primary={
            <div className="grid gap-4 xl:grid-cols-2">
              <PlaceholderCard title="Performance digest" eyebrow="Primary" />
              <PlaceholderCard title="Opportunity queue" eyebrow="Primary" />
            </div>
          }
          secondary={
            <div className="grid gap-4 xl:grid-cols-2">
              <PlaceholderCard title="Scanner radar" eyebrow="Secondary" />
              <PlaceholderCard title="PnL bridge" eyebrow="Secondary" />
            </div>
          }
          activity={<PlaceholderCard title="Recent activity" eyebrow="Activity" detail="Cross-route recent events." />}
          aside={
            <div className="space-y-4">
              <PlaceholderCard title="Alerts" eyebrow="Aside" />
              <PlaceholderCard title="Run health" eyebrow="Aside" />
            </div>
          }
        />
      ),
    },
    NeuWizardTemplate: {
      description: "Wizard scaffold with a dedicated step rail, content center, summary rail, and footer slot.",
      panelClassName: "overflow-hidden",
      content: (
        <NeuWizardTemplate
          header={
            <TemplatePreviewHeader
              eyebrow="Wizard template"
              title="Launch flow scaffold"
              description="The wizard template intentionally pushes navigation into an inset side rail and keeps the work surface raised."
            />
          }
          stepRail={
            <div className="space-y-3">
              <NeuStatusPill label="Step 1" tone="accent" />
              <PlaceholderCard title="Universe" />
              <PlaceholderCard title="Analysts" />
              <PlaceholderCard title="Review" />
            </div>
          }
          content={<PlaceholderCard title="Main step content" detail="Large working zone with fields and grouped decisions." />}
          summary={<PlaceholderCard title="Summary rail" detail="Tight recap of the currently selected values." />}
          footer={
            <div className="flex flex-wrap justify-end gap-2">
              <NeuButton variant="secondary">Back</NeuButton>
              <NeuButton variant="soft-tonal">Save draft</NeuButton>
              <NeuButton variant="primary">Continue</NeuButton>
            </div>
          }
        />
      ),
    },
    NeuConsoleTemplate: {
      description: "Console scaffold for runtime status, split primary/secondary panes, and report outputs beneath.",
      panelClassName: "overflow-hidden",
      content: (
        <NeuConsoleTemplate
          header={
            <TemplatePreviewHeader
              eyebrow="Console template"
              title="Runtime orchestration scaffold"
              description="Useful when an active process needs streaming updates, side context, and final report sections."
            />
          }
          status={<NeuBanner tone="accent" title="Run active" description="All analysts are currently connected to the stream." />}
          stats={templateSummary}
          primary={<PlaceholderCard title="Primary stream" detail="Messages, progress, and execution state." />}
          secondary={<PlaceholderCard title="Secondary context" detail="Agent roster, configuration, or logs." />}
          reports={<PlaceholderCard title="Reports stack" detail="Rendered markdown, tables, or exports." />}
        />
      ),
    },
    NeuArchiveTemplate: {
      description: "Archive scaffold with filters, bulk actions, indexed results, and pagination.",
      panelClassName: "overflow-hidden",
      content: (
        <NeuArchiveTemplate
          header={
            <TemplatePreviewHeader
              eyebrow="Archive template"
              title="Archive route scaffold"
              description="Use this scaffold when the page is primarily a browsable historical index."
            />
          }
          filters={templateToolbar}
          bulkActions={<PlaceholderCard title="Bulk actions" detail="Delete, restore, export, and tagging controls." />}
          results={<PlaceholderCard title="Results list" detail="Archive cards or table output." />}
          pagination={<NeuPagination page={2} pageSize={25} total={126} onPageChange={() => {}} />}
        />
      ),
    },
    NeuWorkbenchTemplate: {
      description: "Workbench scaffold for tools that need controls, results, and a strongly separated aside column.",
      panelClassName: "overflow-hidden",
      content: (
        <NeuWorkbenchTemplate
          header={
            <TemplatePreviewHeader
              eyebrow="Workbench template"
              title="Scanner workbench scaffold"
              description="This structure suits tools that alternate between setup, progress, and result review."
            />
          }
          controls={<PlaceholderCard title="Control shelf" detail="Universe, cadence, model, and scan toggles." />}
          secondaryActions={<PlaceholderCard title="Secondary actions" detail="Schedule, clone, and compare actions." />}
          results={<PlaceholderCard title="Result canvas" detail="Ranked opportunities, charts, or tables." />}
          aside={<PlaceholderCard title="Aside utilities" detail="Schedule health, jobs, and recent runs." />}
        />
      ),
    },
    NeuPortfolioGridTemplate: {
      description: "Portfolio scaffold with filters, statistics, a main account grid, and supporting aside content.",
      panelClassName: "overflow-hidden",
      content: (
        <NeuPortfolioGridTemplate
          header={
            <TemplatePreviewHeader
              eyebrow="Portfolio grid template"
              title="Portfolio route scaffold"
              description="The main grid stays dominant while filters and side context remain supportive."
            />
          }
          filters={templateToolbar}
          stats={templateSummary}
          grid={
            <div className="grid gap-4 xl:grid-cols-2">
              <PlaceholderCard title="Account card A" />
              <PlaceholderCard title="Account card B" />
            </div>
          }
          aside={<PlaceholderCard title="Portfolio aside" detail="Connection state, balances, and quick actions." />}
        />
      ),
    },
    NeuEntityDetailTemplate: {
      description: "Entity detail scaffold combines summary, tabs, main content, and a secondary insight rail.",
      panelClassName: "overflow-hidden",
      content: (
        <NeuEntityDetailTemplate
          header={
            <TemplatePreviewHeader
              eyebrow="Entity detail template"
              title="Entity detail scaffold"
              description="Best when a single run, cycle, or account needs a list-detail style layout."
            />
          }
          summary={templateSummary}
          tabs={
            <NeuTabs
              value="summary"
              onValueChange={() => {}}
              items={[
                { value: "summary", label: "Summary", content: null },
                { value: "history", label: "History", content: null },
                { value: "settings", label: "Settings", content: null },
              ]}
            />
          }
          content={<PlaceholderCard title="Detail content" detail="Primary analysis, positions, or logs." />}
          aside={<PlaceholderCard title="Detail aside" detail="Related actions and secondary stats." />}
        />
      ),
    },
    NeuAnalyticsTemplate: {
      description: "Analytics scaffold keeps controls and KPI shelves above the main chart body with an optional right rail.",
      panelClassName: "overflow-hidden",
      content: (
        <NeuAnalyticsTemplate
          header={
            <TemplatePreviewHeader
              eyebrow="Analytics template"
              title="Analytics route scaffold"
              description="This frame keeps the chart body central while surrounding controls stay softer."
            />
          }
          controls={templateToolbar}
          kpis={templateSummary}
          charts={
            <div className="grid gap-4 xl:grid-cols-2">
              <PlaceholderCard title="Equity curve" detail="Primary analytic chart." />
              <PlaceholderCard title="Drawdown heatmap" detail="Secondary analytic chart." />
            </div>
          }
          aside={<PlaceholderCard title="Insight rail" detail="Benchmarks, notes, or anomaly flags." />}
          footerActions={
            <div className="flex flex-wrap justify-end gap-2">
              <NeuButton variant="secondary">Export PNG</NeuButton>
              <NeuButton variant="soft-tonal">Share link</NeuButton>
            </div>
          }
        />
      ),
    },
    NeuLibraryTemplate: {
      description: "Library scaffold is tuned for grid-heavy strategy or preset collections plus modal slots.",
      panelClassName: "overflow-hidden",
      content: (
        <NeuLibraryTemplate
          header={
            <TemplatePreviewHeader
              eyebrow="Library template"
              title="Library route scaffold"
              description="This layout supports search, filters, card grids, and inline dialog slots."
            />
          }
          filters={templateToolbar}
          grid={
            <div className="grid gap-4 xl:grid-cols-3">
              <PlaceholderCard title="Collection card A" />
              <PlaceholderCard title="Collection card B" />
              <PlaceholderCard title="Collection card C" />
            </div>
          }
          dialogSlot={<PlaceholderCard title="Dialog slot" detail="Optional create/edit overlay insertion point." />}
        />
      ),
    },
    NeuTableIndexTemplate: {
      description: "Table index scaffold is optimized for records-first screens that still need context and side notes.",
      panelClassName: "overflow-hidden",
      content: (
        <NeuTableIndexTemplate
          header={
            <TemplatePreviewHeader
              eyebrow="Table index template"
              title="Index route scaffold"
              description="Use this when the route is fundamentally a table with a supporting note rail."
            />
          }
          toolbar={templateToolbar}
          table={<PlaceholderCard title="Index table" detail="Primary list output with sorting and actions." />}
          pagination={<NeuPagination page={3} pageSize={25} total={240} onPageChange={() => {}} compact />}
          aside={<PlaceholderCard title="Index aside" detail="Saved filters, notes, and secondary context." />}
        />
      ),
    },
    NeuInspectorTemplate: {
      description: "Inspector scaffold works for configuration, environment state, and detail-rich operational notes.",
      panelClassName: "overflow-hidden",
      content: (
        <NeuInspectorTemplate
          header={
            <TemplatePreviewHeader
              eyebrow="Inspector template"
              title="Inspector route scaffold"
              description="The inspector layout keeps control bands above the main detail canvas."
            />
          }
          controls={templateToolbar}
          inspector={<PlaceholderCard title="Inspector canvas" detail="Resolved values, overrides, and metadata." />}
          notes={<PlaceholderCard title="Notes" detail="Operational caveats and review markers." />}
          aside={<PlaceholderCard title="Inspector aside" detail="Appearance controls or related context." />}
        />
      ),
    },
  };

  const checklistEntries = Object.entries(neumorphismComponentChecklist) as unknown as Array<
    [ChecklistSection, readonly AuditComponentName[]]
  >;

  return (
    <NeuThemeScope mode={ui.mode} accent={ui.accent} contrast={ui.contrast} className="min-h-screen p-4 md:p-5">
      <NeuAppShell
        sidebar={<NeuSidebar sections={[...shellSections]} activePath="/" />}
        topbar={
          <div className="space-y-4">
            <NeuTopbar
              section="Neumorphism preview"
            title="TradingAgents design system review surface"
              description="Every registered design-system component and route structure model is rendered on this page so the neumorphic fit can be judged in one place before route migration."
              statusPill={<NeuStatusPill label="Third iteration audit" tone="accent" animated />}
              actions={
                <div className="flex flex-wrap gap-2">
                  <NeuButton variant="secondary" onClick={() => dispatch(setCommandPaletteOpen(true))}>
                    Open palette
                  </NeuButton>
                  <NeuButton variant="secondary" onClick={() => setDrawerOpen(true)}>
                    Open drawer
                  </NeuButton>
                  <NeuButton variant="soft-tonal" onClick={() => setDialogOpen(true)}>
                    Preview dialog
                  </NeuButton>
                  <NeuButton variant="danger" onClick={() => setConfirmOpen(true)}>
                    Confirm dialog
                  </NeuButton>
                </div>
              }
            />
            <NeuMarketStrip
              items={[
                { id: "btc", label: "BTC/USD", value: "$108,223", detail: "+2.9%", tone: "success", icon: <ChartCandlestick className="size-4" /> },
                { id: "latency", label: "Latency", value: "42 ms", detail: "build worker", tone: "accent", icon: <Database className="size-4" /> },
                { id: "runtime", label: "Runtime", value: "Connected", detail: "streaming", tone: "success", icon: <BriefcaseBusiness className="size-4" /> },
                { id: "focus", label: "Audit", value: `${totalComponents}/${totalComponents}`, detail: "components mounted", tone: "warning", icon: <Workflow className="size-4" /> },
              ]}
            />
          </div>
        }
        dock={
          <NeuMobileDock
            activePath="/"
            items={[
              { id: "overview", label: "Home", icon: <LayoutDashboard className="size-4.5" />, href: "/" },
              { id: "analysis", label: "Analysis", icon: <Bot className="size-4.5" />, href: "/analysis/new" },
              { id: "scanner", label: "Scanner", icon: <Radar className="size-4.5" />, href: "/scanner", badge: <NeuBadge tone="warning" variant="soft" size="sm" count={2}>q</NeuBadge> },
              { id: "accounts", label: "Accounts", icon: <Wallet className="size-4.5" />, href: "/accounts", badge: <NeuBadge tone="danger" variant="ghost" size="sm" dot>risk</NeuBadge> },
            ]}
          />
        }
      >
        <div className="space-y-6">
          <NeuPageHeader
            eyebrow="Audit overview"
            title="Checklist-driven neumorphism review"
            description="This surface now audits foundations, structure, shell, headers, inputs, display, charts, overlays, composites, and templates from the same token model."
            actions={
              <div className="flex flex-wrap gap-2">
                <NeuButton variant="secondary" onClick={() => document.getElementById("audit-structure")?.scrollIntoView({ behavior: "smooth" })}>
                  Structure
                </NeuButton>
                <NeuButton variant="secondary" onClick={() => document.getElementById("audit-inputs")?.scrollIntoView({ behavior: "smooth" })}>
                  Inputs
                </NeuButton>
                <NeuButton variant="secondary" onClick={() => document.getElementById("audit-composites")?.scrollIntoView({ behavior: "smooth" })}>
                  Composites
                </NeuButton>
                <NeuButton variant="soft-tonal" onClick={() => document.getElementById("audit-templates")?.scrollIntoView({ behavior: "smooth" })}>
                  Templates
                </NeuButton>
              </div>
            }
            stats={topLevelMetrics}
            variant="overview"
            meta={
              <NeuBanner
                tone="accent"
                title="Audit rule"
                description="The preview is the contract: if a registered component is missing here, the system is incomplete."
              />
            }
          />

          <NeuSurface depth="flat" radius="lg" padding="lg" className="space-y-4">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
              <div className="space-y-1">
                <p className="text-base font-semibold tracking-[-0.02em]">Section navigation</p>
                <p className="text-sm leading-6" style={{ color: "var(--neu-text-muted)" }}>
                  Each link jumps to a section rendered directly from the component checklist.
                </p>
              </div>
              <NeuStatusPill label={`${totalComponents} audited components`} tone="success" />
            </div>
            <div className="flex flex-wrap gap-2">
              {checklistEntries.map(([section, names]) => (
                <a key={section} href={`#audit-${section}`}>
                  <NeuBadge tone={section === "composites" || section === "templates" ? "warning" : "accent"} variant="soft">
                    {sectionMeta[section].title} {names.length}
                  </NeuBadge>
                </a>
              ))}
            </div>
          </NeuSurface>

          <NeuBanner
            tone="warning"
            title="Dense-surface rule"
            description="For tables, charts, and inspectors, the neumorphism is intentionally restrained so data contrast and action clarity stay ahead of decoration."
          />

          {checklistEntries.map(([section, names]) => (
            <AuditSection key={section} section={section} count={names.length}>
              {names.map((name) => (
                <AuditCard key={name} name={name} sample={auditSamples[name]} />
              ))}
            </AuditSection>
          ))}
        </div>

        <NeuCommandPalette
          open={ui.commandPaletteOpen}
          query={commandQuery}
          onQueryChange={setCommandQuery}
          onOpenChange={(open) => dispatch(setCommandPaletteOpen(open))}
          onSelect={() => dispatch(setCommandPaletteOpen(false))}
          groups={commandGroups}
        />

        <NeuDialog
          open={dialogOpen}
          onOpenChange={setDialogOpen}
          title="Preview dialog"
          description="This overlay verifies the floating shell, readable copy contrast, and action spacing."
          size="lg"
          mobileFullscreen
          footer={
            <div className="flex w-full justify-end">
              <NeuButton onClick={() => setDialogOpen(false)}>Close</NeuButton>
            </div>
          }
        >
          <NeuBanner
            tone="success"
            title="Overlay system ready"
            description="Dialog chrome uses a stronger raised treatment than the base page so it lifts clearly from the background."
          />
          <NeuWell padding="sm">
            <p className="text-sm leading-7" style={{ color: "var(--neu-text-muted)" }}>
              This is a live overlay specimen used by the audit cards above.
            </p>
          </NeuWell>
        </NeuDialog>

        <NeuDrawer
          open={drawerOpen}
          onOpenChange={setDrawerOpen}
          title="Drawer preview"
          description="Use drawers for layered workflows that still need persistent context."
          side={drawerSide}
          size={drawerSide === "bottom" ? "full" : "lg"}
          footer={
            <NeuTouchActionBar
              title="Drawer actions"
              description="The footer stays fixed inside the drawer on mobile."
              actions={
                <>
                  <NeuButton size="sm" variant="secondary">Dismiss</NeuButton>
                  <NeuButton size="sm" variant="soft-tonal">Apply</NeuButton>
                </>
              }
            />
          }
        >
          <div className="space-y-4">
            <NeuBanner tone="accent" title="Drawer content" description="This specimen validates the side and bottom sheet geometry." />
            <NeuPanel title="Quick actions" description="Keep stacked actions soft and readable.">
              <div className="flex flex-wrap gap-2">
                <NeuButton variant="secondary">Clone run</NeuButton>
                <NeuButton variant="soft-tonal">Schedule scan</NeuButton>
                <NeuButton variant="danger">Delete draft</NeuButton>
              </div>
            </NeuPanel>
          </div>
        </NeuDrawer>

        <NeuConfirmDialog
          open={confirmOpen}
          onCancel={() => setConfirmOpen(false)}
          onConfirm={() => setConfirmOpen(false)}
          title="Destructive preview"
          body="This confirm dialog is the isolated reusable shell for high-risk actions such as close-all, reset, and delete flows."
        />
      </NeuAppShell>
    </NeuThemeScope>
  );
}

export function TradingAgentsNeumorphismPreview() {
  const store = useMemo(() => createNeuPreviewStore(), []);

  return (
    <Provider store={store}>
      <PreviewWorkspace />
    </Provider>
  );
}
