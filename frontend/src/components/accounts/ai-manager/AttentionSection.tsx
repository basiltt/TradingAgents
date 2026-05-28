import { useMemo } from "react";
import { useAppDispatch, useAppSelector } from "@/store";
import { dismissAttentionItem } from "@/store/ai-manager-slice";
import type { AttentionItem } from "@/store/ai-manager-slice";
import { makeSelectAttention } from "@/store/ai-manager-selectors";
import { AlertTriangle, X } from "lucide-react";

interface AttentionSectionProps { accountId: string; }

const SEVERITY_STYLES: Record<string, { border: string; icon: string }> = {
  critical: { border: "border-l-red-500", icon: "text-red-400" },
  warning: { border: "border-l-amber-500", icon: "text-amber-400" },
  info: { border: "border-l-sky-500", icon: "text-sky-400" },
};

const SEVERITY_ORDER: Record<string, number> = { critical: 0, warning: 1, info: 2 };

export default function AttentionSection({ accountId }: AttentionSectionProps) {
  const dispatch = useAppDispatch();
  const selectAttention = useMemo(() => makeSelectAttention(accountId), [accountId]);
  const items = useAppSelector(selectAttention);

  const sorted = useMemo(() =>
    [...items].sort((a, b) => (SEVERITY_ORDER[a.severity] ?? 9) - (SEVERITY_ORDER[b.severity] ?? 9) || new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()),
    [items]
  );

  if (sorted.length === 0) {
    return (
      <div className="rounded-2xl p-4 text-center text-muted-foreground/40" style={{ background: "var(--neu-surface-base)", boxShadow: "var(--neu-shadow-pill)" }}>
        <p className="text-xs">Nothing requires your attention</p>
      </div>
    );
  }

  return (
    <div className="rounded-2xl p-5 space-y-3" style={{ background: "var(--neu-surface-base)", boxShadow: "var(--neu-shadow-pill)" }}>
      <div className="flex items-center gap-2">
        <AlertTriangle className="w-4 h-4 text-amber-400" />
        <h4 className="text-xs uppercase tracking-widest font-semibold text-muted-foreground/80">Attention Required</h4>
        <span className="ml-auto text-[10px] text-muted-foreground/50">{sorted.length} item{sorted.length > 1 ? "s" : ""}</span>
      </div>

      <div className="space-y-2 max-h-[300px] overflow-y-auto">
        {sorted.map(item => (
          <AttentionCard key={item.id} item={item} onDismiss={() => dispatch(dismissAttentionItem({ account_id: accountId, item_id: item.id }))} />
        ))}
      </div>
    </div>
  );
}

function AttentionCard({ item, onDismiss }: { item: AttentionItem; onDismiss: () => void }) {
  const styles = SEVERITY_STYLES[item.severity] || SEVERITY_STYLES.info;
  return (
    <div className={`rounded-lg p-3 border-l-2 ${styles.border} animate-in slide-in-from-right-2`}
         style={{ background: "var(--neu-surface-deep)", boxShadow: "var(--neu-shadow-inset)" }}>
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <p className={`text-xs font-medium ${styles.icon}`}>{item.title}</p>
          <p className="text-[10px] text-muted-foreground/60 mt-0.5">{item.description}</p>
          <p className="text-[9px] text-muted-foreground/30 mt-1">{new Date(item.timestamp).toLocaleTimeString()}</p>
        </div>
        <button onClick={(e) => { e.stopPropagation(); onDismiss(); }}
                className="p-1 rounded hover:bg-muted/10 text-muted-foreground/30 hover:text-muted-foreground/60 transition-colors">
          <X className="w-3 h-3" />
        </button>
      </div>
    </div>
  );
}
