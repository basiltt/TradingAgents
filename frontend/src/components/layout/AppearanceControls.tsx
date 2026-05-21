import {
  Contrast,
  MonitorCog,
  MoonStar,
  SunMedium,
  SwatchBook,
} from "lucide-react";
import { useAppDispatch, useAppSelector } from "@/store";
import { setContrast, setPalette, setTheme } from "@/store/ui-slice";
import {
  getPalettePreview,
  themeContrastOrder,
  themePaletteOrder,
  themePalettes,
  type ThemeContrast,
  type ThemeMode,
} from "@/lib/theme";
import { cn } from "@/lib/utils";

const themeOptions: Array<{
  value: ThemeMode;
  label: string;
  icon: typeof SunMedium;
}> = [
  { value: "light", label: "Light", icon: SunMedium },
  { value: "dark", label: "Dark", icon: MoonStar },
  { value: "system", label: "System", icon: MonitorCog },
];

const contrastLabels: Record<ThemeContrast, string> = {
  standard: "Balanced",
  high: "High Contrast",
};

export function AppearanceControls({
  className,
  compact = false,
}: {
  className?: string;
  compact?: boolean;
}) {
  const dispatch = useAppDispatch();
  const theme = useAppSelector((s) => s.ui.theme);
  const palette = useAppSelector((s) => s.ui.palette);
  const contrast = useAppSelector((s) => s.ui.contrast);

  return (
    <div
      className={cn(
        "flex flex-col gap-3.5",
        compact &&
          "rounded-[calc(var(--radius)*1.65)] border border-border/60 bg-card/55 p-2.5 shadow-[var(--shadow-card)] backdrop-blur-xl",
        className,
      )}
    >
      {!compact && (
        <div className="flex items-start gap-3 rounded-[calc(var(--radius)*1.75)] border border-border/60 bg-card/70 p-4 shadow-[var(--shadow-card)] backdrop-blur-xl">
          <div className="flex size-10 shrink-0 items-center justify-center rounded-[calc(var(--radius)*1.2)] bg-primary/10 text-primary shadow-[var(--shadow-soft)]">
            <SwatchBook className="size-4.5" />
          </div>
          <div className="space-y-1">
            <p className="section-eyebrow">Appearance Studio</p>
            <h2 className="text-base font-semibold tracking-tight">
              Switch themes and palettes from one source.
            </h2>
            <p className="text-[0.82rem] text-muted-foreground">
              All color presets are centralized in the frontend theme token map, so
              the shell, charts, forms, dialogs, and badges stay in sync.
            </p>
          </div>
        </div>
      )}

      <div className="space-y-2">
        <div className="flex items-center justify-between gap-3">
          <p className="section-eyebrow">Theme Mode</p>
          {!compact && (
            <p className="text-xs text-muted-foreground">
              Pick a fixed mode or follow the system preference.
            </p>
          )}
        </div>
        <div className="grid grid-cols-3 gap-2 rounded-[calc(var(--radius)*1.45)] border border-border/60 bg-muted/25 p-1 shadow-[var(--shadow-inset)]">
          {themeOptions.map((option) => {
            const Icon = option.icon;
            const active = theme === option.value;
            return (
              <button
                key={option.value}
                type="button"
                aria-pressed={active}
                onClick={() => dispatch(setTheme(option.value))}
                className={cn(
                  "touch-target inline-flex items-center justify-center gap-1.5 rounded-[calc(var(--radius)*1.1)] border px-2.5 py-1.5 text-[0.82rem] font-medium transition-all duration-200",
                  active
                    ? "border-primary/50 bg-primary text-primary-foreground shadow-[var(--shadow-accent)]"
                    : "border-transparent bg-transparent text-muted-foreground hover:border-border/70 hover:bg-card/80 hover:text-foreground",
                )}
              >
                <Icon className="size-4" />
                {!compact && <span>{option.label}</span>}
              </button>
            );
          })}
        </div>
      </div>

      <div className="space-y-2">
        <div className="flex items-center justify-between gap-3">
          <p className="section-eyebrow">Palette</p>
          {!compact && (
            <p className="text-xs text-muted-foreground">
              Presets update the full design token stack instantly.
            </p>
          )}
        </div>
        <div
          className={cn(
            "grid gap-2",
            compact ? "grid-cols-4" : "grid-cols-1 md:grid-cols-2 xl:grid-cols-4",
          )}
        >
          {themePaletteOrder.map((paletteKey) => {
            const definition = themePalettes[paletteKey];
            const active = palette === paletteKey;
            return (
              <button
                key={paletteKey}
                type="button"
                aria-pressed={active}
                onClick={() => dispatch(setPalette(paletteKey))}
                className={cn(
                  "group relative overflow-hidden rounded-[calc(var(--radius)*1.5)] border text-left transition-all duration-200",
                  compact
                    ? "aspect-square p-0.5"
                    : "p-1.25",
                  active
                    ? "border-primary/45 shadow-[var(--shadow-accent)]"
                    : "border-border/60 hover:-translate-y-0.5 hover:border-border/85 hover:shadow-[var(--shadow-card-hover)]",
                )}
              >
                <div
                  className={cn(
                    "h-full rounded-[calc(var(--radius)*1.1)]",
                    compact ? "" : "min-h-[7.75rem]",
                  )}
                  style={{ background: getPalettePreview(paletteKey) }}
                />
                {!compact && (
                  <div className="pointer-events-none absolute inset-x-1.5 bottom-1.5 rounded-[calc(var(--radius)*1.05)] border border-white/20 bg-black/35 p-2.5 text-white backdrop-blur-md">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-semibold tracking-tight">{definition.label}</span>
                      {active && (
                        <span className="rounded-full border border-white/25 bg-white/15 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.22em]">
                          Active
                        </span>
                      )}
                    </div>
                    <p className="mt-1 text-xs text-white/75">{definition.description}</p>
                  </div>
                )}
              </button>
            );
          })}
        </div>
      </div>

      <div className="space-y-2">
        <div className="flex items-center justify-between gap-3">
          <p className="section-eyebrow">Contrast</p>
          {!compact && (
            <p className="text-xs text-muted-foreground">
              Strengthen edges and readability for dense data views.
            </p>
          )}
        </div>
        <div className="grid grid-cols-2 gap-2 rounded-[calc(var(--radius)*1.45)] border border-border/60 bg-muted/25 p-1 shadow-[var(--shadow-inset)]">
          {themeContrastOrder.map((contrastMode) => {
            const active = contrast === contrastMode;
            return (
              <button
                key={contrastMode}
                type="button"
                aria-pressed={active}
                onClick={() => dispatch(setContrast(contrastMode))}
                className={cn(
                  "touch-target inline-flex items-center justify-center gap-1.5 rounded-[calc(var(--radius)*1.1)] border px-2.5 py-1.5 text-[0.82rem] font-medium transition-all duration-200",
                  active
                    ? "border-primary/50 bg-primary text-primary-foreground shadow-[var(--shadow-accent)]"
                    : "border-transparent bg-transparent text-muted-foreground hover:border-border/70 hover:bg-card/80 hover:text-foreground",
                )}
              >
                <Contrast className="size-4" />
                {!compact && <span>{contrastLabels[contrastMode]}</span>}
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
