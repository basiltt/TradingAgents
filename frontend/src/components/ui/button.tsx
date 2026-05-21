/* eslint-disable react-refresh/only-export-components */
import { Button as ButtonPrimitive } from "@base-ui/react/button"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

const buttonVariants = cva(
  "group/button inline-flex shrink-0 items-center justify-center rounded-[calc(var(--radius)*1.2)] border text-sm font-medium whitespace-nowrap shadow-[var(--shadow-soft)] outline-none select-none focus-visible:border-ring focus-visible:ring-4 focus-visible:ring-ring/20 active:scale-[0.98] disabled:pointer-events-none disabled:opacity-50 disabled:shadow-none aria-invalid:border-destructive aria-invalid:ring-4 aria-invalid:ring-destructive/15 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        default:
          "border-primary/25 bg-[linear-gradient(135deg,oklch(0.62_var(--accent-chroma)_var(--accent-hue)),oklch(0.69_var(--accent-2-chroma)_var(--accent-2-hue)))] text-primary-foreground hover:-translate-y-0.5 hover:brightness-105 hover:shadow-[var(--shadow-accent)]",
        outline:
          "border-border/70 bg-card/72 text-foreground hover:-translate-y-0.5 hover:border-border hover:bg-card/92 hover:shadow-[var(--shadow-card)] aria-expanded:bg-card/92 aria-expanded:text-foreground",
        secondary:
          "border-transparent bg-secondary/90 text-secondary-foreground hover:-translate-y-0.5 hover:bg-secondary hover:shadow-[var(--shadow-soft)] aria-expanded:bg-secondary",
        ghost:
          "border-transparent bg-transparent text-muted-foreground shadow-none hover:bg-accent/80 hover:text-foreground aria-expanded:bg-accent/80 aria-expanded:text-foreground",
        destructive:
          "border-destructive/25 bg-destructive/12 text-destructive hover:-translate-y-0.5 hover:bg-destructive/18 hover:shadow-[var(--shadow-soft)] focus-visible:border-destructive/40 focus-visible:ring-destructive/20",
        link: "text-primary underline-offset-4 hover:underline",
      },
      size: {
        default:
          "h-10 gap-2 px-4 has-data-[icon=inline-end]:pr-3 has-data-[icon=inline-start]:pl-3",
        xs: "h-8 gap-1 rounded-[calc(var(--radius)*1.05)] px-3 text-xs has-data-[icon=inline-end]:pr-2.5 has-data-[icon=inline-start]:pl-2.5 [&_svg:not([class*='size-'])]:size-3.5",
        sm: "h-9 gap-1.5 rounded-[calc(var(--radius)*1.1)] px-3.5 text-[0.82rem] has-data-[icon=inline-end]:pr-3 has-data-[icon=inline-start]:pl-3 [&_svg:not([class*='size-'])]:size-3.5",
        lg: "h-11 gap-2 px-5 text-sm has-data-[icon=inline-end]:pr-4 has-data-[icon=inline-start]:pl-4",
        icon: "size-10",
        "icon-xs":
          "size-8 rounded-[calc(var(--radius)*1.05)] [&_svg:not([class*='size-'])]:size-3.5",
        "icon-sm":
          "size-9 rounded-[calc(var(--radius)*1.1)]",
        "icon-lg": "size-11",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

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
  )
}

export { Button, buttonVariants }
