import {
  NeuAppearanceStudio,
  setNeuAccent,
  setNeuContrast,
  setNeuMode,
} from "@/design-system/neumorphism";
import { useAppDispatch, useAppSelector } from "@/store";

export function AppearanceControls({
  className,
  compact = false,
}: {
  className?: string;
  compact?: boolean;
}) {
  const dispatch = useAppDispatch();
  const { mode, accent, contrast } = useAppSelector((state) => state.neuUi);

  return (
    <div className={className}>
      <NeuAppearanceStudio
        theme={mode}
        palette={accent}
        contrast={contrast}
        compact={compact}
        onThemeChange={(next) => dispatch(setNeuMode(next))}
        onPaletteChange={(next) => dispatch(setNeuAccent(next))}
        onContrastChange={(next) => dispatch(setNeuContrast(next))}
      />
    </div>
  );
}
