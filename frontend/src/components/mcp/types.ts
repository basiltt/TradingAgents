/**
 * Type definitions for the MCP (Model Context Protocol) operator console.
 *
 * Mirrors the backend control-plane contract at /api/v1/mcp/*. The MCP server
 * lets an external AI agent drive the app; this console is where the operator
 * turns it on/off, manages which tools are exposed (to keep the model's context
 * window from overflowing), manages the access token, and reviews the
 * agent's config-change proposals before they touch live trading.
 */

/** Capability tier — an ordered ceiling on what the agent may do. */
export type CapabilityTier = "READ_ONLY" | "BACKTEST" | "MUTATING_DEMO" | "LIVE_MONEY";

/** Risk class of an individual tool. */
export type SafetyClass = "read_only" | "backtest" | "live_money";

/** Persisted MCP configuration (GET /api/v1/mcp/config). */
export interface MCPConfig {
  enabled: boolean;
  capability_tier: CapabilityTier;
  enabled_groups: string[];
  enabled_tools: Record<string, boolean>;
  safe_mode_flags: Record<string, boolean>;
  row_version: number;
  bind_host: string;
  has_token: boolean;
}

/** Runtime status (GET /api/v1/mcp/status). */
export interface MCPStatus {
  state: "running" | "off";
  enabled: boolean;
  active_tools: number;
  pending_proposals: number;
  last_error_at: string | null;
}

/** One tool in the budget catalog (GET /api/v1/mcp/registry). */
export interface MCPToolEntry {
  name: string;
  group: string;
  safety_class: SafetyClass;
  /** Estimated model-context tokens this tool consumes when advertised. */
  est_tokens: number;
  enabled: boolean;
  /** Backing service present AND within the capability-tier ceiling. */
  available: boolean;
  mutating: boolean;
  exchange_facing: boolean;
  description: string;
}

/** Per-group rollup in the budget catalog. */
export interface MCPGroupRollup {
  est_tokens: number;
  tool_count: number;
  enabled_count: number;
}

/** Full budget catalog (GET /api/v1/mcp/registry). */
export interface MCPRegistry {
  tools: MCPToolEntry[];
  groups: Record<string, MCPGroupRollup>;
  /** preset name → the tool names it selects. */
  presets: Record<string, string[]>;
  total_est_tokens: number;
  selected_est_tokens: number;
  capability_tier: CapabilityTier;
  enabled_groups: string[];
  row_version: number;
}

/** A config-change proposal awaiting human approval (money path).
 *  Matches the mcp_proposals row shape returned by ProposalRepository. */
export interface MCPProposal {
  id: string;
  sweep_id?: string | null;
  status: "pending" | "approved" | "rejected" | "expired" | "applied" | "reverted";
  target_schedule_id?: string | null;
  target_config_index?: number | null;
  /** The full proposed AutoTradeConfig. */
  config: Record<string, unknown>;
  /** The field-level diff vs the live config (what would change). */
  diff: Record<string, unknown>;
  /** Robustness verdict + expected uplift from the sweep ranker. */
  risk_verdict?: Record<string, unknown> | null;
  approver?: string | null;
  applied_config_version?: string | null;
  config_schema_version?: number | null;
  created_at?: string | null;
  expires_at?: string | null;
}

/** One audit-log entry (GET /api/v1/mcp/audit). */
export interface MCPAuditEntry {
  seq: number;
  tool_name?: string | null;
  principal?: string | null;
  mutating?: boolean;
  outcome?: string | null;
  created_at?: string | null;
  [key: string]: unknown;
}

/** Known tool-group display metadata (purely cosmetic; unknown groups fall back). */
export const GROUP_LABELS: Record<string, string> = {
  scans: "Scans",
  accounts: "Accounts",
  positions: "Positions",
  trades: "Trades",
  portfolio: "Portfolio",
  analytics: "Analytics",
  scheduled: "Scheduled",
  strategies: "Strategies",
  symbols: "Symbols",
  backtest: "Backtesting",
  debug: "Debug",
  optimizer: "Optimizer",
  advanced: "Advanced",
};

export const PRESET_LABELS: Record<string, string> = {
  minimal: "Minimal",
  read_only: "Read-only",
  backtest_only: "Backtest + Optimize",
  standard: "Standard",
  full: "Full (no live money)",
};
