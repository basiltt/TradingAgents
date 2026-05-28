import { useMemo, useEffect } from "react";
import { useAppDispatch, useAppSelector } from "@/store";
import { fetchCapabilities } from "@/store/ai-manager-slice";
import type { CapabilityStatus } from "@/store/ai-manager-slice";
import { makeSelectCapabilities } from "@/store/ai-manager-selectors";
import { Cpu } from "lucide-react";

interface CapabilitiesGridProps { accountId: string; }

const STATUS_COLORS: Record<string, string> = {
  healthy: "border-emerald-500/40 bg-emerald-500/5",
  degraded: "border-amber-500/40 bg-amber-500/5",
  failed: "border-red-500/40 bg-red-500/5",
  disabled: "border-zinc-500/20 bg-zinc-500/5 opacity-50",
};

const STATUS_DOT: Record<string, string> = {
  healthy: "bg-emerald-400",
  degraded: "bg-amber-400",
  failed: "bg-red-400",
  disabled: "bg-zinc-500",
};

export default function CapabilitiesGrid({ accountId }: CapabilitiesGridProps) {
  const dispatch = useAppDispatch();
  const selectCaps = useMemo(() => makeSelectCapabilities(accountId), [accountId]);
  const capabilities = useAppSelector(selectCaps);
  const fsmState = useAppSelector(s => s.aiManager.statusByAccount[accountId]?.state);

  useEffect(() => {
    if (fsmState && fsmState !== "sleeping") {
      dispatch(fetchCapabilities(accountId));
    }
  }, [dispatch, accountId, fsmState]);

  const isMuted = fsmState === "sleeping" || fsmState === "paused";

  return (
    <div className="rounded-2xl p-5 space-y-3" style={{ background: "var(--neu-surface-base)", boxShadow: "var(--neu-shadow-pill)" }}>
      <div className="flex items-center gap-2">
        <Cpu className="w-4 h-4 text-sky-400" />
        <h4 className="text-xs uppercase tracking-widest font-semibold text-muted-foreground/80">Capabilities</h4>
      </div>

      {capabilities.length === 0 ? (
        <p className="text-xs text-muted-foreground/40 text-center py-4">Loading capabilities...</p>
      ) : (
        <div className={`grid grid-cols-[repeat(auto-fill,minmax(180px,1fr))] gap-2 ${isMuted ? "opacity-50" : ""}`}>
          {capabilities.map(cap => (
            <CapabilityCard key={cap.capability_key} cap={cap} />
          ))}
        </div>
      )}
    </div>
  );
}

function CapabilityCard({ cap }: { cap: CapabilityStatus }) {
  return (
    <div className={`rounded-lg p-3 border ${STATUS_COLORS[cap.status] || STATUS_COLORS.disabled} ${cap.armed ? "ring-1 ring-amber-400 animate-pulse" : ""}`}>
      <div className="flex items-center gap-2 mb-1.5">
        <div className={`w-2 h-2 rounded-full ${STATUS_DOT[cap.status] || STATUS_DOT.disabled}`} />
        <span className="text-[11px] font-medium truncate">{cap.display_name}</span>
      </div>
      <div className="text-[10px] text-muted-foreground/60 space-y-0.5">
        <p>{cap.next_trigger_condition}</p>
        {cap.trigger_count_session > 0 && <p>Triggered {cap.trigger_count_session}× this session</p>}
        {cap.last_triggered_at && <p>Last: {new Date(cap.last_triggered_at).toLocaleTimeString()}</p>}
      </div>
    </div>
  );
}
