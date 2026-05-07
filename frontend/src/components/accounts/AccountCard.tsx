import { useNavigate } from "@tanstack/react-router";
import type { DashboardCard } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

interface AccountCardProps {
  card: DashboardCard;
  onRefresh: () => void;
}

export function AccountCard({ card, onRefresh }: AccountCardProps) {
  const navigate = useNavigate();

  const statusColor = {
    active: "bg-green-100 text-green-800",
    stale: "bg-amber-100 text-amber-800",
    error: "bg-red-100 text-red-800",
    disabled: "bg-gray-100 text-gray-800",
  }[card.status];

  const pnl = parseFloat(card.total_perp_upl || "0");
  const equity = parseFloat(card.total_equity || "0");
  const todayPnl = parseFloat(card.today_pnl || "0");

  return (
    <div
      className="rounded-lg border p-4 cursor-pointer hover:border-primary transition-colors"
      onClick={() => navigate({ to: "/accounts/$accountId", params: { accountId: card.id } })}
    >
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <h3 className="font-semibold truncate">{card.label}</h3>
          <Badge variant="outline" className="text-xs">
            {card.account_type}
          </Badge>
        </div>
        <span className={`text-xs px-2 py-0.5 rounded-full ${statusColor}`}>
          {card.status}
        </span>
      </div>

      {card.status === "error" && card.last_error && (
        <p className="text-xs text-red-600 mb-2 truncate">{card.last_error}</p>
      )}

      {card.total_equity != null && (
        <div className="space-y-1">
          <div className="flex justify-between">
            <span className="text-sm text-muted-foreground">Equity</span>
            <span className="text-sm font-medium">${equity.toFixed(2)}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-sm text-muted-foreground">Unrealised PnL</span>
            <span className={`text-sm font-medium ${pnl >= 0 ? "text-green-600" : "text-red-600"}`}>
              ${pnl.toFixed(2)}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-sm text-muted-foreground">Today's PnL</span>
            <span className={`text-sm font-medium ${todayPnl >= 0 ? "text-green-600" : "text-red-600"}`}>
              ${todayPnl.toFixed(2)}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-sm text-muted-foreground">Positions</span>
            <span className="text-sm font-medium">{card.positions_count}</span>
          </div>
        </div>
      )}

      {card.last_connected_at && (
        <p className="text-xs text-muted-foreground mt-2">
          Last updated: {new Date(card.last_connected_at).toLocaleTimeString()}
        </p>
      )}
    </div>
  );
}
