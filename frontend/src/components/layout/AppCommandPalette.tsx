/* eslint-disable react-hooks/set-state-in-effect */
import { useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate } from "@tanstack/react-router";
import {
  Contrast,
  Menu,
  MoonStar,
  Search,
  SunMedium,
  SwatchBook,
} from "lucide-react";
import {
  neuAccentDefinitions,
  NeuCommandPalette,
  setNeuAccent,
  setNeuContrast,
  setNeuMode,
  setSidebarCollapsed,
} from "@/design-system/neumorphism";
import { navSections } from "@/components/layout/navigation";
import { useAppDispatch, useAppSelector } from "@/store";

export function AppCommandPalette({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const navigate = useNavigate();
  const pathname = useLocation({ select: (location) => location.pathname });
  const dispatch = useAppDispatch();
  const { mode, accent, contrast, sidebarCollapsed } = useAppSelector((state) => state.neuUi);
  const [query, setQuery] = useState("");

  useEffect(() => {
    if (!open) {
      setQuery("");
    }
  }, [open]);

  const groups = useMemo(() => {
    const routeGroups = navSections.map((section) => ({
      id: section.title.toLowerCase().replaceAll(" ", "-"),
      title: section.title,
      items: section.items.map((item) => {
        const Icon = item.icon;
        return {
          id: item.id,
          label: item.label,
          description: item.description,
          icon: <Icon className="size-4.5" />,
          active: item.matches(pathname),
          keywords: item.keywords,
          onSelect: () => navigate({ to: item.to as never }),
        };
      }),
    }));

    const appearanceGroup = {
      id: "appearance",
      title: "Appearance",
      items: [
        {
          id: "mode-ivory",
          label: "Switch to Ivory mode",
          description: "Use the light-field neumorphic surface set.",
          icon: <SunMedium className="size-4.5" />,
          active: mode === "ivory",
          keywords: ["theme", "light", "ivory", "surface"],
          onSelect: () => dispatch(setNeuMode("ivory")),
        },
        {
          id: "mode-graphite",
          label: "Switch to Graphite mode",
          description: "Use the dark-field neumorphic surface set.",
          icon: <MoonStar className="size-4.5" />,
          active: mode === "graphite",
          keywords: ["theme", "dark", "graphite", "surface"],
          onSelect: () => dispatch(setNeuMode("graphite")),
        },
        {
          id: "contrast-balanced",
          label: "Use balanced contrast",
          description: "Default contrast tuned for dense dashboards.",
          icon: <Contrast className="size-4.5" />,
          active: contrast === "balanced",
          keywords: ["contrast", "balanced", "default"],
          onSelect: () => dispatch(setNeuContrast("balanced")),
        },
        {
          id: "contrast-high",
          label: "Enable high contrast",
          description: "Increase edge definition across panels and tables.",
          icon: <Contrast className="size-4.5" />,
          active: contrast === "high",
          keywords: ["contrast", "high", "accessible"],
          onSelect: () => dispatch(setNeuContrast("high")),
        },
        ...Object.values(neuAccentDefinitions).map((definition) => ({
          id: `accent-${definition.key}`,
          label: `Activate ${definition.label}`,
          description: definition.description,
          icon: <SwatchBook className="size-4.5" />,
          active: accent === definition.key,
          keywords: ["accent", definition.key, definition.label.toLowerCase()],
          onSelect: () => dispatch(setNeuAccent(definition.key)),
        })),
      ],
    };

    const shellGroup = {
      id: "shell",
      title: "Shell",
      items: [
        {
          id: "sidebar-toggle",
          label: sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar",
          description: "Toggle the primary navigation density for desktop layouts.",
          icon: <Menu className="size-4.5" />,
          active: sidebarCollapsed,
          keywords: ["sidebar", "nav", "collapse", "expand"],
          onSelect: () => dispatch(setSidebarCollapsed(!sidebarCollapsed)),
        },
        {
          id: "focus-search",
          label: "Focus command search",
          description: "Keep the palette open and reset the query field.",
          icon: <Search className="size-4.5" />,
          keywords: ["command", "search", "palette"],
          onSelect: () => setQuery(""),
        },
      ],
    };

    return [...routeGroups, appearanceGroup, shellGroup];
  }, [accent, contrast, dispatch, mode, navigate, pathname, sidebarCollapsed]);

  return (
    <NeuCommandPalette
      open={open}
      query={query}
      groups={groups}
      onOpenChange={onOpenChange}
      onQueryChange={setQuery}
      onSelect={() => {
        setQuery("");
        onOpenChange(false);
      }}
    />
  );
}
