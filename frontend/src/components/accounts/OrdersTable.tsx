import type { OpenOrder } from "@/api/client";

interface OrdersTableProps {
  orders: OpenOrder[];
}

export function OrdersTable({ orders }: OrdersTableProps) {
  if (orders.length === 0) {
    return <p className="text-muted-foreground text-center py-8">No open orders</p>;
  }

  return (
    <div className="rounded border overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="bg-muted">
          <tr>
            <th className="text-left p-2">Symbol</th>
            <th className="text-left p-2">Side</th>
            <th className="text-left p-2">Type</th>
            <th className="text-right p-2">Qty</th>
            <th className="text-right p-2">Price</th>
            <th className="text-left p-2">Status</th>
          </tr>
        </thead>
        <tbody>
          {orders.map((o, i) => (
            <tr key={i} className="border-t">
              <td className="p-2 font-medium">{o.symbol}</td>
              <td className="p-2">{o.side}</td>
              <td className="p-2">{o.orderType}{o.stopOrderType ? ` (${o.stopOrderType})` : ""}</td>
              <td className="p-2 text-right">{o.qty}</td>
              <td className="p-2 text-right">{o.price !== "0" ? `$${parseFloat(o.price).toFixed(2)}` : "Market"}</td>
              <td className="p-2">{o.orderStatus}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
