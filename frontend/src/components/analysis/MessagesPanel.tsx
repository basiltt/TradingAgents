import { memo, useRef, useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";

interface Message {
  sender: string;
  content: string;
  seq: number;
}

interface MessagesPanelProps {
  messages: Message[];
}

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
      <CardHeader>
        <CardTitle className="text-base">Messages</CardTitle>
      </CardHeader>
      <CardContent>
        <span className="sr-only" aria-live="polite">
          {announced > 0 ? `${announced} new messages` : ""}
        </span>
        {messages.length === 0 ? (
          <p className="text-sm text-muted-foreground">No messages yet</p>
        ) : (
          <ScrollArea className="h-64" role="log">
            <div className="space-y-1 pr-4">
              {messages.map((msg) => (
                <div key={msg.seq} className="text-sm">
                  <span className="font-medium">{msg.sender}:</span>{" "}
                  {msg.content}
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
