import { useEffect, useState } from "react";
import { useAppDispatch, useAppSelector } from "@/store";
import {
  fetchAIManagerStatus,
  fetchConfig,
  fetchDecisions,
  fetchPerformance,
  enableAIManager,
  disableAIManager,
  pauseAIManager,
  resumeAIManager,
  killAIManager,
  resetKillSwitch,
} from "@/store/ai-manager-slice";
import type { RootState } from "@/store";
import { NeuBadge } from "@/design-system/neumorphism/display";
import { NeuButton } from "@/design-system/neumorphism/inputs";
import { Shield, ShieldAlert, Zap, Calendar, Activity } from "lucide-react";

interface AIMonitorPanelProps {
  accountId: string;
}

const STATE_TONES: Record<string, "success" | "warning" | "accent" | "danger" | "neutral"> = {
  sleeping: "neutral",
  monitoring: "accent",
  analyzing: "warning",
  executing: "success",
  paused: "warning",
  error: "danger",
};

export function AIMonitorPanel({ accountId }: AIMonitorPanelProps) {
  const dispatch = useAppDispatch();
  const status = useAppSelector((s: RootState) => s.aiManager.statusByAccount[accountId]);
  const config = useAppSelector((s: RootState) => s.aiManager.configByAccount[accountId]);
  const decisions = useAppSelector((s: RootState) => s.aiManager.decisionsbyAccount[accountId] || []);
  const cursor = useAppSelector((s: RootState) => s.aiManager.decisionCursors[accountId]);
  const performance = useAppSelector((s: RootState) => s.aiManager.performanceByAccount[accountId]);
  const loading = useAppSelector((s: RootState) => s.aiManager.loading);

  const [perfPeriod, setPerfPeriod] = useState("7d");

  // Load all AI Manager details on mount
  useEffect(() => {
    dispatch(fetchAIManagerStatus(accountId));
    dispatch(fetchConfig(accountId));
    dispatch(fetchDecisions({ accountId, limit: 15 }));
    dispatch(fetchPerformance({ accountId, period: perfPeriod }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dispatch, accountId]);

  // Periodic live refresh for status (so panel stays current without relying only on WS)
  useEffect(() => {
    const interval = setInterval(() => {
      dispatch(fetchAIManagerStatus(accountId));
    }, 30000);
    return () => clearInterval(interval);
  }, [dispatch, accountId]);

  // Handle performance period change
  const handlePeriodChange = (period: string) => {
    setPerfPeriod(period);
    dispatch(fetchPerformance({ accountId, period }));
  };

  const handleLoadMoreDecisions = () => {
    if (cursor) {
      dispatch(fetchDecisions({ accountId, limit: 15, cursor, append: true }));
    }
  };

  if (loading["status"] && !status) {
    return (
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 animate-pulse">
        <div className="h-64 rounded-2xl bg-muted/10" style={{ boxShadow: "var(--neu-shadow-inset)" }} />
        <div className="h-64 rounded-2xl bg-muted/10" style={{ boxShadow: "var(--neu-shadow-inset)" }} />
        <div className="md:col-span-2 h-96 rounded-2xl bg-muted/10" style={{ boxShadow: "var(--neu-shadow-inset)" }} />
      </div>
    );
  }

  // Not configured / Disabled state onboarding
  if (!status) {
    return (
      <div
        className="rounded-2xl p-8 text-center space-y-6 max-w-xl mx-auto my-8"
        style={{
          background: "var(--neu-surface-base)",
          boxShadow: "var(--neu-shadow-pill)",
        }}
      >
        <div className="mx-auto w-16 h-16 rounded-2xl flex items-center justify-center"
             style={{ background: "var(--neu-surface-deep)", boxShadow: "var(--neu-shadow-inset)" }}>
          <Zap className="w-8 h-8 text-muted-foreground/40 animate-pulse" />
        </div>
        <div className="space-y-2">
          <h3 className="text-lg font-bold">AI Manager Not Active</h3>
          <p className="text-sm text-muted-foreground/60 leading-relaxed">
            The AI Manager acts as an intelligent safety controller. It actively monitors risk metrics, evaluates position health, dynamically adjusts take-profits/stop-losses, and enforces emergency circuit breakers.
          </p>
        </div>
        <div className="pt-2">
          <NeuButton
            variant="primary"
            size="md"
            disabled={loading["enable"]}
            onClick={() =>
              dispatch(enableAIManager(accountId)).then(() => {
                dispatch(fetchAIManagerStatus(accountId));
                dispatch(fetchConfig(accountId));
                dispatch(fetchDecisions({ accountId, limit: 15 }));
                dispatch(fetchPerformance({ accountId, period: perfPeriod }));
              })
            }
          >
            {loading["enable"] ? "Activating AI..." : "Enable AI Manager"}
          </NeuButton>
        </div>
      </div>
    );
  }

  const fsmTone = STATE_TONES[status.state] || "neutral";

  return (
    <div className="space-y-6">
      {/* Top Section: Status Cards & Quick Performance */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* FSM Status & Controls */}
        <div
          className="rounded-2xl p-5 space-y-4 md:col-span-2"
          style={{
            background: "var(--neu-surface-base)",
            boxShadow: "var(--neu-shadow-pill)",
          }}
        >
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div className="space-y-1">
              <span className="text-[10px] text-muted-foreground/60 uppercase tracking-widest font-semibold block">AI ENGINE Lifecycle</span>
              <h3 className="text-lg font-bold flex items-center gap-2">
                FSM State:
                <NeuBadge tone={fsmTone} variant="soft" dot pulse={status.state === "monitoring" || status.state === "executing"}>
                  {status.state}
                </NeuBadge>
              </h3>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {status.enabled ? (
                <>
                  {status.state === "paused" ? (
                    <NeuButton
                      variant="primary"
                      size="sm"
                      disabled={loading["resume"]}
                      onClick={() => dispatch(resumeAIManager(accountId))}
                    >
                      Resume
                    </NeuButton>
                  ) : (
                    <NeuButton
                      variant="secondary"
                      size="sm"
                      disabled={loading["pause"]}
                      onClick={() => dispatch(pauseAIManager(accountId))}
                    >
                      Pause
                    </NeuButton>
                  )}
                  <NeuButton
                    variant="danger"
                    size="sm"
                    disabled={loading["kill"]}
                    onClick={() => dispatch(killAIManager(accountId))}
                  >
                    Kill Switch
                  </NeuButton>
                  <NeuButton
                    variant="secondary"
                    size="sm"
                    disabled={loading["disable"]}
                    onClick={() => dispatch(disableAIManager(accountId))}
                  >
                    Disable AI
                  </NeuButton>
                </>
              ) : (
                <NeuButton
                  variant="primary"
                  size="sm"
                  disabled={loading["enable"]}
                  onClick={() =>
                    dispatch(enableAIManager(accountId)).then(() => {
                      dispatch(fetchAIManagerStatus(accountId));
                      dispatch(fetchConfig(accountId));
                      dispatch(fetchDecisions({ accountId, limit: 15 }));
                      dispatch(fetchPerformance({ accountId, period: perfPeriod }));
                    })
                  }
                >
                  Enable AI
                </NeuButton>
              )}
            </div>
          </div>

          {/* Kill Switch Warning */}
          {status.kill_switch && (
            <div
              className="rounded-xl p-3 flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-red-400 border border-red-500/10"
              style={{
                background: "var(--neu-surface-deep)",
                boxShadow: "var(--neu-shadow-inset)",
              }}
            >
              <div className="flex items-center gap-2 text-xs">
                <ShieldAlert className="w-5 h-5 shrink-0" />
                <div>
                  <span className="font-semibold block">System Kill Switch Fired</span>
                  <span className="text-muted-foreground/60">Autonomous execution halted. Safety protocol active.</span>
                </div>
              </div>
              <NeuButton
                variant="danger"
                size="sm"
                disabled={loading["resetKill"]}
                onClick={() => dispatch(resetKillSwitch(accountId))}
              >
                Reset Switch
              </NeuButton>
            </div>
          )}

          {/* Telemetry Metrics Grid */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 pt-2">
            <div
              className="rounded-xl p-3 text-center space-y-1"
              style={{
                background: "var(--neu-surface-deep)",
                boxShadow: "var(--neu-shadow-inset)",
              }}
            >
              <span className="text-[10px] text-muted-foreground/60 uppercase tracking-widest font-semibold block">Actions Today</span>
              <span className="text-lg font-bold font-mono">{status.actions_today}</span>
            </div>
            <div
              className="rounded-xl p-3 text-center space-y-1"
              style={{
                background: "var(--neu-surface-deep)",
                boxShadow: "var(--neu-shadow-inset)",
              }}
            >
              <span className="text-[10px] text-muted-foreground/60 uppercase tracking-widest font-semibold block">Action Budget</span>
              <span className="text-lg font-bold font-mono">{status.budget_remaining.actions} left</span>
            </div>
            <div
              className="rounded-xl p-3 text-center space-y-1"
              style={{
                background: "var(--neu-surface-deep)",
                boxShadow: "var(--neu-shadow-inset)",
              }}
            >
              <span className="text-[10px] text-muted-foreground/60 uppercase tracking-widest font-semibold block">Breaker Trips</span>
              <span className={`text-lg font-bold font-mono ${status.circuit_breaker.active ? "text-red-400" : ""}`}>
                {status.circuit_breaker.count}{status.circuit_breaker.active ? " ⚠" : ""}
              </span>
            </div>
            <div
              className="rounded-xl p-3 text-center space-y-1"
              style={{
                background: "var(--neu-surface-deep)",
                boxShadow: "var(--neu-shadow-inset)",
              }}
            >
              <span className="text-[10px] text-muted-foreground/60 uppercase tracking-widest font-semibold block">Degradation</span>
              <span className="text-lg font-bold font-mono">Tier {status.degradation_tier}</span>
            </div>
          </div>
        </div>

        {/* AI Performance Panel */}
        <div
          className="rounded-2xl p-5 space-y-4"
          style={{
            background: "var(--neu-surface-base)",
            boxShadow: "var(--neu-shadow-pill)",
          }}
        >
          <div className="flex items-center justify-between">
            <h4 className="text-xs uppercase tracking-widest font-semibold text-muted-foreground/60">Performance</h4>
            <div className="flex gap-1">
              {["1d", "7d", "30d"].map((p) => (
                <button
                  key={p}
                  onClick={() => handlePeriodChange(p)}
                  className={`text-[10px] px-2.5 py-1 rounded-md font-mono transition-all ${
                    perfPeriod === p
                      ? "bg-[color-mix(in_oklch,var(--neu-accent)_12%,var(--neu-surface-base))] text-[var(--neu-accent)] font-semibold"
                      : "text-muted-foreground/50 hover:text-muted-foreground"
                  }`}
                >
                  {p}
                </button>
              ))}
            </div>
          </div>

          {performance ? (
            <div className="space-y-4 pt-1">
              <div className="flex items-center justify-between border-b border-border/10 pb-2">
                <span className="text-xs text-muted-foreground/60">Win Rate</span>
                <span className="text-lg font-bold font-mono">
                  {((performance.win_rate ?? 0) * 100).toFixed(1)}%
                </span>
              </div>
              <div className="flex items-center justify-between border-b border-border/10 pb-2">
                <span className="text-xs text-muted-foreground/60">Net Profit</span>
                <span className={`text-sm font-bold font-mono ${performance.net_pnl >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                  {performance.net_pnl >= 0 ? "+" : ""}${performance.net_pnl.toFixed(2)}
                </span>
              </div>
              <div className="flex items-center justify-between text-xs text-muted-foreground/60">
                <span>Wins / Losses</span>
                <span className="font-mono text-muted-foreground/80">
                  {performance.wins} W · {performance.losses} L
                </span>
              </div>
            </div>
          ) : (
            <div className="h-28 flex items-center justify-center">
              <span className="text-xs text-muted-foreground/40 font-mono">No telemetry in this period</span>
            </div>
          )}
        </div>
      </div>

      {/* Middle Section: Emergency Settings & Threshold Limits */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Emergency Monitor Card */}
        <div
          className="rounded-2xl p-5 space-y-4"
          style={{
            background: "var(--neu-surface-base)",
            boxShadow: "var(--neu-shadow-pill)",
          }}
        >
          <div className="flex items-center gap-2">
            <Shield className="w-4 h-4 text-orange-400" />
            <h4 className="text-xs uppercase tracking-widest font-semibold text-muted-foreground/80">Emergency Telemetry & Targets</h4>
          </div>

          <div className="space-y-3.5">
            {/* Reference Equity and Cooldown */}
            <div className="grid grid-cols-2 gap-3">
              <div
                className="rounded-xl p-3 space-y-1.5"
                style={{
                  background: "var(--neu-surface-deep)",
                  boxShadow: "var(--neu-shadow-inset)",
                }}
              >
                <span className="text-[10px] text-muted-foreground/50 uppercase tracking-wider block">Reference Equity</span>
                <span className="text-sm font-bold font-mono block">
                  {status.emergency_ref_equity != null ? `$${status.emergency_ref_equity.toFixed(2)}` : "—"}
                </span>
              </div>
              <div
                className="rounded-xl p-3 space-y-1.5"
                style={{
                  background: "var(--neu-surface-deep)",
                  boxShadow: "var(--neu-shadow-inset)",
                }}
              >
                <span className="text-[10px] text-muted-foreground/50 uppercase tracking-wider block">Cooldown Timer</span>
                <span className={`text-xs font-bold block ${status.emergency_cooldown_until ? "text-orange-400" : "text-muted-foreground/60"}`}>
                  {status.emergency_cooldown_until
                    ? new Date(status.emergency_cooldown_until).toLocaleTimeString()
                    : "Inactive"}
                </span>
              </div>
            </div>

            {/* Locked & Excluded symbols */}
            <div className="space-y-2.5">
              <div className="flex items-start justify-between text-xs gap-3">
                <span className="text-muted-foreground/60 pt-0.5">Locked Positions</span>
                <div className="flex flex-wrap gap-1 justify-end max-w-[70%]">
                  {config?.locked_positions && (config.locked_positions as string[]).length > 0 ? (
                    (config.locked_positions as string[]).map((sym) => (
                      <NeuBadge key={sym} tone="accent" variant="outline" size="sm">
                        {sym}
                      </NeuBadge>
                    ))
                  ) : (
                    <span className="text-muted-foreground/40 font-mono text-[10px]">None locked</span>
                  )}
                </div>
              </div>
              <div className="flex items-start justify-between text-xs gap-3">
                <span className="text-muted-foreground/60 pt-0.5">Excluded Symbols</span>
                <div className="flex flex-wrap gap-1 justify-end max-w-[70%]">
                  {config?.excluded_symbols && (config.excluded_symbols as string[]).length > 0 ? (
                    (config.excluded_symbols as string[]).map((sym) => (
                      <NeuBadge key={sym} tone="neutral" variant="ghost" size="sm">
                        {sym}
                      </NeuBadge>
                    ))
                  ) : (
                    <span className="text-muted-foreground/40 font-mono text-[10px]">None excluded</span>
                  )}
                </div>
              </div>
            </div>

            {/* Emergency Closed Trades */}
            <div className="space-y-2">
              <span className="text-[10px] text-muted-foreground/60 uppercase tracking-widest font-semibold block">Emergency Closed Symbols (Last 30s)</span>
              <div
                className="rounded-xl p-3 min-h-[4.5rem] flex flex-col justify-center space-y-1.5"
                style={{
                  background: "var(--neu-surface-deep)",
                  boxShadow: "var(--neu-shadow-inset)",
                }}
              >
                {status.emergency_closed_symbols && Object.keys(status.emergency_closed_symbols).length > 0 ? (
                  Object.entries(status.emergency_closed_symbols).map(([sym, ts_str]) => (
                    <div key={sym} className="flex items-center justify-between text-xs">
                      <span className="font-mono font-semibold text-orange-400">{sym}</span>
                      <span className="text-[10px] text-muted-foreground/40 font-mono">
                        {new Date(ts_str as string).toLocaleTimeString()}
                      </span>
                    </div>
                  ))
                ) : (
                  <span className="text-xs text-muted-foreground/40 font-mono text-center">No recent emergency shutdowns</span>
                )}
              </div>
            </div>
          </div>
        </div>

        {/* AI Thresholds Config Card */}
        <div
          className="rounded-2xl p-5 space-y-4"
          style={{
            background: "var(--neu-surface-base)",
            boxShadow: "var(--neu-shadow-pill)",
          }}
        >
          <div className="flex items-center gap-2">
            <Activity className="w-4 h-4 text-[var(--neu-accent)]" />
            <h4 className="text-xs uppercase tracking-widest font-semibold text-muted-foreground/80">AI Evaluation Thresholds</h4>
          </div>

          {config ? (
            <div className="grid grid-cols-2 gap-x-4 gap-y-3.5 text-xs">
              <div className="flex flex-col gap-1 border-b border-border/5 pb-2">
                <span className="text-muted-foreground/50 text-[10px]">Risk Tolerance</span>
                <span className="font-semibold capitalize text-muted-foreground/80">{String(config.risk_tolerance)}</span>
              </div>
              <div className="flex flex-col gap-1 border-b border-border/5 pb-2">
                <span className="text-muted-foreground/50 text-[10px]">Evaluation Interval</span>
                <span className="font-semibold font-mono text-muted-foreground/80">{String(config.evaluation_interval_s)}s</span>
              </div>
              <div className="flex flex-col gap-1 border-b border-border/5 pb-2">
                <span className="text-muted-foreground/50 text-[10px]">Confidence Threshold</span>
                <span className="font-semibold font-mono text-muted-foreground/80">{Math.round((config.confidence_threshold as number) * 100)}%</span>
              </div>
              <div className="flex flex-col gap-1 border-b border-border/5 pb-2">
                <span className="text-muted-foreground/50 text-[10px]">Max Daily Loss Limit</span>
                <span className="font-semibold font-mono text-muted-foreground/80">{String(config.max_daily_loss_pct)}%</span>
              </div>
              <div className="flex flex-col gap-1 border-b border-border/5 pb-2">
                <span className="text-muted-foreground/50 text-[10px]">Max Action Limit (24h / 1h)</span>
                <span className="font-semibold font-mono text-muted-foreground/80">{String(config.max_daily_actions)} / {String(config.max_hourly_actions)}</span>
              </div>
              <div className="flex flex-col gap-1 border-b border-border/5 pb-2">
                <span className="text-muted-foreground/50 text-[10px]">Daily Profit Target</span>
                <span className="font-semibold font-mono text-muted-foreground/80">
                  {config.daily_profit_target_pct != null ? `${config.daily_profit_target_pct}%` : "None"}
                </span>
              </div>
              <div className="flex flex-col gap-1 border-b border-border/5 pb-2 col-span-2">
                <span className="text-muted-foreground/50 text-[10px]">Max Single Decision Loss Limit</span>
                <span className="font-semibold font-mono text-muted-foreground/80">{String(config.max_single_decision_loss_pct)}%</span>
              </div>
            </div>
          ) : (
            <div className="h-44 flex items-center justify-center">
              <span className="text-xs text-muted-foreground/40 font-mono">No thresholds data available</span>
            </div>
          )}
        </div>
      </div>

      {/* Bottom Section: Activity Log / Decisions timeline */}
      <div
        className="rounded-2xl p-5 space-y-4"
        style={{
          background: "var(--neu-surface-base)",
          boxShadow: "var(--neu-shadow-pill)",
        }}
      >
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Calendar className="w-4 h-4 text-emerald-400" />
            <h4 className="text-xs uppercase tracking-widest font-semibold text-muted-foreground/80">AI Decisions Log & Audit Trail</h4>
          </div>
          {loading["decisions"] && (
            <div className="w-4 h-4 border-2 border-muted-foreground/30 border-t-muted-foreground rounded-full animate-spin" />
          )}
        </div>

        {decisions.length > 0 ? (
          <div className="space-y-3">
            <div className="overflow-x-auto rounded-xl">
              <table className="w-full text-xs text-left">
                <thead>
                  <tr
                    className="text-muted-foreground/50 font-semibold uppercase tracking-wider border-b border-border/5 text-[10px]"
                    style={{ background: "color-mix(in oklch, var(--neu-highlight) 6%, transparent)" }}
                  >
                    <th className="py-2.5 px-3">Timestamp</th>
                    <th className="py-2.5 px-3">Action Type</th>
                    <th className="py-2.5 px-3">Position Target</th>
                    <th className="py-2.5 px-3 text-right">Confidence</th>
                    <th className="py-2.5 px-3 text-center">Outcome</th>
                    <th className="py-2.5 px-3 max-w-[280px]">Reasoning</th>
                  </tr>
                </thead>
                <tbody>
                  {decisions.map((dec) => {
                    const outLabel = dec.outcome_label || "";
                    const outTone =
                      outLabel === "profitable" || outLabel === "win" ? "success" :
                      outLabel === "loss" ? "danger" : "neutral";

                    return (
                      <tr key={dec.id} className="border-b border-border/5 hover:bg-muted-foreground/5 transition-colors">
                        <td className="py-2.5 px-3 font-mono text-[10px] text-muted-foreground/75 whitespace-nowrap">
                          {new Date(dec.timestamp).toLocaleString()}
                        </td>
                        <td className="py-2.5 px-3 font-semibold uppercase tracking-wide text-muted-foreground/80">
                          {dec.action_taken?.action || "HOLD"}
                        </td>
                        <td className="py-2.5 px-3 font-mono font-semibold text-muted-foreground/90">
                          {dec.action_taken?.symbol || "—"}
                        </td>
                        <td className="py-2.5 px-3 text-right font-mono text-muted-foreground/70">
                          {(dec.confidence * 100).toFixed(0)}%
                        </td>
                        <td className="py-2.5 px-3 text-center">
                          {dec.outcome_label ? (
                            <NeuBadge tone={outTone} variant="ghost" size="sm">
                              {outLabel}
                            </NeuBadge>
                          ) : (
                            <span className="text-muted-foreground/30 font-mono">—</span>
                          )}
                        </td>
                        <td className="py-2.5 px-3 text-muted-foreground/60 max-w-[280px] break-words">
                          {dec.reasoning}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {cursor && (
              <div className="pt-2 text-center">
                <NeuButton
                  variant="soft-tonal"
                  size="sm"
                  disabled={loading["decisions"]}
                  onClick={handleLoadMoreDecisions}
                >
                  {loading["decisions"] ? "Loading..." : "Load More Decisions"}
                </NeuButton>
              </div>
            )}
          </div>
        ) : (
          <div
            className="rounded-xl p-8 text-center space-y-2"
            style={{
              background: "var(--neu-surface-deep)",
              boxShadow: "var(--neu-shadow-inset)",
            }}
          >
            <Activity className="w-8 h-8 mx-auto text-muted-foreground/20" />
            <p className="text-xs text-muted-foreground/40 font-mono">No autonomous actions taken yet</p>
          </div>
        )}
      </div>
    </div>
  );
}
