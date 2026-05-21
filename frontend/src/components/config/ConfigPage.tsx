import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  KeyRound,
  Settings2,
  SlidersHorizontal,
} from "lucide-react";
import { apiClient } from "@/api/client";
import { AppearanceControls } from "@/components/layout/AppearanceControls";
import { PageHeader } from "@/components/layout/PageHeader";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";

export function ConfigPage() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["config"],
    queryFn: ({ signal }) => apiClient.getConfig(signal),
    staleTime: 30_000,
  });

  return (
    <div className="space-y-5 pb-7">
      <PageHeader
        eyebrow="System Settings"
        title="Configuration, environment state, and appearance controls."
        description="Review the active backend configuration, validate overrides, and tune the redesigned interface from the same operational surface."
        stats={[
          {
            label: "Resolved values",
            value: String(Object.keys(data?.resolved ?? {}).length),
            tone: "accent",
          },
          {
            label: "Overrides",
            value: String(Object.keys(data?.overrides ?? {}).length),
            tone: "success",
          },
        ]}
      />

      <AppearanceControls />

      {isLoading ? (
        <div className="grid gap-4 lg:grid-cols-[1.25fr_0.9fr]">
          <Card className="min-h-96 animate-pulse" />
          <Card className="min-h-72 animate-pulse" />
        </div>
      ) : isError || !data ? (
        <Card className="border-destructive/20 bg-destructive/6">
          <CardContent className="flex flex-col gap-4 p-5 sm:flex-row sm:items-center">
            <div className="flex size-10 items-center justify-center rounded-[calc(var(--radius)*1.25)] bg-destructive/10 text-destructive shadow-[var(--shadow-soft)]">
              <AlertTriangle className="size-4.5" />
            </div>
            <div>
              <h2 className="text-lg font-semibold tracking-tight text-destructive">
                Failed to fetch runtime configuration
              </h2>
              <p className="mt-1 text-sm text-muted-foreground">
                The backend settings endpoint is unavailable. Verify the local runtime and
                try again.
              </p>
            </div>
          </CardContent>
        </Card>
      ) : (
        <>
          <div className="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
            <ResolvedConfigCard values={data.resolved} />
            <Card>
              <CardHeader>
                <div className="flex items-center gap-3">
                  <div className="flex size-10 items-center justify-center rounded-[calc(var(--radius)*1.25)] bg-warning/12 text-warning shadow-[var(--shadow-soft)]">
                    <KeyRound className="size-4.5" />
                  </div>
                  <div>
                    <CardTitle>Exchange Connectivity</CardTitle>
                    <CardDescription>
                      Bybit credentials remain optional unless live execution is enabled.
                    </CardDescription>
                  </div>
                </div>
              </CardHeader>
              <CardContent className="space-y-4 text-sm text-muted-foreground">
                <p className="leading-6">
                  TradingAgents uses public Bybit endpoints for market context and can operate
                  in read-only mode without private account credentials.
                </p>
                <div className="rounded-[calc(var(--radius)*1.25)] border border-border/60 bg-muted/20 p-4">
                  <p className="section-eyebrow">Optional variables</p>
                  <div className="mt-3 space-y-2 font-mono text-xs text-foreground">
                    <p>BYBIT_API_KEY</p>
                    <p>BYBIT_API_SECRET</p>
                  </div>
                </div>
                <p className="leading-6">
                  Set the private credentials only when portfolio access, order routing, or
                  account-specific features are required.
                </p>
              </CardContent>
            </Card>
          </div>

          {Object.keys(data.overrides).length > 0 && (
            <Card>
              <CardHeader>
                <div className="flex items-center gap-3">
                  <div className="flex size-10 items-center justify-center rounded-[calc(var(--radius)*1.25)] bg-emerald-500/12 text-emerald-500 shadow-[var(--shadow-soft)]">
                    <SlidersHorizontal className="size-4.5" />
                  </div>
                  <div>
                    <CardTitle>Active Overrides</CardTitle>
                    <CardDescription>
                      These values currently shadow the repository defaults.
                    </CardDescription>
                  </div>
                </div>
              </CardHeader>
              <CardContent className="space-y-2">
                {Object.entries(data.overrides).map(([key, value], index) => (
                  <div
                    key={key}
                    className={cn(
                      "grid gap-1 rounded-[calc(var(--radius)*1.1)] border border-border/50 px-3.5 py-2.5 md:grid-cols-[minmax(0,16rem)_1fr] md:items-center",
                      index % 2 === 0 ? "bg-muted/15" : "bg-card/55",
                    )}
                  >
                    <span className="font-mono text-xs font-semibold text-muted-foreground">
                      {key}
                    </span>
                    <span className="font-mono text-sm font-semibold text-emerald-500 break-all">
                      {String(value)}
                    </span>
                  </div>
                ))}
              </CardContent>
            </Card>
          )}
        </>
      )}
    </div>
  );
}

function ResolvedConfigCard({ values }: { values: Record<string, unknown> }) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-3">
          <div className="flex size-10 items-center justify-center rounded-[calc(var(--radius)*1.25)] bg-primary/10 text-primary shadow-[var(--shadow-soft)]">
            <Settings2 className="size-4.5" />
          </div>
          <div>
            <CardTitle>Resolved Environment</CardTitle>
            <CardDescription>
              The live backend values currently injected into the runtime.
            </CardDescription>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-2">
        <div className="custom-scrollbar max-h-[38rem] space-y-2 overflow-y-auto pr-1">
          {Object.entries(values).map(([key, value], index) => (
            <div
              key={key}
              className={cn(
                "grid gap-1 rounded-[calc(var(--radius)*1.1)] border border-border/50 px-3.5 py-2.5 md:grid-cols-[minmax(0,16rem)_1fr] md:items-center",
                index % 2 === 0 ? "bg-muted/15" : "bg-card/55",
              )}
            >
              <span className="font-mono text-xs font-semibold text-muted-foreground">
                {key}
              </span>
              <span className="font-mono text-sm font-semibold text-foreground break-all">
                {String(value) === "***" ? (
                  <span className="inline-flex items-center rounded-full border border-warning/20 bg-warning/12 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-warning">
                    Masked secret
                  </span>
                ) : (
                  String(value)
                )}
              </span>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
