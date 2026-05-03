export interface TradeCardData {
  action?: string;
  rating?: string;
  confidence?: number;
  entryPrice?: number;
  stopLoss?: number;
  stopLoss2?: number;
  takeProfit1?: number;
  takeProfit2?: number;
  takeProfit3?: number;
  riskRewardRatio?: number;
  positionSizing?: string;
  timeHorizon?: string;
  reasoning?: string;
  executiveSummary?: string;
  leverage?: number;
}

function extractField(md: string, key: string): string | undefined {
  const re = new RegExp(`\\*\\*${key}\\*\\*:\\s*(.+)`, "i");
  const m = md.match(re);
  return m?.[1]?.trim() || undefined;
}

function extractNumber(md: string, key: string): number | undefined {
  const raw = extractField(md, key);
  if (!raw) return undefined;
  const n = parseFloat(raw);
  return Number.isFinite(n) ? n : undefined;
}

function tryParseJson(text: string): Record<string, unknown> | null {
  const trimmed = text.trim();
  const start = trimmed.indexOf("{");
  const end = trimmed.lastIndexOf("}");
  if (start === -1 || end === -1) return null;
  try {
    return JSON.parse(trimmed.slice(start, end + 1));
  } catch {
    return null;
  }
}

function fromJson(obj: Record<string, unknown>): TradeCardData {
  const asNum = (v: unknown): number | undefined => {
    if (typeof v === "number" && Number.isFinite(v)) return v;
    if (typeof v === "string") { const n = parseFloat(v); return Number.isFinite(n) ? n : undefined; }
    return undefined;
  };
  const asStr = (v: unknown): string | undefined =>
    typeof v === "string" && v.length > 0 ? v : undefined;
  const asArr = (v: unknown): number[] => {
    if (!Array.isArray(v)) return [];
    return v.map(asNum).filter((n): n is number => n != null);
  };

  const action = asStr(obj.trade_type) ?? asStr(obj.action) ?? asStr(obj.Action);
  const sls = asArr(obj.stop_losses ?? obj.stopLosses ?? obj.stop_loss_levels);
  const tps = asArr(obj.take_profits ?? obj.takeProfits ?? obj.take_profit_levels);

  return {
    action: action ? action.charAt(0).toUpperCase() + action.slice(1).toLowerCase() : undefined,
    confidence: asNum(obj.confidence) ?? asNum(obj.conviction),
    entryPrice: asNum(obj.entry_price) ?? asNum(obj.entryPrice) ?? asNum(obj.entry),
    stopLoss: sls[0] ?? asNum(obj.stop_loss) ?? asNum(obj.stopLoss),
    stopLoss2: sls[1],
    takeProfit1: tps[0] ?? asNum(obj.take_profit) ?? asNum(obj.takeProfit),
    takeProfit2: tps[1],
    takeProfit3: tps[2],
    riskRewardRatio: asNum(obj.risk_reward_ratio) ?? asNum(obj.riskRewardRatio) ?? asNum(obj.risk_reward),
    positionSizing: asStr(obj.position_sizing) ?? asStr(obj.positionSizing) ?? asStr(obj.position_size),
    timeHorizon: asStr(obj.time_horizon) ?? asStr(obj.timeHorizon),
    reasoning: asStr(obj.reasoning) ?? asStr(obj.rationale),
    leverage: asNum(obj.leverage),
  };
}

function parseMarkdownTrader(trader: string): Partial<TradeCardData> {
  return {
    action: extractField(trader, "Action"),
    confidence: extractNumber(trader, "Confidence"),
    entryPrice: extractNumber(trader, "Entry Price"),
    stopLoss: extractNumber(trader, "Stop Loss"),
    stopLoss2: extractNumber(trader, "Stop Loss 2"),
    takeProfit1: extractNumber(trader, "Take Profit 1"),
    takeProfit2: extractNumber(trader, "Take Profit 2"),
    takeProfit3: extractNumber(trader, "Take Profit 3"),
    riskRewardRatio: extractNumber(trader, "Risk/Reward Ratio"),
    positionSizing: extractField(trader, "Position Sizing"),
    timeHorizon: extractField(trader, "Time Horizon"),
    reasoning: extractField(trader, "Reasoning"),
  };
}

function parseMarkdownPm(pm: string): Partial<TradeCardData> {
  return {
    rating: extractField(pm, "Rating"),
    confidence: extractNumber(pm, "Confidence"),
    executiveSummary: extractField(pm, "Executive Summary"),
    timeHorizon: extractField(pm, "Time Horizon"),
  };
}

function merge(...sources: Partial<TradeCardData>[]): TradeCardData {
  const result: TradeCardData = {};
  for (const s of sources) {
    for (const [k, v] of Object.entries(s)) {
      if (v != null && (result as Record<string, unknown>)[k] == null) {
        (result as Record<string, unknown>)[k] = v;
      }
    }
  }
  return result;
}

export function parseTradeCard(reports: Record<string, string>): TradeCardData | null {
  const trader = reports.trader ?? "";
  const pm = reports.portfolio_manager ?? reports.final_trade_decision ?? "";

  if (!trader && !pm) return null;

  const traderJson = tryParseJson(trader);
  const pmJson = tryParseJson(pm);

  const traderData = traderJson ? fromJson(traderJson) : parseMarkdownTrader(trader);
  const pmData = pmJson ? fromJson(pmJson) : parseMarkdownPm(pm);

  const merged = merge(pmData, traderData);

  if (!merged.action && !merged.rating) return null;

  return merged;
}
