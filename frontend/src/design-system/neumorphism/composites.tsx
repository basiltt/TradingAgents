import { useState, type ReactNode } from "react";
import {
  Bot,
  BriefcaseBusiness,
  MemoryStick,
  Play,
  Radar,
  RefreshCcw,
  Save,
} from "lucide-react";
import {
  NeuBadge,
  NeuCard,
  NeuEmptyState,
  NeuFilterBar,
  NeuKpiGrid,
  NeuPagination,
  NeuProgressTrack,
  NeuScoreBar,
  NeuTable,
} from "./display";
import { NeuSurface, NeuWell } from "./foundation";
import { NeuEntityHeader, NeuPageHeader, NeuStatusPill } from "./headers";
import {
  NeuButton,
  NeuCombobox,
  NeuInput,
  NeuModelPicker,
  NeuMultiSelect,
  NeuSelect,
  NeuTabs,
  NeuToggleGroup,
} from "./inputs";
import { NeuBanner, NeuReconnectionChip } from "./overlays";
import {
  NeuEntityDetailTemplate,
  NeuInspectorTemplate,
  NeuLibraryTemplate,
  NeuTableIndexTemplate,
  NeuWizardTemplate,
  NeuWorkbenchTemplate,
} from "./templates";
import { cn } from "@/lib/utils";
import type { NeuMetric, NeuOption } from "./types";

export interface AnalysisLaunchWizardValues {
  assetType: "stock" | "crypto";
  symbol: string;
  provider: string;
  deepModel: string;
  quickModel: string;
  analysts: string[];
  workflowMode: "quick_trade" | "deep_analysis";
  backendEndpoint: string;
  outputLanguage: string;
  watchlists: string[];
}

export function AnalysisLaunchWizard({
  initialValues,
  providers,
  models,
  symbols,
  watchlists,
  onSubmit,
  onSaveDraft,
}: {
  initialValues: Partial<AnalysisLaunchWizardValues>;
  providers: NeuOption[];
  models: NeuOption[];
  symbols: string[];
  watchlists: NeuOption[];
  onSubmit: (values: AnalysisLaunchWizardValues) => void;
  onSaveDraft?: (values: AnalysisLaunchWizardValues) => void;
}) {
  const [step, setStep] = useState(1);
  const [values, setValues] = useState<AnalysisLaunchWizardValues>({
    assetType: initialValues.assetType ?? "stock",
    symbol: initialValues.symbol ?? "",
    provider: initialValues.provider ?? providers[0]?.value ?? "openai",
    deepModel: initialValues.deepModel ?? models[0]?.value ?? "",
    quickModel: initialValues.quickModel ?? models[1]?.value ?? models[0]?.value ?? "",
    analysts: initialValues.analysts ?? [],
    workflowMode: initialValues.workflowMode ?? "deep_analysis",
    backendEndpoint: initialValues.backendEndpoint ?? "http://localhost:8000",
    outputLanguage: initialValues.outputLanguage ?? "English",
    watchlists: initialValues.watchlists ?? [],
  });

  return (
    <NeuWizardTemplate
      header={
        <NeuPageHeader
          eyebrow="Research launch"
          title="Analysis launch wizard"
          description="A route-ready wizard shell for the TradingAgents analysis flow with tactile segmentation, provider selection, and draft persistence."
          variant="overview"
        />
      }
      stepRail={
        <div className="space-y-3">
          {[
            { id: 1, title: "Asset + symbol", icon: Radar },
            { id: 2, title: "Models + analysts", icon: Bot },
            { id: 3, title: "Execution + output", icon: BriefcaseBusiness },
          ].map((item) => {
            const active = step === item.id;
            const Icon = item.icon;
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => setStep(item.id)}
                className={cn(
                  "neu-focus-ring flex w-full items-center gap-3 rounded-[var(--neu-radius-md)] px-3 py-3 text-left transition",
                  active
                    ? "neu-surface-base neu-surface-accent shadow-[var(--neu-shadow-pill)]"
                    : "neu-surface-base neu-surface-raised neu-interactive",
                )}
              >
                <span
                  className={cn(
                    "inline-flex size-10 items-center justify-center rounded-[var(--neu-radius-sm)]",
                    active
                      ? "neu-surface-base neu-surface-raised shadow-[var(--neu-shadow-pill)]"
                      : "neu-surface-base neu-surface-inset",
                  )}
                >
                  <Icon className="size-4.5" />
                </span>
                <span className="text-sm font-semibold">{item.title}</span>
              </button>
            );
          })}
        </div>
      }
      content={
        <div className="space-y-4">
          {step === 1 ? (
            <>
              <NeuToggleGroup
                label="Asset type"
                value={values.assetType}
                onChange={(next) => setValues((current) => ({ ...current, assetType: next as "stock" | "crypto" }))}
                options={[
                  { value: "stock", label: "Stock" },
                  { value: "crypto", label: "Crypto" },
                ]}
              />
              <NeuCombobox
                label="Ticker or symbol"
                options={symbols}
                value={values.symbol}
                onChange={(symbol) => setValues((current) => ({ ...current, symbol }))}
                allowCustom
                helperText="Supports exchange symbols, watchlist pulls, and custom typed values."
              />
              <NeuMultiSelect
                label="Watchlists"
                options={watchlists}
                value={values.watchlists}
                onChange={(next) => setValues((current) => ({ ...current, watchlists: next }))}
              />
            </>
          ) : null}

          {step === 2 ? (
            <>
              <NeuSelect
                label="Provider"
                options={providers}
                value={values.provider}
                onChange={(provider) => setValues((current) => ({ ...current, provider }))}
              />
              <div className="grid gap-4 lg:grid-cols-2">
                <NeuModelPicker
                  label="Deep reasoning model"
                  provider={values.provider}
                  options={models}
                  value={values.deepModel}
                  onChange={(deepModel) => setValues((current) => ({ ...current, deepModel }))}
                  recents={models.slice(0, 2).map((model) => model.value)}
                />
                <NeuModelPicker
                  label="Quick synthesis model"
                  provider={values.provider}
                  options={models}
                  value={values.quickModel}
                  onChange={(quickModel) => setValues((current) => ({ ...current, quickModel }))}
                  recents={models.slice(2, 4).map((model) => model.value)}
                />
              </div>
              <NeuMultiSelect
                label="Analyst crew"
                options={[
                  { value: "market", label: "Market" },
                  { value: "news", label: "News" },
                  { value: "social", label: "Social" },
                  { value: "fundamentals", label: "Fundamentals" },
                ]}
                value={values.analysts}
                onChange={(analysts) => setValues((current) => ({ ...current, analysts }))}
              />
            </>
          ) : null}

          {step === 3 ? (
            <>
              <NeuToggleGroup
                label="Workflow mode"
                value={values.workflowMode}
                onChange={(next) =>
                  setValues((current) => ({
                    ...current,
                    workflowMode: next as "quick_trade" | "deep_analysis",
                  }))
                }
                options={[
                  { value: "quick_trade", label: "Quick trade" },
                  { value: "deep_analysis", label: "Deep analysis" },
                ]}
              />
              <NeuInput
                label="Backend endpoint"
                value={values.backendEndpoint}
                onChange={(event) => setValues((current) => ({ ...current, backendEndpoint: event.target.value }))}
                helperText="Keep proxy, model catalog, and agent overrides pointed at the same runtime."
              />
              <NeuInput
                label="Output language"
                value={values.outputLanguage}
                onChange={(event) => setValues((current) => ({ ...current, outputLanguage: event.target.value }))}
              />
            </>
          ) : null}
        </div>
      }
      summary={
        <div className="space-y-4">
          <div className="space-y-2">
            <p className="text-sm font-semibold tracking-[-0.02em]">Launch summary</p>
            <NeuProgressTrack value={step} max={3} tone="accent" />
          </div>
          <div className="space-y-2 text-sm">
            {[
              { label: "Asset", value: values.assetType },
              { label: "Symbol", value: values.symbol || "Not selected" },
              { label: "Provider", value: values.provider },
              { label: "Models", value: `${values.deepModel || "—"} / ${values.quickModel || "—"}` },
              { label: "Workflow", value: values.workflowMode },
            ].map((entry, index) => (
              <NeuSurface
                key={entry.label}
                depth={index === 0 ? "raised" : "inset"}
                radius="md"
                padding="sm"
                className="flex items-center justify-between gap-3"
              >
                <span style={{ color: "var(--neu-text-muted)" }}>{entry.label}</span>
                <span className="font-semibold">{entry.value}</span>
              </NeuSurface>
            ))}
          </div>
        </div>
      }
      footer={
        <div className="flex flex-wrap justify-between gap-3">
          <div className="flex gap-2">
            <NeuButton variant="secondary" size="sm" onClick={() => setStep((current) => Math.max(1, current - 1))} disabled={step === 1}>
              Back
            </NeuButton>
            <NeuButton variant="secondary" size="sm" onClick={() => setStep((current) => Math.min(3, current + 1))} disabled={step === 3}>
              Next
            </NeuButton>
          </div>
          <div className="flex flex-wrap gap-2">
            {onSaveDraft ? (
              <NeuButton variant="soft-tonal" onClick={() => onSaveDraft(values)}>
                <Save className="size-4" />
                Save draft
              </NeuButton>
            ) : null}
            <NeuButton variant="primary" onClick={() => onSubmit(values)}>
              <Play className="size-4" />
              Launch
            </NeuButton>
          </div>
        </div>
      }
    />
  );
}

export function AnalysisRunConsole({
  run,
  agents,
  messages,
  reports,
  stats,
  wsState,
  configSummary,
}: {
  run: { runId: string; symbol: string; status: string; duration?: string };
  agents: Array<{ name: string; status: string; activity: string }>;
  messages: Array<{ sender: string; content: string; at: string }>;
  reports: Array<{ id: string; title: string; body: string }>;
  stats: NeuMetric[];
  wsState: { status: "connected" | "reconnecting" | "offline"; attempt?: number };
  configSummary: Array<{ label: string; value: string }>;
}) {
  const [selectedReport, setSelectedReport] = useState(reports[0]?.id ?? "report");

  return (
    <NeuEntityDetailTemplate
      header={
        <NeuEntityHeader
          title={`${run.symbol} analysis`}
          subtitle="Live run console with agent telemetry, streaming messages, report tabs, and config context."
          backTo={{ label: "Back to research" }}
          status={<NeuStatusPill label={run.status} tone={run.status === "completed" ? "success" : run.status === "failed" ? "danger" : "accent"} />}
          stats={[
            { label: "Run", value: run.runId, tone: "neutral" },
            { label: "Status", value: run.status, tone: run.status === "completed" ? "success" : "accent" },
            { label: "Duration", value: run.duration ?? "Live", tone: "warning" },
          ]}
        />
      }
      summary={
        <NeuBanner
          tone={wsState.status === "connected" ? "success" : wsState.status === "reconnecting" ? "warning" : "danger"}
          title="Connection state"
          description="The console supports live streaming, replay fallback, and reconnect affordances with the same tactile component language."
          actions={<NeuReconnectionChip {...wsState} />}
        />
      }
      content={
        <div className="space-y-5">
          <NeuKpiGrid items={stats} />
          <div className="grid gap-5 xl:grid-cols-2">
            <NeuTable
              columns={[
                { id: "name", header: "Agent", accessor: "name" },
                { id: "status", header: "Status", accessor: "status" },
                { id: "activity", header: "Activity", accessor: "activity" },
              ]}
              rows={agents}
              rowKey={(agent) => agent.name}
            />
            <NeuCard title="Messages" description="Streaming operator and agent communication.">
              <NeuWell padding="sm" className="max-h-[22rem] space-y-3 overflow-auto">
                {messages.map((message, index) => (
                  <NeuSurface
                    key={`${message.at}-${message.sender}`}
                    depth={index % 2 === 0 ? "raised" : "inset"}
                    radius="md"
                    padding="sm"
                    className="space-y-1"
                  >
                    <p className="text-xs font-semibold uppercase tracking-[0.16em]" style={{ color: "var(--neu-text-muted)" }}>
                      {message.sender} · {message.at}
                    </p>
                    <p className="text-sm leading-6">{message.content}</p>
                  </NeuSurface>
                ))}
              </NeuWell>
            </NeuCard>
          </div>
          <NeuTabs
            value={selectedReport}
            onValueChange={setSelectedReport}
            items={reports.map((report) => ({
              value: report.id,
              label: report.title,
              content: (
                <NeuWell padding="md" className="min-h-[20rem] text-sm leading-7">
                  {report.body}
                </NeuWell>
              ),
            }))}
          />
        </div>
      }
      aside={
        <NeuCard title="Resolved configuration" description="Pinned run metadata for replay and support workflows.">
          <div className="space-y-2 text-sm">
            {configSummary.map((entry) => (
              <div key={entry.label} className="flex items-center justify-between gap-3">
                <span style={{ color: "var(--neu-text-muted)" }}>{entry.label}</span>
                <span className="font-medium">{entry.value}</span>
              </div>
            ))}
          </div>
        </NeuCard>
      }
    />
  );
}

export function ScanResultsBoard({
  buy,
  sell,
  hold,
  filters,
  onTrade,
  onViewAnalysis,
}: {
  buy: Array<{ symbol: string; score: number; runId?: string }>;
  sell: Array<{ symbol: string; score: number; runId?: string }>;
  hold: Array<{ symbol: string; score: number; runId?: string }>;
  filters?: ReactNode;
  onTrade?: (symbol: string, direction: "buy" | "sell") => void;
  onViewAnalysis?: (runId: string) => void;
}) {
  const groups = [
    { title: "Buy", tone: "success" as const, rows: buy, direction: "buy" as const },
    { title: "Sell", tone: "danger" as const, rows: sell, direction: "sell" as const },
    { title: "Hold", tone: "warning" as const, rows: hold, direction: "buy" as const },
  ];

  return (
    <div className="space-y-4">
      {filters}
      <div className="grid gap-4 xl:grid-cols-3">
        {groups.map((group) => (
          <NeuCard
            key={group.title}
            title={`${group.title} signals`}
            description={`${group.rows.length} assets in this band.`}
            actions={<NeuStatusPill label={`${group.rows.length} signals`} tone={group.tone} />}
          >
            <div className="space-y-3">
              {group.rows.map((row) => (
                <NeuSurface
                  key={row.symbol}
                  depth="inset"
                  radius="md"
                  padding="sm"
                  interactive={Boolean(onTrade || onViewAnalysis)}
                  className="space-y-3"
                >
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <p className="text-sm font-semibold">{row.symbol}</p>
                      <NeuBadge tone={group.tone} variant="soft">{group.title}</NeuBadge>
                    </div>
                    <div className="w-28">
                      <NeuScoreBar
                        score={row.score}
                        direction={group.title === "Buy" ? "buy" : group.title === "Sell" ? "sell" : "neutral"}
                      />
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {group.title !== "Hold" && onTrade ? (
                      <NeuButton size="sm" variant="primary" onClick={() => onTrade(row.symbol, group.direction)}>
                        Trade
                      </NeuButton>
                    ) : null}
                    {row.runId && onViewAnalysis ? (
                      <NeuButton size="sm" variant="secondary" onClick={() => onViewAnalysis(row.runId!)}>
                        View analysis
                      </NeuButton>
                    ) : null}
                  </div>
                </NeuSurface>
              ))}
            </div>
          </NeuCard>
        ))}
      </div>
    </div>
  );
}

export function ScanWorkbench({
  settings,
  activeScan,
  results,
  filters,
  onStart,
  onCancel,
  onTrade,
  onSchedule,
}: {
  settings: ReactNode;
  activeScan?: { phase: string; progress: number; summary: string };
  results: Parameters<typeof ScanResultsBoard>[0];
  filters?: ReactNode;
  onStart: () => void;
  onCancel?: () => void;
  onTrade?: (symbol: string, direction: "buy" | "sell") => void;
  onSchedule?: () => void;
}) {
  return (
    <NeuWorkbenchTemplate
      header={
        <NeuPageHeader
          eyebrow="Scanner workbench"
          title="Scanner execution surface"
          description="Combines setup, active scan telemetry, grouped results, and schedule entry points inside one consistent workbench template."
          actions={
            <div className="flex flex-wrap gap-2">
              <NeuButton variant="primary" onClick={onStart}>
                <Play className="size-4" />
                Start scan
              </NeuButton>
              {onSchedule ? (
                <NeuButton variant="soft-tonal" onClick={onSchedule}>
                  <Save className="size-4" />
                  Schedule
                </NeuButton>
              ) : null}
              {onCancel ? (
                <NeuButton variant="danger" onClick={onCancel}>
                  Cancel
                </NeuButton>
              ) : null}
            </div>
          }
        />
      }
      controls={<NeuCard title="Scan settings">{settings}</NeuCard>}
      secondaryActions={
        activeScan ? (
          <NeuCard title="Active scan" description={activeScan.summary}>
            <NeuProgressTrack value={activeScan.progress} max={100} segmented tone="accent" />
          </NeuCard>
        ) : null
      }
      results={<ScanResultsBoard {...results} filters={filters} onTrade={onTrade} />}
    />
  );
}

export function AccountsGrid({
  accounts,
  filter,
  onFilterChange,
  onAdd,
  onResetDemo,
  onCloseAll,
}: {
  accounts: Array<{ id: string; label: string; type: string; equity: string; pnl: string; positions: number }>;
  filter: string;
  onFilterChange: (filter: string) => void;
  onAdd?: () => void;
  onResetDemo?: () => void;
  onCloseAll?: () => void;
}) {
  return (
    <div className="space-y-5">
      <NeuPageHeader
        eyebrow="Portfolio"
        title="Accounts grid"
        description="Portfolio command center for all, live, and demo account groups."
        actions={
          <div className="flex flex-wrap gap-2">
            {onResetDemo ? <NeuButton variant="soft-tonal" onClick={onResetDemo}>Reset demo</NeuButton> : null}
            {onCloseAll ? <NeuButton variant="danger" onClick={onCloseAll}>Close all</NeuButton> : null}
            {onAdd ? <NeuButton variant="primary" onClick={onAdd}>Add account</NeuButton> : null}
          </div>
        }
      />
      <NeuFilterBar
        filters={["all", "live", "demo"].map((entry) => ({
          id: entry,
          label: entry,
          active: filter === entry,
          onSelect: () => onFilterChange(entry),
        }))}
      />
      <div className="grid gap-4 xl:grid-cols-3">
        {accounts.map((account) => (
          <NeuCard
            key={account.id}
            title={account.label}
            description={`${account.type} account`}
            footer={<NeuBadge tone={account.type === "demo" ? "warning" : "accent"} variant="soft">{account.type}</NeuBadge>}
            actions={<NeuStatusPill label={`${account.positions} positions`} tone={account.positions > 0 ? "accent" : "neutral"} />}
          >
            <div className="grid gap-3 sm:grid-cols-3">
              <NeuWell padding="sm">
                <p className="text-[11px] font-semibold uppercase tracking-[0.18em]" style={{ color: "var(--neu-text-muted)" }}>Equity</p>
                <p className="mt-2 text-lg font-semibold">{account.equity}</p>
              </NeuWell>
              <NeuWell padding="sm">
                <p className="text-[11px] font-semibold uppercase tracking-[0.18em]" style={{ color: "var(--neu-text-muted)" }}>PnL</p>
                <p className="mt-2 text-lg font-semibold">{account.pnl}</p>
              </NeuWell>
              <NeuWell padding="sm">
                <p className="text-[11px] font-semibold uppercase tracking-[0.18em]" style={{ color: "var(--neu-text-muted)" }}>Positions</p>
                <p className="mt-2 text-lg font-semibold">{account.positions}</p>
              </NeuWell>
            </div>
          </NeuCard>
        ))}
      </div>
    </div>
  );
}

export function AccountSummaryHero({
  account,
  wallet,
  pnl,
  actions,
}: {
  account: { label: string; type: string; status: string };
  wallet: NeuMetric[];
  pnl: NeuMetric[];
  actions?: ReactNode;
}) {
  return (
    <div className="space-y-5">
      <NeuEntityHeader
        title={account.label}
        subtitle={`${account.type} account`}
        status={<NeuStatusPill label={account.status} tone={account.status === "live" ? "success" : "warning"} />}
        actions={actions}
      />
      <NeuKpiGrid items={[...wallet, ...pnl]} />
    </div>
  );
}

export function TradeDeskWorkspace({
  activeTrades,
  historyTrades,
  filters,
  stats,
  wsConnected,
  onCloseTrade,
  onCloseAll,
}: {
  activeTrades: Array<{ id: string; symbol: string; side: string; status: string; pnl: string }>;
  historyTrades: Array<{ id: string; symbol: string; side: string; status: string; pnl: string }>;
  filters: ReactNode;
  stats: NeuMetric[];
  wsConnected: boolean;
  onCloseTrade?: (tradeId: string) => void;
  onCloseAll?: () => void;
}) {
  const [tradeTab, setTradeTab] = useState<"active" | "history">("active");
  const activeColumns = [
    { id: "symbol", header: "Symbol", accessor: "symbol" as const },
    { id: "side", header: "Side", accessor: "side" as const },
    { id: "status", header: "Status", accessor: "status" as const },
    { id: "pnl", header: "PnL", accessor: "pnl" as const, align: "right" as const },
  ];

  return (
    <div className="space-y-5">
      {!wsConnected ? (
        <NeuBanner
          tone="warning"
          title="WebSocket disconnected"
          description="Trade streaming is paused. The table stays usable and can continue from polling or reconnect mode."
        />
      ) : null}
      <NeuPageHeader
        eyebrow="Execution"
        title="Trade desk workspace"
        description="Unified active and historical trade views with filter persistence and close-trade affordances."
        actions={onCloseAll ? <NeuButton variant="danger" onClick={onCloseAll}>Close all</NeuButton> : null}
      />
      <NeuKpiGrid items={stats} />
      <NeuTabs
        value={tradeTab}
        onValueChange={(value) => setTradeTab(value as "active" | "history")}
        items={[
          {
            value: "active",
            label: "Active",
            content: (
              <div className="space-y-4">
                {filters}
                <NeuTable
                  columns={activeColumns}
                  rows={activeTrades}
                  rowKey={(trade) => trade.id}
                  rowActions={(trade) =>
                    onCloseTrade ? (
                      <NeuButton size="sm" variant="danger" onClick={() => onCloseTrade(trade.id)}>
                        Close
                      </NeuButton>
                    ) : null
                  }
                />
              </div>
            ),
          },
          {
            value: "history",
            label: "History",
            content: <NeuTable columns={activeColumns} rows={historyTrades} rowKey={(trade) => trade.id} />,
          },
        ]}
      />
    </div>
  );
}

export function StrategyLibraryBoard({
  strategies,
  filters,
  search,
  onCreate,
  onEdit,
  onDuplicate,
  onDelete,
  onImport,
  onExport,
}: {
  strategies: Array<{ id: string; name: string; category: string; status: string; description: string }>;
  filters?: ReactNode;
  search?: ReactNode;
  onCreate?: () => void;
  onEdit?: (id: string) => void;
  onDuplicate?: (id: string) => void;
  onDelete?: (id: string) => void;
  onImport?: () => void;
  onExport?: () => void;
}) {
  return (
    <NeuLibraryTemplate
      header={
        <NeuPageHeader
          eyebrow="Strategy library"
          title="Strategy collection"
          description="Reusable strategy cards with CRUD, import, and export actions."
          actions={
            <div className="flex flex-wrap gap-2">
              {onImport ? <NeuButton variant="secondary" onClick={onImport}>Import</NeuButton> : null}
              {onExport ? <NeuButton variant="secondary" onClick={onExport}>Export</NeuButton> : null}
              {onCreate ? <NeuButton variant="primary" onClick={onCreate}>Create strategy</NeuButton> : null}
            </div>
          }
        />
      }
      filters={
        <NeuFilterBar
          filters={[
            { id: "all", label: "All", active: true },
            { id: "active", label: "Active" },
            { id: "draft", label: "Draft" },
          ]}
          search={search}
          actions={filters}
        />
      }
      grid={
        <div className="grid gap-4 xl:grid-cols-3">
          {strategies.map((strategy) => (
            <NeuCard
              key={strategy.id}
              title={strategy.name}
              description={strategy.description}
              footer={<NeuBadge tone={strategy.status === "active" ? "success" : "warning"} variant="soft">{strategy.status}</NeuBadge>}
              actions={
                <div className="flex flex-wrap gap-2">
                  {onEdit ? <NeuButton size="sm" variant="secondary" onClick={() => onEdit(strategy.id)}>Edit</NeuButton> : null}
                  {onDuplicate ? <NeuButton size="sm" variant="soft-tonal" onClick={() => onDuplicate(strategy.id)}>Duplicate</NeuButton> : null}
                  {onDelete ? <NeuButton size="sm" variant="danger" onClick={() => onDelete(strategy.id)}>Delete</NeuButton> : null}
                </div>
              }
            >
              <NeuBadge tone="accent" variant="soft">{strategy.category}</NeuBadge>
            </NeuCard>
          ))}
        </div>
      }
    />
  );
}

export function CycleBoard({
  cycles,
  selectedCycle,
  onStop,
  onRefresh,
}: {
  cycles: Array<{ id: string; label: string; status: string; trades: number; symbol: string }>;
  selectedCycle?: string;
  onStop?: (cycleId: string) => void;
  onRefresh?: () => void;
}) {
  const active = cycles.find((cycle) => cycle.id === selectedCycle) ?? cycles[0];

  return (
    <NeuEntityDetailTemplate
      header={
        <NeuPageHeader
          eyebrow="Trading cycles"
          title="Cycle board"
          description="Shared list-detail system for active and completed trading cycles."
          actions={onRefresh ? <NeuButton variant="secondary" onClick={onRefresh}><RefreshCcw className="size-4" />Refresh</NeuButton> : null}
        />
      }
      content={
        <div className="space-y-4">
          {cycles.map((cycle) => (
            <NeuCard
              key={cycle.id}
              title={cycle.label}
              description={`${cycle.symbol} · ${cycle.trades} trades${cycle.id === active?.id ? " · selected" : ""}`}
              footer={<NeuBadge tone={cycle.status === "active" ? "success" : cycle.status === "failed" ? "danger" : "warning"} variant="soft">{cycle.status}</NeuBadge>}
              actions={cycle.id === active?.id ? <NeuStatusPill label="Focused" tone="accent" /> : null}
              interactive
            />
          ))}
        </div>
      }
      aside={
        active ? (
          <NeuCard
            title={active.label}
            description="Selected cycle detail"
            actions={onStop ? <NeuButton variant="danger" size="sm" onClick={() => onStop(active.id)}>Stop cycle</NeuButton> : null}
          >
            <div className="space-y-2 text-sm">
              <p><strong>Symbol:</strong> {active.symbol}</p>
              <p><strong>Status:</strong> {active.status}</p>
              <p><strong>Trades:</strong> {active.trades}</p>
            </div>
          </NeuCard>
        ) : null
      }
    />
  );
}

export function ConfigInspector({
  resolved,
  overrides,
  maskedKeys,
  appearance,
}: {
  resolved: Array<{ key: string; value: string }>;
  overrides: Array<{ key: string; value: string }>;
  maskedKeys?: string[];
  appearance?: ReactNode;
}) {
  const mask = new Set(maskedKeys ?? []);
  const resolvedRows = resolved.map((entry) => ({
    ...entry,
    value: mask.has(entry.key) ? "••••••••" : entry.value,
  }));

  return (
    <NeuInspectorTemplate
      header={
        <NeuPageHeader
          eyebrow="System config"
          title="Configuration inspector"
          description="Resolved values, runtime overrides, and appearance controls inside one operational template."
        />
      }
      inspector={
        <NeuTableIndexTemplate
          header={null}
          table={
            <NeuTable
              columns={[
                { id: "key", header: "Key", accessor: "key" },
                { id: "value", header: "Value", accessor: "value" },
              ]}
              rows={resolvedRows}
              rowKey={(row) => row.key}
            />
          }
        />
      }
      notes={
        <NeuCard title="Active overrides" description="Layered on top of resolved defaults.">
          <div className="space-y-2 text-sm">
            {overrides.map((entry) => (
              <NeuSurface key={entry.key} depth="inset" radius="md" padding="sm" className="flex items-center justify-between gap-3">
                <span>{entry.key}</span>
                <span style={{ color: "var(--neu-text-muted)" }}>{mask.has(entry.key) ? "••••••••" : entry.value}</span>
              </NeuSurface>
            ))}
          </div>
        </NeuCard>
      }
      aside={appearance}
    />
  );
}

export function MemoryRecordList({
  items,
  page,
  total,
  onPageChange,
}: {
  items: Array<{ id: string; summary: string; confidence: string; status: string; createdAt: string }>;
  page: number;
  total: number;
  onPageChange: (page: number) => void;
}) {
  return (
    <div className="space-y-5">
      <NeuPageHeader
        eyebrow="Memory"
        title="Memory record list"
        description="Paginated browser for decision records, confidence states, and operational memory status."
      />
      <NeuTable
        columns={[
          { id: "summary", header: "Summary", accessor: "summary" },
          { id: "confidence", header: "Confidence", accessor: "confidence" },
          { id: "status", header: "Status", accessor: "status" },
          { id: "createdAt", header: "Created", accessor: "createdAt" },
        ]}
        rows={items}
        rowKey={(item) => item.id}
        emptyState={
          <NeuEmptyState
            icon={<MemoryStick className="size-6" />}
            title="No memory records"
            description="This route stays empty-safe and keeps pagination wiring ready for later integration."
          />
        }
      />
      <NeuPagination page={page} pageSize={10} total={total} onPageChange={onPageChange} />
    </div>
  );
}
