import { memo, useRef, useEffect, useState, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import { MobileCollapse } from "./MobileCollapse";

interface Message {
  sender: string;
  content: string;
  seq: number;
}

interface MessagesPanelProps {
  messages: Message[];
  isLoading?: boolean;
}

const SENDER_CONFIG: Record<string, { color: string; bg: string; label: string }> = {
  market_analyst: { color: "text-blue-700 dark:text-blue-400", bg: "bg-blue-500/10", label: "Market Analyst" },
  social_analyst: { color: "text-purple-700 dark:text-purple-400", bg: "bg-purple-500/10", label: "Social Analyst" },
  news_analyst: { color: "text-amber-700 dark:text-amber-400", bg: "bg-amber-500/10", label: "News Analyst" },
  fundamentals_analyst: { color: "text-green-700 dark:text-green-400", bg: "bg-green-500/10", label: "Fundamentals Analyst" },
  bull_researcher: { color: "text-emerald-700 dark:text-emerald-400", bg: "bg-emerald-500/10", label: "Bull Researcher" },
  bear_researcher: { color: "text-red-700 dark:text-red-400", bg: "bg-red-500/10", label: "Bear Researcher" },
  trader: { color: "text-orange-700 dark:text-orange-400", bg: "bg-orange-500/10", label: "Trader" },
  risk_manager: { color: "text-rose-700 dark:text-rose-400", bg: "bg-rose-500/10", label: "Risk Manager" },
  portfolio_manager: { color: "text-indigo-700 dark:text-indigo-400", bg: "bg-indigo-500/10", label: "Portfolio Manager" },
};

function formatSender(sender: string): string {
  return SENDER_CONFIG[sender]?.label ?? sender.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

const mdComponents = {
  table: ({ children }: { children?: ReactNode }) => (
    <div className="my-1.5 overflow-x-auto rounded-md border border-border/50">
      <table className="w-full text-xs">{children}</table>
    </div>
  ),
  thead: ({ children }: { children?: ReactNode }) => (
    <thead className="bg-muted/60">{children}</thead>
  ),
  th: ({ children }: { children?: ReactNode }) => (
    <th className="px-2.5 py-1.5 text-left text-xs font-semibold text-foreground/80 border-b border-border/50">{children}</th>
  ),
  td: ({ children }: { children?: ReactNode }) => (
    <td className="px-2.5 py-1.5 text-foreground/80 border-t border-border/30">{children}</td>
  ),
  h1: ({ children }: { children?: ReactNode }) => (
    <h1 className="text-sm font-bold mt-3 mb-1.5">{children}</h1>
  ),
  h2: ({ children }: { children?: ReactNode }) => (
    <h2 className="text-sm font-semibold mt-3 mb-1">{children}</h2>
  ),
  h3: ({ children }: { children?: ReactNode }) => (
    <h3 className="text-xs font-semibold mt-2 mb-1 uppercase tracking-wider text-foreground/70">{children}</h3>
  ),
  p: ({ children }: { children?: ReactNode }) => (
    <p className="my-1.5 leading-relaxed">{children}</p>
  ),
  ul: ({ children }: { children?: ReactNode }) => (
    <ul className="my-1.5 ml-1 space-y-0.5 list-disc list-outside pl-4">{children}</ul>
  ),
  ol: ({ children }: { children?: ReactNode }) => (
    <ol className="my-1.5 ml-1 space-y-0.5 list-decimal list-outside pl-4">{children}</ol>
  ),
  blockquote: ({ children }: { children?: ReactNode }) => (
    <blockquote className="my-1.5 border-l-2 border-primary/25 pl-3 text-foreground/55 italic">{children}</blockquote>
  ),
  strong: ({ children }: { children?: ReactNode }) => (
    <strong className="font-semibold text-foreground">{children}</strong>
  ),
  hr: () => <hr className="my-2 border-border/30" />,
  code: ({ children, className }: { children?: ReactNode; className?: string }) => {
    if (className) {
      const lang = className.replace("language-", "");
      return (
        <pre className="my-1.5 rounded-md bg-muted/70 border border-border/50 p-2.5 overflow-x-auto text-xs font-mono leading-relaxed">
          {lang && <div className="text-[10px] text-muted-foreground mb-1 uppercase tracking-wide">{lang}</div>}
          <code>{children}</code>
        </pre>
      );
    }
    return (
      <code className="px-1 py-0.5 rounded bg-muted/60 text-xs font-mono text-primary/80">{children}</code>
    );
  },
};

function MessageContent({ content }: { content: string }) {
  return (
    <div className="text-sm text-foreground/90 leading-relaxed">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
        {content}
      </ReactMarkdown>
    </div>
  );
}

function MsgIcon() {
  return (
    <svg className="w-4 h-4 text-muted-foreground" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
    </svg>
  );
}

export const MessagesPanel = memo(function MessagesPanel({ messages, isLoading }: MessagesPanelProps) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const [announced, setAnnounced] = useState(0);
  const lastAnnouncedRef = useRef(0);

  // No auto-scroll — let the user control scroll position manually.

  useEffect(() => {
    const interval = setInterval(() => {
      const newCount = messages.length - lastAnnouncedRef.current;
      if (newCount > 0) {
        setAnnounced(newCount);
        lastAnnouncedRef.current = messages.length;
      }
    }, 10_000);
    return () => clearInterval(interval);
  }, [messages.length]);

  const countBadge = messages.length > 0 ? (
    <span className="inline-flex items-center text-[10px] font-black bg-muted/80 text-foreground px-2 py-0.5 rounded-full border border-border/30">
      {messages.length}
    </span>
  ) : null;

  const renderBody = (scrollClassName: string) => (
    <>
      <span className="sr-only" aria-live="polite">
        {announced > 0 ? `${announced} new messages` : ""}
      </span>
      {isLoading ? (
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="rounded-xl border border-border/30 p-4 space-y-3 bg-muted/20">
              <Skeleton className="h-5 w-28 rounded-md" />
              <Skeleton className="h-3.5 w-full rounded" />
              <Skeleton className="h-3.5 w-4/5 rounded" />
            </div>
          ))}
        </div>
      ) : messages.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-12 text-center h-full">
          <div className="w-14 h-14 rounded-2xl bg-muted/50 flex items-center justify-center mb-4 border border-border/20 shadow-inner">
            <svg className="w-6 h-6 text-muted-foreground animate-pulse" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
            </svg>
          </div>
          <p className="text-sm font-bold text-foreground/80">No messages yet</p>
          <p className="text-xs text-muted-foreground mt-1">Messages will stream in as agents execute pipeline tasks.</p>
        </div>
      ) : (
        <ScrollArea className={scrollClassName} role="log">
          <div className="space-y-3 pr-3">
            {messages.map((msg) => {
              const cfg = SENDER_CONFIG[msg.sender];
              const colorClass = cfg?.color ?? "text-primary";
              const bgClass = cfg?.bg ?? "bg-muted";
              return (
                <div key={msg.seq} className="rounded-xl border border-border/30 p-4 bg-muted/15 hover:bg-muted/35 hover:border-border/50 transition-all duration-300 shadow-sm">
                  <div className="flex items-center justify-between gap-2 mb-2 flex-wrap">
                    <span className={`inline-flex items-center text-[10px] font-black uppercase tracking-wider px-2 py-0.5 rounded border border-current/15 ${bgClass} ${colorClass}`}>
                      {formatSender(msg.sender)}
                    </span>
                    <span className="text-[9px] text-muted-foreground font-mono font-bold">SEQ #{msg.seq}</span>
                  </div>
                  <MessageContent content={msg.content} />
                </div>
              );
            })}
            <div ref={bottomRef} />
          </div>
        </ScrollArea>
      )}
    </>
  );

  return (
    <div className="h-full">
      {/* Mobile: collapsible */}
      <MobileCollapse
        defaultOpen
        storageKey="collapse:messages"
        className="md:hidden"
        title={
          <span className="text-xs font-bold uppercase tracking-wider flex items-center gap-2">
            <MsgIcon />
            Pipeline Logs
          </span>
        }
        badge={countBadge}
      >
        <div className="p-4">{renderBody("h-[28rem]")}</div>
      </MobileCollapse>

      {/* Desktop: Glass Card */}
      <div className="hidden md:flex md:flex-col h-full glass-card border border-border/50 rounded-2xl p-5 bg-card/65 shadow-sm min-h-[460px]">
        <div className="flex items-center justify-between pb-4 border-b border-border/30 mb-4 shrink-0">
          <h3 className="text-xs font-bold uppercase tracking-wider flex items-center gap-2 text-foreground/90">
            <MsgIcon />
            Real-Time Messages Feed
          </h3>
          {countBadge}
        </div>
        <div className="flex-1 min-h-0">
          {renderBody("h-[380px]")}
        </div>
      </div>
    </div>
  );
});
