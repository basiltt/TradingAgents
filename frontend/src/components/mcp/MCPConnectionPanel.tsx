/**
 * MCPConnectionPanel — access-token lifecycle + client connection details.
 *
 * The bearer token is shown exactly once at generation time (the backend stores
 * only its hash), so the panel makes "copy it now" unmissable and never claims
 * to display a token it cannot retrieve. It also renders a ready-to-paste Claude
 * Code config (file + CLI) pointing at the loopback transport.
 */
import { useState } from "react";
import { KeyRound, Copy, Check, RefreshCw, Loader2, AlertTriangle, ShieldCheck, Plug } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { MCPConfig } from "./types";

/** The reachable /mcp/rpc URL. PREFER the server-computed value (config.rpc_endpoint):
 * the transport guard accepts only a loopback Host, so the endpoint is loopback on
 * the BACKEND port — never the browser's origin (which would point at the frontend
 * dev server / a non-loopback IP the guard rejects). Fall back to a loopback guess. */
function endpointUrl(config: MCPConfig): string {
  if (config.rpc_endpoint) return config.rpc_endpoint;
  return "http://127.0.0.1:8877/mcp/rpc";
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
  const endpoint = endpointUrl(config);

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
        <BindStatus config={config} />
      </div>

      {/* Client config */}
      <ClientConfigBlock endpoint={endpoint} token={freshToken} />
    </div>
  );
}

/** Honest, fail-safe bind/exposure status. This app has NO auth — the loopback bind is
 * the only thing between an attacker and real-money trade placement — so the panel must
 * never present anything but a PROVEN loopback as safe:
 *   - loopback_only === false      → proven exposed → loud red alert
 *   - loopback_only === true        → verified loopback → calm confirmation
 *   - loopback_only undefined/null  → cannot prove it  → persistent amber "verify yourself"
 * The backend can only observe its own bind, never a Docker host port map, so "unproven"
 * is a real and common state that must caution rather than reassure. */
function BindStatus({ config }: { config: MCPConfig }) {
  const proven = config.loopback_only;
  // What we actually detected, for display. served_host is the real bind; bind_host is a
  // DB policy value (NOT the real bind) — label it as such so it's never mistaken for proof.
  const detected = config.served_host || null;
  const hostLabel = detected
    ? detected
    : config.bind_host
      ? `${config.bind_host} (policy, unverified)`
      : "unknown";

  if (proven === false) {
    return (
      <>
        <CopyRow label="Server bind" value={detected || "non-loopback"} mono />
        <p
          role="alert"
          className="flex items-start gap-1.5 rounded-[var(--neu-radius-md)] border border-destructive/30 bg-destructive/8 px-2.5 py-2 text-[11px] font-medium leading-relaxed text-destructive"
        >
          <AlertTriangle aria-hidden className="mt-0.5 size-3.5 shrink-0" />
          <span>
            Exposed bind ({detected || "non-loopback"}) — the trading API has{" "}
            <strong>no authentication</strong>, so any device that can reach this host can
            place real-money trades. The loopback Host check does NOT stop a direct attacker
            (it only blocks browser DNS-rebinding). Bind to 127.0.0.1 and use an
            authenticated reverse proxy for remote access.
          </span>
        </p>
      </>
    );
  }

  if (proven === true) {
    return (
      <>
        <CopyRow label="Server bind" value={detected || "127.0.0.1"} mono />
        <p className="flex items-start gap-1.5 px-1 text-[11px] leading-relaxed text-[var(--neu-text-muted)]">
          <ShieldCheck aria-hidden className="mt-0.5 size-3 shrink-0 text-[var(--neu-accent)]" />
          <span>
            Verified loopback bind — the MCP client (Claude Code) must run on{" "}
            <strong>this same machine</strong>. For remote access, front the app with an
            authenticated reverse proxy; never bind it to a public interface.
          </span>
        </p>
      </>
    );
  }

  // undefined / null → cannot prove the bind. Caution, do not reassure.
  return (
    <>
      <CopyRow label="Server bind" value={hostLabel} mono />
      <p
        role="alert"
        className="flex items-start gap-1.5 rounded-[var(--neu-radius-md)] border border-warning/30 bg-warning/8 px-2.5 py-2 text-[11px] font-medium leading-relaxed text-[var(--neu-text-strong)]"
      >
        <AlertTriangle aria-hidden className="mt-0.5 size-3.5 shrink-0 text-warning" />
        <span>
          Confirm the bind yourself — this indicator can't be verified here. This app has{" "}
          <strong>no authentication</strong>; a loopback bind is the only thing stopping any
          device on your network from placing real-money trades. Before enabling, check on
          the host that the port is bound to <code className="font-mono">127.0.0.1</code>,
          not <code className="font-mono">0.0.0.0</code> or a LAN IP — e.g.{" "}
          <code className="font-mono">ss -ltnp | grep {portOf(config)}</code> on Linux,{" "}
          <code className="font-mono">docker port &lt;container&gt;</code> for Docker, or{" "}
          <code className="font-mono">netstat -ano | findstr {portOf(config)}</code> on
          Windows.
        </span>
      </p>
    </>
  );
}

/** Best-effort port for the verification hint, parsed from the computed endpoint. */
function portOf(config: MCPConfig): string {
  const m = config.rpc_endpoint?.match(/:(\d+)\//);
  return m ? m[1] : "8877";
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

function ClientConfigBlock({ endpoint, token }: { endpoint: string; token: string | null }) {
  // The placeholder is present whenever we don't have the freshly-minted plaintext
  // token (the common steady state — the backend only ever stores its hash). Gate the
  // "replace this" hint on the placeholder actually being shown, not on whether a token
  // exists, so an operator with a configured-but-hidden token still gets guidance.
  // Guard on falsiness (not `=== null`) so an empty-string token never emits a bare
  // "Bearer " with no hint.
  const hasPlaintext = !!token;
  const tokenValue = hasPlaintext ? token : "<YOUR_TOKEN>";
  const showPlaceholderHint = !hasPlaintext;
  const snippet = JSON.stringify(
    {
      mcpServers: {
        tradingagents: {
          type: "http",
          url: endpoint,
          headers: { Authorization: `Bearer ${tokenValue}` },
        },
      },
    },
    null,
    2,
  );
  // Equivalent Claude Code CLI one-liner (adds the same HTTP server + auth header).
  const cliCommand = `claude mcp add --transport http tradingagents ${endpoint} --header "Authorization: Bearer ${tokenValue}"`;

  return (
    <div className="mt-4 space-y-3">
      <div>
        <div className="mb-1.5 flex items-center justify-between">
          <span className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--neu-text-muted)]">
            Claude Code — config file (.mcp.json)
          </span>
          <CopyButton value={snippet} />
        </div>
        <pre className="custom-scrollbar max-h-56 overflow-auto rounded-[var(--neu-radius-md)] bg-[var(--neu-surface-inset)] p-3 text-[11px] leading-relaxed text-[var(--neu-text-strong)]">
          <code>{snippet}</code>
        </pre>
      </div>

      <div>
        <div className="mb-1.5 flex items-center justify-between">
          <span className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--neu-text-muted)]">
            Claude Code — CLI
          </span>
          <CopyButton value={cliCommand} />
        </div>
        <pre className="custom-scrollbar overflow-auto rounded-[var(--neu-radius-md)] bg-[var(--neu-surface-inset)] p-3 text-[11px] leading-relaxed text-[var(--neu-text-strong)]">
          <code>{cliCommand}</code>
        </pre>
      </div>

      {showPlaceholderHint ? (
        <p className="text-[11px] text-[var(--neu-text-muted)]">
          Replace <code className="font-mono">&lt;YOUR_TOKEN&gt;</code> with the bearer token
          (it is shown only once, at generation time — regenerate above to reveal a new one).
        </p>
      ) : null}
      <p className="text-[11px] text-[var(--neu-text-muted)]">
        Claude Desktop has no native loopback-HTTP server config — bridge it with{" "}
        <code className="font-mono">npx mcp-remote {endpoint}</code> (stdio) if needed.
      </p>
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
    <Button variant="ghost" size="icon-sm" onClick={copy} aria-label={copied ? "Copied" : "Copy"}>
      {copied ? <Check aria-hidden className="size-4 text-[var(--neu-accent)]" /> : <Copy aria-hidden className="size-4" />}
    </Button>
  );
}
