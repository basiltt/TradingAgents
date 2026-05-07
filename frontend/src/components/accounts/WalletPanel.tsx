import type { WalletBalance } from "@/api/client";

interface WalletPanelProps {
  wallet: WalletBalance;
}

export function WalletPanel({ wallet }: WalletPanelProps) {
  if (!wallet.coin.length) {
    return <p className="text-muted-foreground text-center py-8">No wallet data</p>;
  }

  return (
    <div className="rounded border">
      <table className="w-full text-sm">
        <thead className="bg-muted">
          <tr>
            <th className="text-left p-2">Coin</th>
            <th className="text-right p-2">Balance</th>
            <th className="text-right p-2">Equity</th>
            <th className="text-right p-2">Unrealised PnL</th>
          </tr>
        </thead>
        <tbody>
          {wallet.coin.map((c, i) => (
            <tr key={i} className="border-t">
              <td className="p-2 font-medium">{c.coin}</td>
              <td className="p-2 text-right">{parseFloat(c.walletBalance || "0").toFixed(4)}</td>
              <td className="p-2 text-right">{parseFloat(c.equity || "0").toFixed(4)}</td>
              <td className="p-2 text-right">{parseFloat(c.unrealisedPnl || "0").toFixed(4)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
