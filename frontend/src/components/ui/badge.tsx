/* eslint-disable react-refresh/only-export-components */
import { mergeProps } from "@base-ui/react/merge-props";
import { useRender } from "@base-ui/react/use-render";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "neu-surface-base inline-flex min-h-6 w-fit shrink-0 items-center justify-center gap-1 overflow-hidden rounded-[var(--neu-radius-pill)] border px-2.5 py-0.5 text-[10px] font-semibold uppercase whitespace-nowrap transition-all [&>svg]:pointer-events-none [&>svg]:size-3.5!",
  {
    variants: {
      variant: {
        default:
          "neu-surface-raised text-[var(--neu-accent)] border-[color:color-mix(in_oklch,var(--neu-accent)_18%,var(--neu-stroke-soft))] bg-[color:color-mix(in_oklch,var(--neu-accent)_10%,var(--neu-surface-raised))]",
        secondary:
          "neu-surface-raised text-[var(--neu-text-muted)] border-[color:var(--neu-stroke-soft)]",
        destructive:
          "neu-surface-raised text-[var(--neu-danger)] border-[color:color-mix(in_oklch,var(--neu-danger)_18%,var(--neu-stroke-soft))] bg-[color:color-mix(in_oklch,var(--neu-danger)_10%,var(--neu-surface-raised))]",
        outline:
          "neu-surface-flat text-[var(--neu-text-strong)] border-[color:var(--neu-stroke-soft)] bg-transparent",
        ghost:
          "neu-surface-inset text-[var(--neu-text-muted)] border-transparent shadow-none",
        link: "border-none bg-transparent px-0 text-[var(--neu-accent)] shadow-none hover:underline",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
);

function Badge({
  className,
  variant = "default",
  render,
  ...props
}: useRender.ComponentProps<"span"> & VariantProps<typeof badgeVariants>) {
  return useRender({
    defaultTagName: "span",
    props: mergeProps<"span">(
      {
        className: cn(badgeVariants({ variant }), className),
      },
      props,
    ),
    render,
    state: {
      slot: "badge",
      variant,
    },
  });
}

export { Badge, badgeVariants };
