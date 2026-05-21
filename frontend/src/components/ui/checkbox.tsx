import { Checkbox as CheckboxPrimitive } from "@base-ui/react/checkbox";
import { CheckIcon } from "lucide-react";
import { cn } from "@/lib/utils";

function Checkbox({ className, ...props }: CheckboxPrimitive.Root.Props) {
  return (
    <CheckboxPrimitive.Root
      data-slot="checkbox"
      className={cn(
        "neu-focus-ring neu-surface-base neu-surface-inset peer relative flex size-5 shrink-0 items-center justify-center rounded-[10px] border border-[color:var(--neu-stroke-soft)] text-[var(--neu-accent-ink)] transition group-has-disabled/field:opacity-50 disabled:cursor-not-allowed disabled:opacity-50 data-checked:border-[color:color-mix(in_oklch,var(--neu-accent)_22%,var(--neu-stroke-soft))] data-checked:bg-[linear-gradient(145deg,color-mix(in_oklch,var(--neu-highlight)_26%,var(--neu-accent-muted)),color-mix(in_oklch,var(--neu-accent)_10%,var(--neu-surface-raised))_54%,color-mix(in_oklch,var(--neu-accent-muted)_88%,var(--neu-surface-raised)))] data-checked:shadow-[var(--neu-shadow-pill)]",
        className,
      )}
      {...props}
    >
      <CheckboxPrimitive.Indicator
        data-slot="checkbox-indicator"
        className="grid place-content-center text-current transition-none [&>svg]:size-3.5"
      >
        <CheckIcon />
      </CheckboxPrimitive.Indicator>
    </CheckboxPrimitive.Root>
  );
}

export { Checkbox };
