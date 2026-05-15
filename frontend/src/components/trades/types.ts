export type TradeStatus =
  | "pending"
  | "open"
  | "partially_filled"
  | "closing"
  | "cancelling"
  | "partially_closed"
  | "closed"
  | "cancelled"
  | "failed";

export const ACTIVE_STATUSES: TradeStatus[] = [
  "pending", "open", "partially_filled", "closing", "cancelling", "partially_closed",
];
export const TERMINAL_STATUSES: TradeStatus[] = ["closed", "cancelled", "failed"];

export interface Trade {
  id: string;
  account_id: string;
  symbol: string;
  side: string;
  order_type: string;
  qty: number;
  filled_qty: number;
  entry_price: number | null;
  avg_fill_price: number | null;
  exit_price: number | null;
  stop_loss_price: number | null;
  take_profit_price: number | null;
  leverage: number;
  status: TradeStatus;
  realized_pnl: number | null;
  realized_pnl_pct: number | null;
  fees: number | null;
  net_pnl: number | null;
  source: "manual" | "cycle";
  source_id: string | null;
  close_reason: string | null;
  version: number;
  opened_at: string | null;
  closed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface TradeListResponse {
  items: Trade[];
  cursor: string | null;
  has_more: boolean;
}

export interface TradeStatsResponse {
  total_trades: number;
  open_count: number;
  win_rate: number;
  avg_pnl: number;
  total_pnl: number;
}

export interface TradeEvent {
  id: number;
  trade_id: string;
  event_type: string;
  old_status: string | null;
  new_status: string | null;
  fill_qty: number | null;
  fill_price: number | null;
  actor: string;
  payload: Record<string, unknown> | null;
  created_at: string;
}

export interface TradeEventsResponse {
  items: TradeEvent[];
  truncated: boolean;
}

export interface TradeFilters {
  account_ids: string[];
  status: TradeStatus[];
  symbol: string;
  side: string;
  from_date: string;
  to_date: string;
}

export type TradeWsEvent =
  | {
      type: "trade.opened";
      trade_id: string;
      account_id: string;
      version: number;
      data: Trade;
    }
  | {
      type: "trade.closed";
      trade_id: string;
      account_id: string;
      version: number;
      symbol: string;
      close_reason: string | null;
      realized_pnl: number | null;
      net_pnl: number | null;
    }
  | {
      type: "trade.partially_closed";
      trade_id: string;
      account_id: string;
      version: number;
      filled_qty: number;
      remaining_qty: number;
      realized_pnl: number | null;
    }
  | {
      type: "trade.close_failed";
      trade_id: string;
      account_id: string;
      version: number;
      previous_status: string;
      error_code: string;
      error_message: string;
    };

export const STATUS_COLORS: Record<TradeStatus | "unknown", string> = {
  open: "green",
  pending: "amber",
  partially_filled: "amber",
  closing: "blue",
  cancelling: "amber",
  partially_closed: "blue",
  closed: "gray",
  failed: "red",
  cancelled: "orange",
  unknown: "gray",
};
