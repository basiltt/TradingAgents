import { memo, useRef, useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";

interface Message {
  sender: string;
  content: string;
  seq: number;
}

interface MessagesPanelProps {
  messages: Message[];
}

const SENDER_COLORS: Record<string, string> = {
  market_analyst: "text-blue-600 dark:text-blue-400",
  social_analyst: "text-purple-600 dark:text-purple-400",
  news_analyst: "text-amber-600 dark:text-amber-400",
  fundamentals_analyst: "text-green-600 dark:text-green-400",
  bull_researcher: "text-emerald-600 dark:text-emerald-400",
  bear_researcher: "text-red-600 dark:text-red-400",
  trader: "text-orange-600 dark:text-orange-400",
  risk_manager: "text-rose-600 dark:text-rose-400",
  portfolio_manager: "text-indigo-600 dark:text-indigo-400",
};

export const MessagesPanel = memo(function MessagesPanel({ messages }: MessagesPanelProps) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const [announced, setAnnounced] = useState(0);
  const lastAnnouncedRef = useRef(0);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length]);

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

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base flex items-center gap-2">
          <svg className="w-4 h-4 text-muted-foreground" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
          </svg>
          Messages
          {messages.length > 0 && (
            <Badge variant="secondary" className="ml-auto text-xs">{messages.length}</Badge>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <span className="sr-only" aria-live="polite">
          {announced > 0 ? `${announced} new messages` : ""}
        </span>
        {messages.length === 0 ? (
          <div className="flex flex-col items-center py-6 text-center">
            <div className="w-10 h-10 rounded-xl bg-muted flex items-center justify-center mb-2">
              <svg className="w-5 h-5 text-muted-foreground" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
              </svg>
            </div>
            <p className="text-sm text-muted-foreground">No messages yet</p>
          </div>
        ) : (
          <ScrollArea className="h-72" role="log">
            <div className="space-y-1.5 pr-4">
              {messages.map((msg) => (
                <div key={msg.seq} className="text-sm py-1.5 px-2.5 rounded-md hover:bg-muted/50 transition-colors">
                  <span className={`font-semibold ${SENDER_COLORS[msg.sender] ?? "text-primary"}`}>
                    {msg.sender}
                  </span>
                  <span className="text-muted-foreground mx-1.5">·</span>
                  <span className="text-foreground/90">{msg.content}</span>
                </div>
              ))}
              <div ref={bottomRef} />
            </div>
          </ScrollArea>
        )}
      </CardContent>
    </Card>
  );
});
