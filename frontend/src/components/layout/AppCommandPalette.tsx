import { useMemo, useState } from "react";
import { useNavigate } from "@tanstack/react-router";
import {
  Command,
  Contrast,
  MoonStar,
  MonitorCog,
  Search,
  SunMedium,
  SwatchBook,
} from "lucide-react";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { themePaletteOrder, themePalettes } from "@/lib/theme";
import { useAppDispatch, useAppSelector } from "@/store";
import { setContrast, setPalette, setTheme } from "@/store/ui-slice";
import { navSections } from "@/components/layout/navigation";

type CommandItem = {
  id: string;
  title: string;
  description: string;
  icon: typeof Search;
  category: string;
  keywords: string[];
  active?: boolean;
  action: () => void;
};

export function AppCommandPalette({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const navigate = useNavigate();
  const dispatch = useAppDispatch();
  const theme = useAppSelector((state) => state.ui.theme);
  const palette = useAppSelector((state) => state.ui.palette);
  const contrast = useAppSelector((state) => state.ui.contrast);
  const [query, setQuery] = useState("");

  const commands = useMemo<CommandItem[]>(() => {
    const routeCommands = navSections.flatMap((section) =>
      section.items.map((item) => ({
        id: item.id,
        title: item.label,
        description: item.description,
        icon: item.icon,
        category: section.title,
        keywords: [item.label, item.description, ...item.keywords],
        action: () => navigate({ to: item.to as never }),
      })),
    );

    const appearanceCommands: CommandItem[] = [
      {
        id: "theme-light",
        title: "Switch to Light Mode",
        description: "Use the light terminal theme for brighter daytime work.",
        icon: SunMedium,
        category: "Appearance",
        keywords: ["theme", "light", "bright"],
        active: theme === "light",
        action: () => dispatch(setTheme("light")),
      },
      {
        id: "theme-dark",
        title: "Switch to Dark Mode",
        description: "Use the dark terminal theme for high-density monitoring.",
        icon: MoonStar,
        category: "Appearance",
        keywords: ["theme", "dark", "night"],
        active: theme === "dark",
        action: () => dispatch(setTheme("dark")),
      },
      {
        id: "theme-system",
        title: "Follow System Theme",
        description: "Sync the workspace appearance with the operating system preference.",
        icon: MonitorCog,
        category: "Appearance",
        keywords: ["theme", "system", "automatic"],
        active: theme === "system",
        action: () => dispatch(setTheme("system")),
      },
      {
        id: "contrast-standard",
        title: "Use Balanced Contrast",
        description: "Restore the standard terminal contrast profile.",
        icon: Contrast,
        category: "Appearance",
        keywords: ["contrast", "balanced", "standard"],
        active: contrast === "standard",
        action: () => dispatch(setContrast("standard")),
      },
      {
        id: "contrast-high",
        title: "Enable High Contrast",
        description: "Boost edge definition and readability across dense tables and panels.",
        icon: Contrast,
        category: "Appearance",
        keywords: ["contrast", "accessible", "high"],
        active: contrast === "high",
        action: () => dispatch(setContrast("high")),
      },
      ...themePaletteOrder.map((paletteKey) => ({
        id: `palette-${paletteKey}`,
        title: `Activate ${themePalettes[paletteKey].label} Palette`,
        description: themePalettes[paletteKey].description,
        icon: SwatchBook,
        category: "Appearance",
        keywords: [
          "palette",
          paletteKey,
          themePalettes[paletteKey].label,
          themePalettes[paletteKey].description,
        ],
        active: palette === paletteKey,
        action: () => dispatch(setPalette(paletteKey)),
      })),
    ];

    return [...routeCommands, ...appearanceCommands];
  }, [contrast, dispatch, navigate, palette, theme]);

  const filteredCommands = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) return commands;

    return commands.filter((item) =>
      item.keywords.some((keyword) => keyword.toLowerCase().includes(normalized)),
    );
  }, [commands, query]);

  const groupedCommands = useMemo(() => {
    const groups = new Map<string, CommandItem[]>();
    for (const item of filteredCommands) {
      const current = groups.get(item.category) ?? [];
      current.push(item);
      groups.set(item.category, current);
    }
    return groups;
  }, [filteredCommands]);

  const runCommand = (command: CommandItem) => {
    command.action();
    setQuery("");
    onOpenChange(false);
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) setQuery("");
        onOpenChange(next);
      }}
    >
      <DialogContent
        showCloseButton={false}
        className="max-w-[min(52rem,calc(100%-1rem))] gap-0 overflow-hidden border border-border/70 bg-popover/88 p-0 backdrop-blur-2xl"
      >
        <DialogHeader className="border-b border-border/60 bg-card/72 px-4 py-3.5">
          <div className="flex items-center gap-3">
            <div className="flex size-10 items-center justify-center rounded-[calc(var(--radius)*1.2)] border border-primary/20 bg-primary/12 text-primary shadow-[var(--shadow-accent)]">
              <Command className="size-4.5" />
            </div>
            <div className="min-w-0">
              <DialogTitle>Command Palette</DialogTitle>
              <DialogDescription className="mt-1">
                Jump across routes, switch palettes, and tune the workspace without leaving the keyboard.
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

        <div className="border-b border-border/50 bg-background/55 px-4 py-2.5">
          <label className="flex items-center gap-3 rounded-[calc(var(--radius)*1.2)] border border-border/70 bg-card/78 px-3.5 py-2.5 shadow-[var(--shadow-soft)]">
            <Search className="size-4.5 shrink-0 text-muted-foreground" />
            <input
              autoFocus
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search routes, themes, palettes, or workspace actions..."
              className="min-w-0 flex-1 bg-transparent text-[0.9rem] text-foreground outline-none placeholder:text-muted-foreground/80"
            />
            <span className="command-kbd hidden sm:inline-flex">Ctrl K</span>
          </label>
        </div>

        <div className="custom-scrollbar max-h-[min(70vh,34rem)] overflow-y-auto px-3 py-2.5">
          {groupedCommands.size === 0 ? (
            <div className="flex min-h-40 flex-col items-center justify-center gap-3 rounded-[calc(var(--radius)*1.35)] border border-dashed border-border/70 bg-muted/15 p-5 text-center">
              <Search className="size-6 text-muted-foreground" />
              <div>
                <p className="text-sm font-semibold tracking-tight">No matching commands</p>
                <p className="mt-1 text-sm text-muted-foreground">
                  Try a route name, a palette label, or words like "contrast" and "scanner".
                </p>
              </div>
            </div>
          ) : (
            Array.from(groupedCommands.entries()).map(([category, items]) => (
              <section key={category} className="space-y-2 py-1.5">
                <div className="px-2">
                  <p className="section-eyebrow">{category}</p>
                </div>
                <div className="grid gap-2">
                  {items.map((item) => {
                    const Icon = item.icon;
                    return (
                      <button
                        key={item.id}
                        type="button"
                        onClick={() => runCommand(item)}
                        className="group/command flex items-start gap-3 rounded-[calc(var(--radius)*1.2)] border border-border/60 bg-card/70 px-3.5 py-2.5 text-left shadow-[var(--shadow-soft)] hover:-translate-y-0.5 hover:border-primary/25 hover:bg-card/88 hover:shadow-[var(--shadow-card-hover)]"
                      >
                        <span className="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-[calc(var(--radius)*1)] border border-white/8 bg-white/4 text-primary">
                          <Icon className="size-4.5" />
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="flex flex-wrap items-center gap-2">
                            <span className="text-sm font-semibold tracking-tight text-foreground">
                              {item.title}
                            </span>
                            {item.active ? (
                              <span className="rounded-full border border-primary/20 bg-primary/12 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.18em] text-primary">
                                Active
                              </span>
                            ) : null}
                          </span>
                          <span className="mt-1 block text-[0.82rem] leading-5 text-muted-foreground">
                            {item.description}
                          </span>
                        </span>
                      </button>
                    );
                  })}
                </div>
              </section>
            ))
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
