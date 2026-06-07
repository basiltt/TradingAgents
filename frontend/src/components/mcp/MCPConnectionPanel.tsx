/**
 * MCPConnectionPanel — access-token lifecycle + client connection details.
 *
 * The bearer token is shown exactly once at generation time (the backend stores
 * only its hash), so the panel makes "copy it now" unmissable and never claims
 * to display a token it cannot retrieve. It also renders a ready-to-paste client
 * config for Claude Desktop / Claude Code pointing at the loopback transport.
 */
import { useState } from "react";
import { KeyRound, Copy, Check, RefreshCw, Loader2, AlertTriangle, Plug } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { MCPConfig } from "./types";

/** The loopback endpoint the transport serves on (same origin as the app). */
function endpointUrl(): string {
  if (typeof window !== "undefined" && window.location?.origin) {
    return `${window.location.origin}/mcp/rpc`;
  }
  return "http://127.0.0.1:8000/mcp/rpc";
}

export function MCPConnectionPanel({
  config,
  generating,
  freshToken,
  onRegenerate,
  onDismissToken,
}: {
  config: MCPConfig;
  generating: boolean;
  /** Plaintext token from the latest regenerate — shown once, then cleared. */
  freshToken: string | null;
  onRegenerate: () => void;
  onDismissToken: () => void;
}) {
  const endpoint = endpointUrl();

  return (
    <div className="neu-surface-base neu-surface-raised rounded-[var(--neu-radius-lg)] p-5 shadow-[var(--neu-shadow-float)]">
      <div className="flex items-center gap-3">
        <div className="flex size-10 items-center justify-center rounded-[var(--neu-radius-md)] bg-[var(--neu-accent)]/12 text-[var(--neu-accent)]">
          <Plug className="size-5" />
        </div>
        <div>
          <h3 className="text-base font-bold tracking-tight text-[var(--neu-text-strong)]">Connection</h3>
          <p className="text-xs text-[var(--neu-text-muted)]">Bearer token + client setup for the loopback transport.</p>
        </div>
      </div>

      {/* Token state */}
      <div className="mt-4 space-y-3">
        {freshToken ? (
          <FreshTokenCard token={freshToken} onDismiss={onDismissToken} />
        ) : (
          <div className="flex items-center justify-between gap-3 rounded-[var(--neu-radius-md)] border border-[var(--neu-stroke-soft)] bg-[var(--neu-surface-flat)] px-3.5 py-3">
            <div className="flex items-center gap-2.5">
              <KeyRound className="size-4 text-[var(--neu-text-muted)]" />
              <div>
                <div className="text-sm font-semibold text-[var(--neu-text-strong)]">
                  {config.has_token ? "Token configured" : "No token yet"}
                </div>
                <div className="text-[11px] text-[var(--neu-text-muted)]">
                  {config.has_token
                    ? "Stored as a hash — regenerate to reveal a new one."
                    : "Generate a token before enabling the server."}
                </div>
              </div>
            </div>
            <Button variant={config.has_token ? "outline" : "default"} size="sm" onClick={onRegenerate} disabled={generating}>
              {generating ? <Loader2 className="size-4 animate-spin" /> : <RefreshCw className="size-4" />}
              {config.has_token ? "Regenerate" : "Generate"}
            </Button>
          </div>
        )}

        <CopyRow label="Endpoint" value={endpoint} mono />
        <CopyRow label="Host binding" value={config.bind_host} mono />
      </div>

      {/* Client config */}
      <ClientConfigBlock endpoint={endpoint} hasToken={config.has_token || !!freshToken} token={freshToken} />
    </div>
  );
}

function FreshTokenCard({ token, onDismiss }: { token: string; onDismiss: () => void }) {
  return (
    <div className="rounded-[var(--neu-radius-md)] border border-warning/30 bg-warning/8 p-3.5">
      <div className="flex items-center gap-2 text-warning">
        <AlertTriangle className="size-4" />
        <span className="text-xs font-bold uppercase tracking-[0.14em]">Copy this token now</span>
      </div>
      <p className="mt-1.5 text-[11px] text-[var(--neu-text-muted)]">
        It is shown only once. The server stores only a hash and cannot show it again.
      </p>
      <div className="mt-2.5 flex items-center gap-2">
        <code className="flex-1 truncate rounded-[var(--neu-radius-sm)] bg-[var(--neu-surface-inset)] px-2.5 py-2 font-mono text-xs text-[var(--neu-text-strong)]">
          {token}
        </code>
        <CopyButton value={token} />
      </div>
      <button
        type="button"
        onClick={onDismiss}
        className="mt-2 text-[11px] font-medium text-[var(--neu-text-muted)] underline-offset-2 hover:underline"
      >
        I've saved it — hide
      </button>
    </div>
  );
}

function CopyRow({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-[var(--neu-radius-md)] border border-[var(--neu-stroke-soft)] bg-[var(--neu-surface-flat)] px-3.5 py-2.5">
      <div className="min-w-0">
        <div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-[var(--neu-text-muted)]">{label}</div>
        <div className={cn("mt-0.5 truncate text-sm text-[var(--neu-text-strong)]", mono && "font-mono text-xs")}>{value}</div>
      </div>
      <CopyButton value={value} />
    </div>
  );
}

function ClientConfigBlock({ endpoint, hasToken, token }: { endpoint: string; hasToken: boolean; token: string | null }) {
  const snippet = JSON.stringify(
    {
      mcpServers: {
        tradingagents: {
          type: "http",
          url: endpoint,
          headers: { Authorization: `Bearer ${token ?? "<YOUR_TOKEN>"}` },
        },
      },
    },
    null,
    2,
  );

  return (
    <div className="mt-4">
      <div className="mb-1.5 flex items-center justify-between">
        <span className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--neu-text-muted)]">
          Client config (Claude Desktop / Code)
        </span>
        <CopyButton value={snippet} />
      </div>
      <pre className="custom-scrollbar max-h-56 overflow-auto rounded-[var(--neu-radius-md)] bg-[var(--neu-surface-inset)] p-3 text-[11px] leading-relaxed text-[var(--neu-text-strong)]">
        <code>{snippet}</code>
      </pre>
      {!hasToken ? (
        <p className="mt-1.5 text-[11px] text-[var(--neu-text-muted)]">
          Replace <code className="font-mono">&lt;YOUR_TOKEN&gt;</code> with the bearer token after generating one.
        </p>
      ) : null}
    </div>
  );
}

function CopyButton({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // clipboard may be unavailable (non-secure context) — no-op
    }
  }
  return (
    <Button variant="ghost" size="icon-sm" onClick={copy} aria-label="Copy">
      {copied ? <Check className="size-4 text-[var(--neu-accent)]" /> : <Copy className="size-4" />}
    </Button>
  );
}
