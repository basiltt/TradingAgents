import { useState, useEffect } from "react";
import { apiClient, ApiError } from "@/api/client";
import type { Strategy, StrategyConfig, StrategyCategory, StrategyStatus } from "@/api/client";
import { toast } from "sonner";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { CATEGORIES, STATUSES, STATUS_COLORS, CATEGORY_COLORS } from "./constants";
import { NeuSwitch } from "@/design-system/neumorphism";

const SELECT_CLASS = "h-8 w-full rounded-lg border border-input bg-transparent px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30";

interface Props {
  open: boolean;
  strategy: Strategy | null;
  onClose: () => void;
  onSaved: () => void;
}

function emptyConfig(): StrategyConfig {
  return {
    trading_mode: "manual_reference",
    signal_adherence: "strict_follow",
    trade_directionality: "standard",
    order_type: "market",
    capital_allocation_mode: "percentage",
    base_capital_pct: 10,
    position_sizing_method: "risk_based",
    leverage_multiplier: 1,
    risk_per_trade_pct: 2,
    sl_type: "fixed_pct",
    sl_value: 5,
    tp_type: "fixed_pct",
    tp_value: 10,
    alert_entry: true,
    alert_exit: true,
    alert_sl_hit: true,
    alert_tp_hit: true,
    cycle_enabled: false,
  };
}

const SECTION_ICONS: Record<string, string> = {
  metadata: "M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z",
  signal: "M13 10V3L4 14h7v7l9-11h-7z",
  capital: "M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z",
  risk: "M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z",
  stoploss: "M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 5.636m12.728 12.728L5.636 5.636",
  takeprofit: "M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z",
  lifecycle: "M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15",
  market: "M3 4a1 1 0 011-1h16a1 1 0 011 1v2.586a1 1 0 01-.293.707l-6.414 6.414a1 1 0 00-.293.707V17l-4 4v-6.586a1 1 0 00-.293-.707L3.293 7.293A1 1 0 013 6.586V4z",
  schedule: "M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z",
  cycle: "M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z",
  alerts: "M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9",
  emergency: "M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z",
};

export function StrategyFormDialog({ open, strategy, onClose, onSaved }: Props) {
  const isEdit = !!strategy;
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState<StrategyCategory>("swing");
  const [status, setStatus] = useState<StrategyStatus>("draft");
  const [config, setConfig] = useState<StrategyConfig>(emptyConfig());
  const [saving, setSaving] = useState(false);
  const [mode, setMode] = useState<"quick" | "full">("quick");
  const [openSections, setOpenSections] = useState<Set<string>>(new Set(["metadata"]));

  useEffect(() => {
    if (!open) return;
    if (strategy) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- populating form from prop data
      setName(strategy.name);
      setDescription(strategy.description);
      setCategory(strategy.category);
      setStatus(strategy.status);
      const merged = { ...emptyConfig(), ...strategy.config };
      setConfig(merged);
    } else {
      setName("");
      setDescription("");
      setCategory("swing");
      setStatus("draft");
      setConfig(emptyConfig());
    }
    setOpenSections(new Set(["metadata"]));
    if (!strategy) setMode("quick");
  }, [strategy, open]);

  const toggleSection = (id: string) => {
    setOpenSections((prev) => {
      const next = new Set(prev);
      if (next.has(id)) { next.delete(id); } else { next.add(id); }
      return next;
    });
  };

  const updateConfig = (partial: Partial<StrategyConfig>) => {
    setConfig((prev) => ({ ...prev, ...partial }));
  };

  const handleSave = async () => {
    if (!name.trim()) {
      toast.error("Strategy name is required");
      return;
    }
    if (config.cycle_enabled) {
      if (config.cycle_target_pnl_pct == null || config.cycle_target_pnl_pct <= 0) {
        toast.error("Cycle target PnL % must be a positive number");
        return;
      }
      if (config.cycle_stop_loss_pct != null && config.cycle_stop_loss_pct <= 0) {
        toast.error("Cycle stop loss % must be a positive number");
        return;
      }
      if (config.cycle_stop_loss_pct != null && config.cycle_stop_loss_pct >= config.cycle_target_pnl_pct) {
        toast.error("Cycle stop loss must be less than target PnL");
        return;
      }
      if (config.cycle_max_trades != null && (!Number.isInteger(config.cycle_max_trades) || config.cycle_max_trades < 1)) {
        toast.error("Max trades per cycle must be a whole number >= 1");
        return;
      }
      if (config.cycle_timeout_hours != null && config.cycle_timeout_hours < 0) {
        toast.error("Cycle timeout must be non-negative");
        return;
      }
      if (config.cycle_cooldown_hours != null && config.cycle_cooldown_hours < 0) {
        toast.error("Cycle cooldown must be non-negative");
        return;
      }
    }
    setSaving(true);
    try {
      const data = { name, description, category, status, config };
      if (isEdit) {
        await apiClient.updateStrategy(strategy!.id, data);
        toast.success("Strategy updated");
      } else {
        await apiClient.createStrategy(data);
        toast.success("Strategy created");
      }
      onSaved();
      onClose();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : (isEdit ? "Failed to update" : "Failed to create"));
    } finally {
      setSaving(false);
    }
  };

  const handleOpenChange = (v: boolean) => {
    if (!v) onClose();
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-w-[calc(100%-2rem)] sm:max-w-md md:max-w-xl lg:max-w-3xl xl:max-w-4xl 2xl:max-w-5xl max-h-[90vh] sm:max-h-[85vh] flex flex-col overflow-hidden p-0" showCloseButton={false}>
        {/* Header */}
        <div className="flex items-center justify-between px-5 pt-4 pb-3.5">
          <div className="flex items-center gap-4">
            <div>
              <DialogHeader>
                <DialogTitle className="text-lg">{isEdit ? "Edit Strategy" : "New Strategy"}</DialogTitle>
              </DialogHeader>
              <p className="text-sm text-muted-foreground mt-1">
                {isEdit ? "Modify your strategy configuration" : "Configure a new trading strategy"}
              </p>
            </div>
            <div className="flex items-center rounded-lg bg-muted/50 p-0.5">
              <button
                onClick={() => setMode("quick")}
                className={`px-3 py-1 rounded-md text-xs font-medium transition-all ${mode === "quick" ? "bg-primary text-primary-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"}`}
              >
                Quick
              </button>
              <button
                onClick={() => setMode("full")}
                className={`px-3 py-1 rounded-md text-xs font-medium transition-all ${mode === "full" ? "bg-primary text-primary-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"}`}
              >
                Full
              </button>
            </div>
          </div>
          <button onClick={onClose} aria-label="Close dialog" className="p-1.5 rounded-lg hover:bg-muted transition-colors">
            <svg className="w-4 h-4 text-muted-foreground" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Scrollable body */}
        <div className="flex-1 min-h-0 overflow-y-auto px-5 pb-3.5 custom-scrollbar">
          {mode === "quick" ? (
            <QuickModeForm
              name={name} setName={setName}
              description={description} setDescription={setDescription}
              category={category} setCategory={setCategory}
              status={status} setStatus={setStatus}
              config={config} updateConfig={updateConfig}
            />
          ) : (
          <div className="space-y-3">

            {/* Metadata Section */}
            <Section id="metadata" title="Strategy Information" icon={SECTION_ICONS.metadata} open={openSections.has("metadata")} onToggle={toggleSection}>
              <div className="space-y-4">
                <div>
                  <Label htmlFor="strategy-name" className="text-xs text-muted-foreground mb-1.5">Name *</Label>
                  <Input id="strategy-name" placeholder="My Trading Strategy" value={name} onChange={(e) => setName(e.target.value)} />
                </div>
                <div>
                  <Label htmlFor="strategy-desc" className="text-xs text-muted-foreground mb-1.5">Description</Label>
                  <textarea
                    id="strategy-desc"
                    placeholder="Strategy notes..."
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    rows={2}
                    className="w-full rounded-lg border border-input bg-transparent px-2.5 py-2 text-sm transition-colors outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30 resize-none"
                  />
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div>
                    <Label className="text-xs text-muted-foreground mb-1.5">Category</Label>
                    <div className="flex flex-wrap gap-1.5 mt-1">
                      {CATEGORIES.map((c) => (
                        <button
                          key={c}
                          onClick={() => setCategory(c)}
                          className={`px-2.5 py-1 rounded-md text-xs font-medium transition-all ${
                            category === c
                              ? CATEGORY_COLORS[c] + " ring-1 ring-current/30"
                              : "bg-muted/50 text-muted-foreground hover:bg-muted"
                          }`}
                        >
                          {c.charAt(0).toUpperCase() + c.slice(1)}
                        </button>
                      ))}
                    </div>
                  </div>
                  <div>
                    <Label className="text-xs text-muted-foreground mb-1.5">Status</Label>
                    <div className="flex flex-wrap gap-1.5 mt-1">
                      {STATUSES.map((s) => (
                        <button
                          key={s}
                          onClick={() => setStatus(s)}
                          className={`px-2.5 py-1 rounded-md text-xs font-medium transition-all ${
                            status === s
                              ? STATUS_COLORS[s] + " ring-1 ring-current/30"
                              : "bg-muted/50 text-muted-foreground hover:bg-muted"
                          }`}
                        >
                          {s.charAt(0).toUpperCase() + s.slice(1)}
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <FormField label="Trading Mode">
                    <select value={config.trading_mode ?? ""} onChange={(e) => updateConfig({ trading_mode: e.target.value })} className={SELECT_CLASS}>
                      <option value="manual_reference">Manual Reference</option>
                      <option value="semi_automated">Semi-Automated</option>
                      <option value="fully_automated">Fully Automated</option>
                    </select>
                  </FormField>
                  <FormField label="Asset Whitelist">
                    <Input placeholder="BTC, ETH, SOL" value={(config.asset_whitelist ?? []).join(", ")} onChange={(e) => updateConfig({ asset_whitelist: e.target.value.split(",").map(s => s.trim()).filter(Boolean) })} />
                  </FormField>
                </div>
                <FormField label="Asset Blacklist">
                  <Input placeholder="DOGE, SHIB" value={(config.asset_blacklist ?? []).join(", ")} onChange={(e) => updateConfig({ asset_blacklist: e.target.value.split(",").map(s => s.trim()).filter(Boolean) })} />
                </FormField>
              </div>
            </Section>

            {/* Signal Processing */}
            <Section id="signal" title="Signal Processing & Execution" icon={SECTION_ICONS.signal} open={openSections.has("signal")} onToggle={toggleSection}>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <FormField label="Signal Adherence">
                  <select value={config.signal_adherence ?? ""} onChange={(e) => updateConfig({ signal_adherence: e.target.value })} className={SELECT_CLASS}>
                    <option value="strict_follow">Strict Follow</option>
                    <option value="alert_only">Alert Only</option>
                    <option value="manual_override">Manual Override</option>
                  </select>
                </FormField>
                <FormField label="Trade Direction">
                  <select value={config.trade_directionality ?? ""} onChange={(e) => updateConfig({ trade_directionality: e.target.value })} className={SELECT_CLASS}>
                    <option value="standard">Standard</option>
                    <option value="inverse">Inverse/Reverse</option>
                  </select>
                </FormField>
                <FormField label="Order Type">
                  <select value={config.order_type ?? ""} onChange={(e) => updateConfig({ order_type: e.target.value })} className={SELECT_CLASS}>
                    <option value="market">Market</option>
                    <option value="limit">Limit</option>
                    <option value="stop">Stop</option>
                    <option value="stop_limit">Stop-Limit</option>
                  </select>
                </FormField>
                <FormField label="Slippage Tolerance (%)">
                  <Input type="number" step="0.1" value={config.slippage_tolerance ?? ""} onChange={(e) => updateConfig({ slippage_tolerance: e.target.value ? Number(e.target.value) : undefined })} />
                </FormField>
                <FormField label="Partial Fills">
                  <Toggle checked={config.partial_fills ?? false} onChange={(v) => updateConfig({ partial_fills: v })} />
                </FormField>
                <FormField label="Max Spread (%)">
                  <Input type="number" step="0.01" value={config.max_spread ?? ""} onChange={(e) => updateConfig({ max_spread: e.target.value ? Number(e.target.value) : undefined })} />
                </FormField>
              </div>
            </Section>

            {/* Capital Allocation */}
            <Section id="capital" title="Capital Allocation & Position Sizing" icon={SECTION_ICONS.capital} open={openSections.has("capital")} onToggle={toggleSection}>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <FormField label="Allocation Mode">
                  <select value={config.capital_allocation_mode ?? ""} onChange={(e) => updateConfig({ capital_allocation_mode: e.target.value })} className={SELECT_CLASS}>
                    <option value="fixed_amount">Fixed Amount</option>
                    <option value="percentage">Percentage</option>
                    <option value="dynamic">Dynamic/Risk-based</option>
                  </select>
                </FormField>
                <FormField label="Base Capital (%)">
                  <Input type="number" step="1" value={config.base_capital_pct ?? ""} onChange={(e) => updateConfig({ base_capital_pct: e.target.value ? Number(e.target.value) : undefined })} />
                </FormField>
                <FormField label="Position Size (Fixed)">
                  <Input type="number" step="1" value={config.absolute_position_size ?? ""} onChange={(e) => updateConfig({ absolute_position_size: e.target.value ? Number(e.target.value) : undefined })} />
                </FormField>
                <FormField label="Sizing Method">
                  <select value={config.position_sizing_method ?? ""} onChange={(e) => updateConfig({ position_sizing_method: e.target.value })} className={SELECT_CLASS}>
                    <option value="fixed_lot">Fixed Lot</option>
                    <option value="risk_based">Risk-based</option>
                    <option value="volatility_atr">Volatility/ATR</option>
                    <option value="kelly_criterion">Kelly Criterion</option>
                    <option value="manual">Manual</option>
                  </select>
                </FormField>
                <FormField label="Compounding">
                  <Toggle checked={config.compounding_enabled ?? false} onChange={(v) => updateConfig({ compounding_enabled: v })} />
                </FormField>
                <FormField label="Leverage">
                  <Input type="number" step="0.5" value={config.leverage_multiplier ?? ""} onChange={(e) => updateConfig({ leverage_multiplier: e.target.value ? Number(e.target.value) : undefined })} />
                </FormField>
                <FormField label="Max Leverage Cap">
                  <Input type="number" step="1" value={config.max_leverage_cap ?? ""} onChange={(e) => updateConfig({ max_leverage_cap: e.target.value ? Number(e.target.value) : undefined })} />
                </FormField>
                <FormField label="Max Global Exposure (%)">
                  <Input type="number" step="1" value={config.max_global_exposure_pct ?? ""} onChange={(e) => updateConfig({ max_global_exposure_pct: e.target.value ? Number(e.target.value) : undefined })} />
                </FormField>
                <FormField label="Max Simultaneous Trades">
                  <Input type="number" step="1" min="1" value={config.max_simultaneous_trades ?? ""} onChange={(e) => updateConfig({ max_simultaneous_trades: e.target.value ? Number(e.target.value) : undefined })} />
                </FormField>
                <FormField label="Max Exposure/Asset (%)">
                  <Input type="number" step="1" value={config.max_exposure_per_asset ?? ""} onChange={(e) => updateConfig({ max_exposure_per_asset: e.target.value ? Number(e.target.value) : undefined })} />
                </FormField>
              </div>
            </Section>

            {/* Risk Management */}
            <Section id="risk" title="Risk Management" icon={SECTION_ICONS.risk} open={openSections.has("risk")} onToggle={toggleSection}>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <FormField label="Risk Per Trade (%)">
                  <Input type="number" step="0.5" value={config.risk_per_trade_pct ?? ""} onChange={(e) => updateConfig({ risk_per_trade_pct: e.target.value ? Number(e.target.value) : undefined })} />
                </FormField>
                <FormField label="Global Drawdown Limit (%)">
                  <Input type="number" step="1" value={config.global_drawdown_limit_pct ?? ""} onChange={(e) => updateConfig({ global_drawdown_limit_pct: e.target.value ? Number(e.target.value) : undefined })} />
                </FormField>
                <FormField label="Daily Drawdown (%)">
                  <Input type="number" step="1" value={config.daily_drawdown_limit_pct ?? ""} onChange={(e) => updateConfig({ daily_drawdown_limit_pct: e.target.value ? Number(e.target.value) : undefined })} />
                </FormField>
                <FormField label="Weekly Drawdown (%)">
                  <Input type="number" step="1" value={config.weekly_drawdown_limit_pct ?? ""} onChange={(e) => updateConfig({ weekly_drawdown_limit_pct: e.target.value ? Number(e.target.value) : undefined })} />
                </FormField>
                <FormField label="Equity Protection (%)">
                  <Input type="number" step="1" value={config.equity_protection_threshold ?? ""} onChange={(e) => updateConfig({ equity_protection_threshold: e.target.value ? Number(e.target.value) : undefined })} />
                </FormField>
              </div>
            </Section>

            {/* Stop Loss */}
            <Section id="stoploss" title="Stop Loss" icon={SECTION_ICONS.stoploss} open={openSections.has("stoploss")} onToggle={toggleSection}>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <FormField label="SL Type">
                  <select value={config.sl_type ?? ""} onChange={(e) => updateConfig({ sl_type: e.target.value })} className={SELECT_CLASS}>
                    <option value="fixed_pct">Fixed %</option>
                    <option value="fixed_price">Fixed Price</option>
                    <option value="atr_based">ATR-based</option>
                    <option value="trailing">Trailing</option>
                    <option value="breakeven">Break-even</option>
                    <option value="indicator_based">Indicator</option>
                    <option value="time_based">Time-based</option>
                  </select>
                </FormField>
                <FormField label="SL Value">
                  <Input type="number" step="0.5" value={config.sl_value ?? ""} onChange={(e) => updateConfig({ sl_value: e.target.value ? Number(e.target.value) : undefined })} />
                </FormField>
                <FormField label="Leverage-Adjusted SL">
                  <Toggle checked={config.sl_leverage_adjusted ?? false} onChange={(v) => updateConfig({ sl_leverage_adjusted: v })} />
                </FormField>
                <FormField label="Breakeven Trigger (%)">
                  <Input type="number" step="0.5" value={config.breakeven_trigger_pct ?? ""} onChange={(e) => updateConfig({ breakeven_trigger_pct: e.target.value ? Number(e.target.value) : undefined })} />
                </FormField>
                <FormField label="Trailing Activation (%)">
                  <Input type="number" step="0.5" value={config.trailing_sl_activation_pct ?? ""} onChange={(e) => updateConfig({ trailing_sl_activation_pct: e.target.value ? Number(e.target.value) : undefined })} />
                </FormField>
                <FormField label="Trailing Distance (%)">
                  <Input type="number" step="0.5" value={config.trailing_sl_distance_pct ?? ""} onChange={(e) => updateConfig({ trailing_sl_distance_pct: e.target.value ? Number(e.target.value) : undefined })} />
                </FormField>
              </div>
            </Section>

            {/* Take Profit */}
            <Section id="takeprofit" title="Take Profit" icon={SECTION_ICONS.takeprofit} open={openSections.has("takeprofit")} onToggle={toggleSection}>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <FormField label="TP Type">
                  <select value={config.tp_type ?? ""} onChange={(e) => updateConfig({ tp_type: e.target.value })} className={SELECT_CLASS}>
                    <option value="fixed_pct">Fixed %</option>
                    <option value="rr_based">R:R-based</option>
                    <option value="indicator_based">Indicator</option>
                    <option value="trailing">Trailing</option>
                    <option value="time_based">Time-based</option>
                  </select>
                </FormField>
                <FormField label="TP Value">
                  <Input type="number" step="0.5" value={config.tp_value ?? ""} onChange={(e) => updateConfig({ tp_value: e.target.value ? Number(e.target.value) : undefined })} />
                </FormField>
              </div>
            </Section>

            {/* Trade Lifecycle */}
            <Section id="lifecycle" title="Trade Lifecycle" icon={SECTION_ICONS.lifecycle} open={openSections.has("lifecycle")} onToggle={toggleSection}>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <FormField label="Pyramiding">
                  <Toggle checked={config.pyramiding_enabled ?? false} onChange={(v) => updateConfig({ pyramiding_enabled: v })} />
                </FormField>
                <FormField label="Max Pyramid Entries">
                  <Input type="number" step="1" min="1" value={config.pyramiding_max_entries ?? ""} onChange={(e) => updateConfig({ pyramiding_max_entries: e.target.value ? Number(e.target.value) : undefined })} />
                </FormField>
                <FormField label="DCA Mode">
                  <select value={config.dca_mode ?? ""} onChange={(e) => updateConfig({ dca_mode: e.target.value || undefined })} className={SELECT_CLASS}>
                    <option value="">None</option>
                    <option value="down">Average Down</option>
                    <option value="up">Average Up</option>
                    <option value="grid">Grid</option>
                    <option value="incremental">Incremental</option>
                    <option value="martingale">Martingale</option>
                  </select>
                </FormField>
                <FormField label="Max Trades/Day">
                  <Input type="number" step="1" min="1" value={config.max_trades_per_day ?? ""} onChange={(e) => updateConfig({ max_trades_per_day: e.target.value ? Number(e.target.value) : undefined })} />
                </FormField>
                <FormField label="Max Trades/Hour">
                  <Input type="number" step="1" min="1" value={config.max_trades_per_hour ?? ""} onChange={(e) => updateConfig({ max_trades_per_hour: e.target.value ? Number(e.target.value) : undefined })} />
                </FormField>
                <FormField label="Cooldown After Loss (hrs)">
                  <Input type="number" step="0.5" value={config.cooldown_after_loss_hours ?? ""} onChange={(e) => updateConfig({ cooldown_after_loss_hours: e.target.value ? Number(e.target.value) : undefined })} />
                </FormField>
                <FormField label="Max Consecutive Losses">
                  <Input type="number" step="1" min="1" value={config.max_consecutive_losses ?? ""} onChange={(e) => updateConfig({ max_consecutive_losses: e.target.value ? Number(e.target.value) : undefined })} />
                </FormField>
                <FormField label="Signal Expiration (hrs)">
                  <Input type="number" step="1" value={config.signal_expiration_hours ?? ""} onChange={(e) => updateConfig({ signal_expiration_hours: e.target.value ? Number(e.target.value) : undefined })} />
                </FormField>
              </div>
            </Section>

            {/* Market Condition Filters */}
            <Section id="market" title="Market Filters" icon={SECTION_ICONS.market} open={openSections.has("market")} onToggle={toggleSection}>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <FormField label="Trend Only">
                  <Toggle checked={config.trend_only ?? false} onChange={(v) => updateConfig({ trend_only: v })} />
                </FormField>
                <FormField label="Range Only">
                  <Toggle checked={config.range_only ?? false} onChange={(v) => updateConfig({ range_only: v })} />
                </FormField>
                <FormField label="Volatility Threshold">
                  <Input type="number" step="0.1" value={config.volatility_threshold ?? ""} onChange={(e) => updateConfig({ volatility_threshold: e.target.value ? Number(e.target.value) : undefined })} />
                </FormField>
                <FormField label="Volume Threshold">
                  <Input type="number" step="1" value={config.volume_threshold ?? ""} onChange={(e) => updateConfig({ volume_threshold: e.target.value ? Number(e.target.value) : undefined })} />
                </FormField>
                <FormField label="News Avoidance">
                  <Toggle checked={config.news_avoidance ?? false} onChange={(v) => updateConfig({ news_avoidance: v })} />
                </FormField>
                <FormField label="Session Trading">
                  <Toggle checked={config.session_based_trading ?? false} onChange={(v) => updateConfig({ session_based_trading: v })} />
                </FormField>
              </div>
            </Section>

            {/* Trading Schedule */}
            <Section id="schedule" title="Trading Schedule" icon={SECTION_ICONS.schedule} open={openSections.has("schedule")} onToggle={toggleSection}>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <FormField label="Active Sessions">
                  <Input placeholder="e.g. London, New York" value={(config.trading_sessions ?? []).join(", ")} onChange={(e) => updateConfig({ trading_sessions: e.target.value ? e.target.value.split(",").map(s => s.trim()).filter(Boolean) : undefined })} />
                </FormField>
                <FormField label="Timezone">
                  <Input placeholder="e.g. UTC, EST" value={config.timezone ?? ""} onChange={(e) => updateConfig({ timezone: e.target.value || undefined })} />
                </FormField>
                <FormField label="Trading Days">
                  <Input placeholder="e.g. Mon, Tue, Wed" value={(config.trading_days ?? []).join(", ")} onChange={(e) => updateConfig({ trading_days: e.target.value ? e.target.value.split(",").map(s => s.trim()).filter(Boolean) : undefined })} />
                </FormField>
                <FormField label="Weekend Restriction">
                  <Toggle checked={config.weekend_restriction ?? false} onChange={(v) => updateConfig({ weekend_restriction: v })} />
                </FormField>
              </div>
            </Section>

            {/* Trading Cycle */}
            <Section id="cycle" title="Trading Cycle" icon={SECTION_ICONS.cycle} open={openSections.has("cycle")} onToggle={toggleSection}>
              <div className="space-y-3">
                <FormField label="Cycle Enabled">
                  <Toggle checked={config.cycle_enabled ?? false} onChange={(v) => updateConfig({ cycle_enabled: v })} />
                </FormField>
                {config.cycle_enabled && (
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <FormField label="Target PnL (%)">
                      <Input type="number" step="0.5" value={config.cycle_target_pnl_pct ?? ""} onChange={(e) => updateConfig({ cycle_target_pnl_pct: e.target.value ? Number(e.target.value) : undefined })} />
                    </FormField>
                    <FormField label="Max Trades/Cycle">
                      <Input type="number" step="1" min="1" value={config.cycle_max_trades ?? ""} onChange={(e) => updateConfig({ cycle_max_trades: e.target.value ? Number(e.target.value) : undefined })} />
                    </FormField>
                    <FormField label="Timeout (hours)">
                      <Input type="number" step="1" value={config.cycle_timeout_hours ?? ""} onChange={(e) => updateConfig({ cycle_timeout_hours: e.target.value ? Number(e.target.value) : undefined })} />
                    </FormField>
                    <FormField label="Cycle Stop Loss (%)">
                      <Input type="number" step="0.5" value={config.cycle_stop_loss_pct ?? ""} onChange={(e) => updateConfig({ cycle_stop_loss_pct: e.target.value ? Number(e.target.value) : undefined })} />
                    </FormField>
                    <FormField label="Cooldown (hours)">
                      <Input type="number" step="1" value={config.cycle_cooldown_hours ?? ""} onChange={(e) => updateConfig({ cycle_cooldown_hours: e.target.value ? Number(e.target.value) : undefined })} />
                    </FormField>
                    <FormField label="Auto-Restart">
                      <Toggle checked={config.cycle_auto_restart ?? false} onChange={(v) => updateConfig({ cycle_auto_restart: v })} />
                    </FormField>
                    <FormField label="Partial Close">
                      <Toggle checked={config.cycle_partial_close_allowed ?? false} onChange={(v) => updateConfig({ cycle_partial_close_allowed: v })} />
                    </FormField>
                  </div>
                )}
              </div>
            </Section>

            {/* Alerts */}
            <Section id="alerts" title="Notifications & Alerts" icon={SECTION_ICONS.alerts} open={openSections.has("alerts")} onToggle={toggleSection}>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <FormField label="Entry Alert">
                  <Toggle checked={config.alert_entry ?? false} onChange={(v) => updateConfig({ alert_entry: v })} />
                </FormField>
                <FormField label="Exit Alert">
                  <Toggle checked={config.alert_exit ?? false} onChange={(v) => updateConfig({ alert_exit: v })} />
                </FormField>
                <FormField label="SL Hit Alert">
                  <Toggle checked={config.alert_sl_hit ?? false} onChange={(v) => updateConfig({ alert_sl_hit: v })} />
                </FormField>
                <FormField label="TP Hit Alert">
                  <Toggle checked={config.alert_tp_hit ?? false} onChange={(v) => updateConfig({ alert_tp_hit: v })} />
                </FormField>
                <FormField label="Drawdown Alert">
                  <Toggle checked={config.alert_drawdown ?? false} onChange={(v) => updateConfig({ alert_drawdown: v })} />
                </FormField>
                <FormField label="Strategy Paused">
                  <Toggle checked={config.alert_strategy_paused ?? false} onChange={(v) => updateConfig({ alert_strategy_paused: v })} />
                </FormField>
                {config.cycle_enabled && (
                  <FormField label="Cycle Complete">
                    <Toggle checked={config.alert_cycle_complete ?? false} onChange={(v) => updateConfig({ alert_cycle_complete: v })} />
                  </FormField>
                )}
              </div>
            </Section>

            {/* Emergency */}
            <Section id="emergency" title="Emergency Controls" icon={SECTION_ICONS.emergency} open={openSections.has("emergency")} onToggle={toggleSection}>
              <div className="flex items-center gap-3 p-3 rounded-lg bg-red-500/5 border border-red-500/20">
                <FormField label="Kill Switch">
                  <Toggle checked={config.emergency_kill_switch ?? false} onChange={(v) => updateConfig({ emergency_kill_switch: v })} />
                </FormField>
                <span className="text-xs text-red-400">Immediately halt all strategy operations</span>
              </div>
            </Section>
          </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" size="sm" onClick={onClose} disabled={saving}>Cancel</Button>
          <Button size="sm" onClick={handleSave} disabled={saving || !name.trim()}>
            {saving ? "Saving..." : isEdit ? "Update Strategy" : "Create Strategy"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function Section({ id, title, icon, open, onToggle, children }: { id: string; title: string; icon: string; open: boolean; onToggle: (id: string) => void; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-border/50 overflow-hidden">
      <button
        onClick={() => onToggle(id)}
        className="w-full flex items-center gap-2.5 px-3.5 py-2.5 text-sm font-medium hover:bg-muted/50 transition-colors"
      >
        <svg className="w-4 h-4 text-muted-foreground shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d={icon} />
        </svg>
        <span className="flex-1 text-left">{title}</span>
        <svg className={`w-3.5 h-3.5 text-muted-foreground transition-transform ${open ? "rotate-180" : ""}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      {open && <div className="px-3.5 pb-3.5 pt-1">{children}</div>}
    </div>
  );
}

function FormField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <Label className="text-xs text-muted-foreground">{label}</Label>
      {children}
    </div>
  );
}

function Toggle({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <NeuSwitch
      checked={checked}
      onChange={onChange}
      className="p-0 gap-0 shrink-0"
    />
  );
}

function QuickModeForm({ name, setName, description, setDescription, category, setCategory, status, setStatus, config, updateConfig }: {
  name: string; setName: (v: string) => void;
  description: string; setDescription: (v: string) => void;
  category: StrategyCategory; setCategory: (v: StrategyCategory) => void;
  status: StrategyStatus; setStatus: (v: StrategyStatus) => void;
  config: StrategyConfig; updateConfig: (p: Partial<StrategyConfig>) => void;
}) {
  return (
    <div className="space-y-6">
      {/* Basic Info */}
      <div className="space-y-3">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Basic Info</h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div className="sm:col-span-2">
            <Label htmlFor="q-name" className="text-xs text-muted-foreground mb-1.5">Name *</Label>
            <Input id="q-name" placeholder="My Trading Strategy" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="sm:col-span-2">
            <Label htmlFor="q-desc" className="text-xs text-muted-foreground mb-1.5">Description</Label>
            <textarea
              id="q-desc"
              placeholder="Brief strategy description..."
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={2}
              className="w-full rounded-lg border border-input bg-transparent px-2.5 py-2 text-sm transition-colors outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30 resize-none"
            />
          </div>
          <FormField label="Category">
            <div className="flex flex-wrap gap-1.5">
              {CATEGORIES.map((c) => (
                <button key={c} onClick={() => setCategory(c)} className={`px-2.5 py-1 rounded-md text-xs font-medium transition-all ${category === c ? CATEGORY_COLORS[c] + " ring-1 ring-current/30" : "bg-muted/50 text-muted-foreground hover:bg-muted"}`}>
                  {c.charAt(0).toUpperCase() + c.slice(1)}
                </button>
              ))}
            </div>
          </FormField>
          <FormField label="Status">
            <div className="flex flex-wrap gap-1.5">
              {STATUSES.map((s) => (
                <button key={s} onClick={() => setStatus(s)} className={`px-2.5 py-1 rounded-md text-xs font-medium transition-all ${status === s ? STATUS_COLORS[s] + " ring-1 ring-current/30" : "bg-muted/50 text-muted-foreground hover:bg-muted"}`}>
                  {s.charAt(0).toUpperCase() + s.slice(1)}
                </button>
              ))}
            </div>
          </FormField>
        </div>
      </div>

      <div className="h-px bg-border" />

      {/* Trade Setup */}
      <div className="space-y-3">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Trade Setup</h3>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
          <FormField label="Trade Direction">
            <select value={config.trade_directionality ?? "standard"} onChange={(e) => updateConfig({ trade_directionality: e.target.value })} className={SELECT_CLASS}>
              <option value="standard">Standard (Straight)</option>
              <option value="inverse">Inverse (Reverse)</option>
            </select>
          </FormField>
          <FormField label="Order Type">
            <select value={config.order_type ?? "market"} onChange={(e) => updateConfig({ order_type: e.target.value })} className={SELECT_CLASS}>
              <option value="market">Market</option>
              <option value="limit">Limit</option>
              <option value="stop">Stop</option>
              <option value="stop_limit">Stop-Limit</option>
            </select>
          </FormField>
          <FormField label="Leverage">
            <Input type="number" step="0.5" min="1" placeholder="1" value={config.leverage_multiplier ?? ""} onChange={(e) => updateConfig({ leverage_multiplier: e.target.value ? Number(e.target.value) : undefined })} />
          </FormField>
        </div>
      </div>

      <div className="h-px bg-border" />

      {/* Capital & Risk */}
      <div className="space-y-3">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Capital & Risk</h3>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
          <FormField label="Capital Per Trade (%)">
            <Input type="number" step="1" min="1" max="100" placeholder="10" value={config.base_capital_pct ?? ""} onChange={(e) => updateConfig({ base_capital_pct: e.target.value ? Number(e.target.value) : undefined })} />
          </FormField>
          <FormField label="Max Global Exposure (%)">
            <Input type="number" step="1" min="1" max="100" placeholder="100" value={config.max_global_exposure_pct ?? ""} onChange={(e) => updateConfig({ max_global_exposure_pct: e.target.value ? Number(e.target.value) : undefined })} />
          </FormField>
          <FormField label="Max Simultaneous Trades">
            <Input type="number" step="1" min="1" placeholder="5" value={config.max_simultaneous_trades ?? ""} onChange={(e) => updateConfig({ max_simultaneous_trades: e.target.value ? Number(e.target.value) : undefined })} />
          </FormField>
          <FormField label="Max Drawdown (%)">
            <Input type="number" step="1" min="1" placeholder="20" value={config.global_drawdown_limit_pct ?? ""} onChange={(e) => updateConfig({ global_drawdown_limit_pct: e.target.value ? Number(e.target.value) : undefined })} />
          </FormField>
          <FormField label="Risk Per Trade (%)">
            <Input type="number" step="0.5" min="0.1" placeholder="2" value={config.risk_per_trade_pct ?? ""} onChange={(e) => updateConfig({ risk_per_trade_pct: e.target.value ? Number(e.target.value) : undefined })} />
          </FormField>
        </div>
      </div>

      <div className="h-px bg-border" />

      {/* SL & TP */}
      <div className="space-y-3">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Stop Loss & Take Profit</h3>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <FormField label="SL Type">
            <select value={config.sl_type ?? "fixed_pct"} onChange={(e) => updateConfig({ sl_type: e.target.value })} className={SELECT_CLASS}>
              <option value="fixed_pct">Fixed %</option>
              <option value="fixed_price">Fixed Price</option>
              <option value="atr_based">ATR-based</option>
              <option value="trailing">Trailing</option>
              <option value="breakeven">Break-even</option>
              <option value="indicator_based">Indicator</option>
              <option value="time_based">Time-based</option>
            </select>
          </FormField>
          <FormField label="SL Value">
            <Input type="number" step="0.5" placeholder="5" value={config.sl_value ?? ""} onChange={(e) => updateConfig({ sl_value: e.target.value ? Number(e.target.value) : undefined })} />
          </FormField>
          <FormField label="TP Type">
            <select value={config.tp_type ?? "fixed_pct"} onChange={(e) => updateConfig({ tp_type: e.target.value })} className={SELECT_CLASS}>
              <option value="fixed_pct">Fixed %</option>
              <option value="rr_based">R:R-based</option>
              <option value="indicator_based">Indicator</option>
              <option value="trailing">Trailing</option>
              <option value="time_based">Time-based</option>
            </select>
          </FormField>
          <FormField label="TP Value">
            <Input type="number" step="0.5" placeholder="10" value={config.tp_value ?? ""} onChange={(e) => updateConfig({ tp_value: e.target.value ? Number(e.target.value) : undefined })} />
          </FormField>
        </div>
      </div>

      <div className="h-px bg-border" />

      {/* Trading Cycle */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Trading Cycle</h3>
          <Toggle checked={config.cycle_enabled ?? false} onChange={(v) => updateConfig({ cycle_enabled: v })} />
        </div>
        {config.cycle_enabled && (
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
            <FormField label="Target PnL (%)">
              <Input type="number" step="0.5" placeholder="5" value={config.cycle_target_pnl_pct ?? ""} onChange={(e) => updateConfig({ cycle_target_pnl_pct: e.target.value ? Number(e.target.value) : undefined })} />
            </FormField>
            <FormField label="Max Trades/Cycle">
              <Input type="number" step="1" min="1" placeholder="10" value={config.cycle_max_trades ?? ""} onChange={(e) => updateConfig({ cycle_max_trades: e.target.value ? Number(e.target.value) : undefined })} />
            </FormField>
            <FormField label="Cycle Stop Loss (%)">
              <Input type="number" step="0.5" placeholder="3" value={config.cycle_stop_loss_pct ?? ""} onChange={(e) => updateConfig({ cycle_stop_loss_pct: e.target.value ? Number(e.target.value) : undefined })} />
            </FormField>
            <FormField label="Timeout (hours)">
              <Input type="number" step="1" placeholder="24" value={config.cycle_timeout_hours ?? ""} onChange={(e) => updateConfig({ cycle_timeout_hours: e.target.value ? Number(e.target.value) : undefined })} />
            </FormField>
            <FormField label="Cooldown (hours)">
              <Input type="number" step="1" placeholder="1" value={config.cycle_cooldown_hours ?? ""} onChange={(e) => updateConfig({ cycle_cooldown_hours: e.target.value ? Number(e.target.value) : undefined })} />
            </FormField>
            <FormField label="Auto-Restart">
              <Toggle checked={config.cycle_auto_restart ?? false} onChange={(v) => updateConfig({ cycle_auto_restart: v })} />
            </FormField>
          </div>
        )}
      </div>
    </div>
  );
}
