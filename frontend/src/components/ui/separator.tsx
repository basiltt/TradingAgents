import { Separator as SeparatorPrimitive } from "@base-ui/react/separator";
import { cn } from "@/lib/utils";

function Separator({
  className,
  orientation = "horizontal",
  ...props
}: SeparatorPrimitive.Props) {
  return (
    <SeparatorPrimitive
      data-slot="separator"
      orientation={orientation}
      className={cn(
        "shrink-0 data-horizontal:h-px data-horizontal:w-full data-horizontal:bg-[linear-gradient(90deg,transparent,color-mix(in_oklch,var(--neu-text-soft)_22%,transparent),transparent)] data-vertical:w-px data-vertical:self-stretch data-vertical:bg-[linear-gradient(180deg,transparent,color-mix(in_oklch,var(--neu-text-soft)_22%,transparent),transparent)]",
        className,
      )}
      {...props}
    />
  );
}

export { Separator };
