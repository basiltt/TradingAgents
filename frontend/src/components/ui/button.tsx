/* eslint-disable react-refresh/only-export-components */
import { Button as ButtonPrimitive } from "@base-ui/react/button";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "neu-focus-ring neu-ripple inline-flex shrink-0 items-center justify-center gap-2 font-semibold whitespace-nowrap transition duration-150 disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        default: "neu-surface-base neu-button-primary neu-interactive text-[var(--neu-accent-ink)]",
        outline: "neu-surface-base neu-button-secondary neu-interactive text-[var(--neu-text-strong)]",
        secondary: "neu-surface-base neu-button-tonal neu-interactive text-[var(--neu-accent-ink)]",
        ghost: "neu-surface-base neu-button-ghost neu-interactive text-[var(--neu-text-muted)]",
        destructive: "neu-surface-base neu-button-danger neu-interactive",
        link: "border-none bg-transparent px-0 text-[var(--neu-accent)] shadow-none hover:underline",
      },
      size: {
        default: "h-9.5 rounded-[var(--neu-radius-md)] px-3.5 text-xs has-data-[icon=inline-end]:pr-3 has-data-[icon=inline-start]:pl-3 sm:h-11 sm:px-4 sm:text-sm sm:has-data-[icon=inline-end]:pr-3.5 sm:has-data-[icon=inline-start]:pl-3.5",
        xs: "h-7 rounded-[var(--neu-radius-sm)] px-2 text-[0.68rem] has-data-[icon=inline-end]:pr-1.5 has-data-[icon=inline-start]:pl-1.5 sm:h-8 sm:px-2.5 sm:text-[0.72rem] sm:has-data-[icon=inline-end]:pr-2 sm:has-data-[icon=inline-start]:pl-2",
        sm: "h-8.5 rounded-[var(--neu-radius-sm)] px-3 text-[0.75rem] has-data-[icon=inline-end]:pr-2.5 has-data-[icon=inline-start]:pl-2.5 sm:h-9 sm:px-3 sm:text-[0.8rem] sm:has-data-[icon=inline-end]:pr-2.5 sm:has-data-[icon=inline-start]:pl-2.5",
        lg: "h-11 rounded-[var(--neu-radius-md)] px-4.5 text-xs has-data-[icon=inline-end]:pr-3.5 has-data-[icon=inline-start]:pl-3.5 sm:h-12 sm:px-5 sm:text-sm sm:has-data-[icon=inline-end]:pr-4 sm:has-data-[icon=inline-start]:pl-4",
        icon: "size-9 rounded-[var(--neu-radius-md)] p-0 sm:size-11",
        "icon-xs": "size-7 rounded-[var(--neu-radius-sm)] p-0 [&_svg:not([class*='size-'])]:size-3 sm:size-8 sm:[&_svg:not([class*='size-'])]:size-3.5",
        "icon-sm": "size-8 rounded-[var(--neu-radius-sm)] p-0 sm:size-9",
        "icon-lg": "size-10 rounded-[var(--neu-radius-md)] p-0 sm:size-12",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
);

function Button({
  className,
  variant = "default",
  size = "default",
  ...props
}: ButtonPrimitive.Props & VariantProps<typeof buttonVariants>) {
  return (
    <ButtonPrimitive
      data-slot="button"
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  );
}

export { Button, buttonVariants };
