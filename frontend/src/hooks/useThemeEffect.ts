import { useEffect } from "react";
import { useAppSelector } from "@/store";
import { applyContrast, applyPalette, persistAppearance, resolveThemeMode } from "@/lib/theme";

export function useThemeEffect() {
  const theme = useAppSelector((s) => s.ui.theme);
  const palette = useAppSelector((s) => s.ui.palette);
  const contrast = useAppSelector((s) => s.ui.contrast);

  useEffect(() => {
    const root = document.documentElement;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");

    const applyTheme = () => {
      const resolved = resolveThemeMode(theme, mq.matches);
      root.classList.toggle("dark", resolved === "dark");
      root.dataset.theme = resolved;
      root.style.colorScheme = resolved;
    };

    applyTheme();
    mq.addEventListener("change", applyTheme);

    return () => mq.removeEventListener("change", applyTheme);
  }, [theme]);

  useEffect(() => {
    const root = document.documentElement;
    applyPalette(root, palette);
    applyContrast(root, contrast);
    persistAppearance(theme, palette, contrast);
  }, [contrast, palette, theme]);
}
