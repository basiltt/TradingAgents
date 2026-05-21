import { useEffect } from "react";
import { useAppSelector } from "@/store";
import {
  persistNeuAppearance,
  NEU_ACCENT_STORAGE_KEY,
  NEU_CONTRAST_STORAGE_KEY,
  NEU_MODE_STORAGE_KEY,
} from "@/design-system/neumorphism";

export function useThemeEffect() {
  const { mode, accent, contrast } = useAppSelector((s) => s.neuUi);

  useEffect(() => {
    const root = document.documentElement;
    const resolved = mode === "graphite" ? "dark" : "light";

    root.classList.add("neu-theme");
    root.classList.toggle("dark", resolved === "dark");
    root.dataset.theme = resolved;
    root.dataset.neuMode = mode;
    root.dataset.neuAccent = accent;
    root.dataset.neuContrast = contrast;
    root.style.colorScheme = resolved;

    return () => {
      root.classList.remove("neu-theme");
      delete root.dataset.neuMode;
      delete root.dataset.neuAccent;
      delete root.dataset.neuContrast;
    };
  }, [accent, contrast, mode]);

  useEffect(() => {
    persistNeuAppearance({ mode, accent, contrast });
    window.localStorage.setItem(NEU_MODE_STORAGE_KEY, mode);
    window.localStorage.setItem(NEU_ACCENT_STORAGE_KEY, accent);
    window.localStorage.setItem(NEU_CONTRAST_STORAGE_KEY, contrast);
  }, [accent, contrast, mode]);
}
