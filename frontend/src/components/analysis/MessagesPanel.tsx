import { useRef, useEffect } from "react";
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

export function MessagesPanel({ messages }: MessagesPanelProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length]);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Messages</CardTitle>
      </CardHeader>
      <CardContent>
        {messages.length === 0 ? (
          <p className="text-sm text-muted-foreground">No messages yet</p>
        ) : (
          <ScrollArea className="h-64">
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
}
