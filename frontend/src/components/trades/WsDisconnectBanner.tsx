export function WsDisconnectBanner({ lastUpdated }: { lastUpdated: number | null }) {
  return (
    <div role="alert" className="rounded-xl border border-amber-500/30 bg-amber-500/5 backdrop-blur-sm px-4 py-3 text-sm text-amber-400">
      <p className="font-semibold text-xs uppercase tracking-wide">Real-time updates unavailable — Reconnecting...</p>
      {lastUpdated && (
        <p className="text-[10px] text-amber-400/70 mt-1 uppercase tracking-wide font-medium">
          Last updated {new Date(lastUpdated).toLocaleTimeString()}
        </p>
      )}
    </div>
  );
}
