import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  KeyRound,
  Settings2,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
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

  const resolvedCount = Object.keys(data?.resolved ?? {}).length;
  const overrideCount = Object.keys(data?.overrides ?? {}).length;
  const maskedSecrets = Object.values(data?.resolved ?? {}).filter((value) => String(value) === "***").length;

  return (
    <div className="space-y-5 pb-7">
      <PageHeader
        eyebrow="System Settings"
        title="Configuration command center"
        description="Inspect live runtime values, validate deployment overrides, and tune the premium interface from a single operational surface."
        stats={[
          {
            label: "Resolved values",
            value: String(resolvedCount),
            tone: "accent",
          },
          {
            label: "Overrides",
            value: String(overrideCount),
            tone: overrideCount ? "success" : "neutral",
          },
          {
            label: "Masked secrets",
            value: String(maskedSecrets),
            tone: maskedSecrets ? "warning" : "neutral",
          },
        ]}
      >
        <div className="flex flex-wrap gap-2">
          <span className="inline-flex items-center gap-2 rounded-full border border-border/60 bg-background/55 px-3 py-1.5 text-[11px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
            <Sparkles className="size-3.5 text-primary" />
            Runtime visibility
          </span>
          <span className="inline-flex items-center gap-2 rounded-full border border-border/60 bg-background/55 px-3 py-1.5 text-[11px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
            <ShieldCheck className="size-3.5 text-success" />
            Safe secret masking
          </span>
        </div>
      </PageHeader>

      <AppearanceControls />

      {isLoading ? (
        <div className="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
          <Card className="min-h-96 animate-pulse" />
          <Card className="min-h-80 animate-pulse" />
        </div>
      ) : isError || !data ? (
        <Card className="border-destructive/20 bg-destructive/6">
          <CardContent className="flex flex-col gap-4 p-5 sm:flex-row sm:items-center">
            <div className="flex size-12 items-center justify-center rounded-[calc(var(--radius)*1.3)] bg-destructive/10 text-destructive shadow-[var(--shadow-soft)]">
              <AlertTriangle className="size-5" />
            </div>
            <div>
              <h2 className="text-lg font-semibold tracking-tight text-destructive">
                Failed to fetch runtime configuration
              </h2>
              <p className="mt-1 text-sm leading-6 text-muted-foreground">
                The backend settings endpoint is unavailable. Verify the local runtime and try again.
              </p>
            </div>
          </CardContent>
        </Card>
      ) : (
        <>
          <div className="grid gap-4 xl:grid-cols-[1.18fr_0.82fr]">
            <ResolvedConfigCard values={data.resolved} />
            <div className="space-y-4">
              <Card className="overflow-hidden">
                <CardHeader>
                  <div className="flex items-center gap-3">
                    <div className="gradient-primary flex size-11 items-center justify-center rounded-[calc(var(--radius)*1.25)] text-primary-foreground shadow-[var(--shadow-accent)]">
                      <KeyRound className="size-5" />
                    </div>
                    <div>
                      <CardTitle>Exchange connectivity</CardTitle>
                      <CardDescription>
                        Bybit credentials remain optional until live execution features are required.
                      </CardDescription>
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="space-y-4 text-sm text-muted-foreground">
                  <div className="surface-lift rounded-[calc(var(--radius)*1.2)] p-4">
                    <p className="section-eyebrow">Operational mode</p>
                    <p className="mt-2 leading-6">
                      TradingAgents can operate in a read-only market intelligence mode without private exchange secrets.
                    </p>
                  </div>

                  <div className="rounded-[calc(var(--radius)*1.2)] border border-border/60 bg-background/45 p-4">
                    <p className="section-eyebrow">Optional variables</p>
                    <div className="mt-3 space-y-2 font-mono text-xs text-foreground">
                      <p>BYBIT_API_KEY</p>
                      <p>BYBIT_API_SECRET</p>
                    </div>
                  </div>

                  <div className="rounded-[calc(var(--radius)*1.2)] border border-success/18 bg-success/8 p-4">
                    <p className="text-sm font-semibold text-foreground">Best practice</p>
                    <p className="mt-2 leading-6">
                      Inject private credentials only when portfolio access, position management, or live order routing is enabled.
                    </p>
                  </div>
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <div className="flex items-center gap-3">
                    <div className="flex size-11 items-center justify-center rounded-[calc(var(--radius)*1.25)] bg-warning/12 text-warning shadow-[var(--shadow-soft)]">
                      <ShieldCheck className="size-5" />
                    </div>
                    <div>
                      <CardTitle>Runtime posture</CardTitle>
                      <CardDescription>
                        Quick visibility into the current configuration surface.
                      </CardDescription>
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="grid gap-3 sm:grid-cols-3 xl:grid-cols-1">
                  {[
                    { label: "Resolved keys", value: String(resolvedCount), tone: "accent" },
                    { label: "Override keys", value: String(overrideCount), tone: overrideCount ? "success" : "neutral" },
                    { label: "Masked values", value: String(maskedSecrets), tone: maskedSecrets ? "warning" : "neutral" },
                  ].map((item) => (
                    <div key={item.label} data-tone={item.tone} className="page-header-stat rounded-[calc(var(--radius)*1.1)] border px-4 py-3.5">
                      <div className="text-[10px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">{item.label}</div>
                      <div className="mt-2 text-lg font-semibold tracking-[-0.04em] text-foreground">{item.value}</div>
                    </div>
                  ))}
                </CardContent>
              </Card>
            </div>
          </div>

          {overrideCount > 0 ? (
            <Card>
              <CardHeader>
                <div className="flex items-center gap-3">
                  <div className="flex size-11 items-center justify-center rounded-[calc(var(--radius)*1.25)] bg-success/12 text-success shadow-[var(--shadow-soft)]">
                    <SlidersHorizontal className="size-5" />
                  </div>
                  <div>
                    <CardTitle>Active overrides</CardTitle>
                    <CardDescription>
                      These values currently shadow the repository defaults for this environment.
                    </CardDescription>
                  </div>
                </div>
              </CardHeader>
              <CardContent>
                <div className="grid gap-3 lg:grid-cols-2">
                  {Object.entries(data.overrides).map(([key, value], index) => (
                    <div
                      key={key}
                      className={cn(
                        "surface-lift rounded-[calc(var(--radius)*1.12)] px-4 py-3.5",
                        index % 3 === 0 && "border-primary/12",
                      )}
                    >
                      <div className="text-[10px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                        {key}
                      </div>
                      <div className="mt-2 break-all font-mono text-sm font-semibold text-success">
                        {String(value)}
                      </div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          ) : null}
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
          <div className="gradient-primary flex size-11 items-center justify-center rounded-[calc(var(--radius)*1.25)] text-primary-foreground shadow-[var(--shadow-accent)]">
            <Settings2 className="size-5" />
          </div>
          <div>
            <CardTitle>Resolved environment</CardTitle>
            <CardDescription>
              The live backend values currently injected into runtime.
            </CardDescription>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="surface-lift rounded-[calc(var(--radius)*1.15)] px-4 py-3.5 text-sm leading-6 text-muted-foreground">
          This table is ideal for deployment reviews, environment drift detection, and fast verification after infrastructure changes.
        </div>

        <div className="custom-scrollbar max-h-[42rem] space-y-2 overflow-y-auto pr-1">
          {Object.entries(values).map(([key, value], index) => (
            <div
              key={key}
              className={cn(
                "grid gap-2 rounded-[calc(var(--radius)*1.1)] border px-4 py-3 md:grid-cols-[minmax(0,17rem)_1fr] md:items-center",
                index % 2 === 0
                  ? "border-border/55 bg-background/40"
                  : "border-border/60 bg-card/68",
              )}
            >
              <span className="font-mono text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                {key}
              </span>
              <span className="break-all font-mono text-sm font-semibold text-foreground">
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
