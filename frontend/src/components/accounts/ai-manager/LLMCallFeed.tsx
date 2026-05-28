import { useMemo, useState } from "react";
import { useAppDispatch, useAppSelector } from "@/store";
import { fetchLLMCalls } from "@/store/ai-manager-slice";
import type { LLMCallEntry } from "@/store/ai-manager-slice";
import { makeSelectLLMCalls, makeSelectInFlightCalls } from "@/store/ai-manager-selectors";
import { Brain, Clock } from "lucide-react";

interface LLMCallFeedProps { accountId: string; }

const URGENCY_COLORS: Record<string, string> = {
  STANDARD: "bg-zinc-500/20 text-zinc-400",
  FAST: "bg-amber-500/20 text-amber-400",
  DEEP: "bg-violet-500/20 text-violet-400",
  EMERGENCY: "bg-red-500/20 text-red-400",
};

export default function LLMCallFeed({ accountId }: LLMCallFeedProps) {
  const dispatch = useAppDispatch();
  const selectCalls = useMemo(() => makeSelectLLMCalls(accountId), [accountId]);
  const selectInFlight = useMemo(() => makeSelectInFlightCalls(accountId), [accountId]);
  const calls = useAppSelector(selectCalls);
  const inFlightIds = useAppSelector(selectInFlight);
  const fsmState = useAppSelector(s => s.aiManager.statusByAccount[accountId]?.state);
  const cursor = useAppSelector(s => s.aiManager.llmCallCursors[accountId]);
  const [expandedId, setExpandedId] = useState<number | null>(null);

  if (fsmState === "sleeping") {
    return (
      <div className="rounded-2xl p-5 text-center text-muted-foreground/50" style={{ background: "var(--neu-surface-base)", boxShadow: "var(--neu-shadow-pill)" }}>
        <Brain className="w-6 h-6 mx-auto mb-2 opacity-40" />
        <p className="text-xs">No LLM activity — AI is sleeping</p>
      </div>
    );
  }
  if (fsmState === "paused") {
    return (
      <div className="rounded-2xl p-5 border border-amber-500/30" style={{ background: "var(--neu-surface-base)", boxShadow: "var(--neu-shadow-pill)" }}>
        <p className="text-xs text-amber-400 font-medium">LLM Feed Paused</p>
      </div>
    );
  }

  return (
    <div className="rounded-2xl p-5 space-y-3" style={{ background: "var(--neu-surface-base)", boxShadow: "var(--neu-shadow-pill)" }}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Brain className="w-4 h-4 text-violet-400" />
          <h4 className="text-xs uppercase tracking-widest font-semibold text-muted-foreground/80">LLM Activity</h4>
        </div>
        {inFlightIds.length > 0 && <ThinkingIndicator />}
      </div>

      <div className="max-h-[500px] overflow-y-auto space-y-1.5 pr-1">
        {calls.length === 0 && (
          <p className="text-xs text-muted-foreground/40 text-center py-4">No calls yet this session</p>
        )}
        {calls.map(call => (
          <LLMCallRow key={call.id} call={call} expanded={expandedId === call.id} onToggle={() => setExpandedId(expandedId === call.id ? null : call.id)} />
        ))}
      </div>

      {cursor && (
        <button onClick={() => dispatch(fetchLLMCalls({ accountId, cursor, append: true }))}
                className="text-xs text-muted-foreground/50 hover:text-muted-foreground transition-colors">
          Load more...
        </button>
      )}
    </div>
  );
}

function ThinkingIndicator() {
  return (
    <div className="flex items-center gap-1.5 text-violet-400">
      <div className="w-2 h-2 rounded-full bg-violet-400 animate-pulse" />
      <span className="text-[10px] font-mono">AI thinking...</span>
    </div>
  );
}

function LLMCallRow({ call, expanded, onToggle }: { call: LLMCallEntry; expanded: boolean; onToggle: () => void }) {
  return (
    <div className="rounded-lg p-2 cursor-pointer hover:bg-muted/5 transition-colors" onClick={onToggle}
         style={{ background: "var(--neu-surface-deep)", boxShadow: "var(--neu-shadow-inset)" }}>
      <div className="flex items-center justify-between text-xs">
        <div className="flex items-center gap-2">
          <span className={`px-1.5 py-0.5 rounded text-[10px] font-mono ${URGENCY_COLORS[call.urgency_tier] || URGENCY_COLORS.STANDARD}`}>
            {call.urgency_tier}
          </span>
          <span className="font-mono text-muted-foreground/70">{call.action_returned || "HOLD"}</span>
          {call.confidence != null && <span className="text-[10px] text-muted-foreground/50">{(call.confidence * 100).toFixed(0)}%</span>}
        </div>
        <div className="flex items-center gap-2 text-[10px] text-muted-foreground/50">
          <span><Clock className="w-3 h-3 inline" /> {call.latency_ms}ms</span>
          <span>{call.input_tokens + call.output_tokens} tok</span>
          <span>{new Date(call.timestamp).toLocaleTimeString()}</span>
        </div>
      </div>
      {expanded && (
        <div className="mt-2 pt-2 border-t border-border/10 text-[11px] text-muted-foreground/60 space-y-1">
          {call.reasoning_preview && <p>{call.reasoning_preview}</p>}
          <p className="font-mono">Model: {call.model} | Attempt: {call.attempt_number}</p>
        </div>
      )}
    </div>
  );
}
