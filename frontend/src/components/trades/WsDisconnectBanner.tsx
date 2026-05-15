export function WsDisconnectBanner({ lastUpdated }: { lastUpdated: string | null }) {
  return (
    <div className="rounded-md border border-amber-500/30 bg-amber-500/10 px-4 py-2 text-sm text-amber-400">
      <p className="font-medium">Real-time updates unavailable — Reconnecting...</p>
      {lastUpdated && (
        <p className="text-xs text-amber-400/70 mt-0.5">
          Last updated {new Date(lastUpdated).toLocaleTimeString()}
        </p>
      )}
    </div>
  );
}
