/* eslint-disable react-refresh/only-export-components */
import { Tabs as TabsPrimitive } from "@base-ui/react/tabs";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

function Tabs({
  className,
  orientation = "horizontal",
  ...props
}: TabsPrimitive.Root.Props) {
  return (
    <TabsPrimitive.Root
      data-slot="tabs"
      data-orientation={orientation}
      className={cn("group/tabs flex gap-3 data-horizontal:flex-col", className)}
      {...props}
    />
  );
}

const tabsListVariants = cva(
  "group/tabs-list inline-flex w-fit items-center justify-center rounded-[var(--neu-radius-md)] p-1.5 text-[var(--neu-text-muted)] group-data-horizontal/tabs:min-h-11 group-data-vertical/tabs:h-fit group-data-vertical/tabs:flex-col",
  {
    variants: {
      variant: {
        default: "neu-surface-base neu-surface-raised shadow-[var(--neu-shadow-pill)]",
        line: "gap-1 rounded-none border-b border-[color:var(--neu-stroke-soft)] bg-transparent p-0 shadow-none",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
);

function TabsList({
  className,
  variant = "default",
  ...props
}: TabsPrimitive.List.Props & VariantProps<typeof tabsListVariants>) {
  return (
    <TabsPrimitive.List
      data-slot="tabs-list"
      data-variant={variant}
      className={cn(tabsListVariants({ variant }), className)}
      {...props}
    />
  );
}

function TabsTrigger({ className, ...props }: TabsPrimitive.Tab.Props) {
  return (
    <TabsPrimitive.Tab
      data-slot="tabs-trigger"
      className={cn(
        "neu-focus-ring relative inline-flex min-h-[2.5rem] flex-1 items-center justify-center gap-1.5 rounded-[var(--neu-radius-sm)] border border-transparent px-3 py-2 text-sm font-semibold whitespace-nowrap text-[var(--neu-text-muted)] transition-all group-data-vertical/tabs:w-full group-data-vertical/tabs:justify-start disabled:pointer-events-none disabled:opacity-50 group-data-[variant=default]/tabs-list:data-active:border-none group-data-[variant=default]/tabs-list:data-active:bg-[var(--neu-surface-base)] group-data-[variant=default]/tabs-list:data-active:text-[var(--neu-text-strong)] group-data-[variant=default]/tabs-list:data-active:shadow-[var(--neu-shadow-raised-soft)]",
        "group-data-[variant=line]/tabs-list:rounded-none group-data-[variant=line]/tabs-list:border-b-2 group-data-[variant=line]/tabs-list:border-transparent group-data-[variant=line]/tabs-list:px-1 group-data-[variant=line]/tabs-list:data-active:border-[color:var(--neu-accent)] group-data-[variant=line]/tabs-list:data-active:text-[var(--neu-text-strong)]",
        className,
      )}
      {...props}
    />
  );
}

function TabsContent({ className, ...props }: TabsPrimitive.Panel.Props) {
  return (
    <TabsPrimitive.Panel
      data-slot="tabs-content"
      className={cn("flex-1 text-sm outline-none", className)}
      {...props}
    />
  );
}

export { Tabs, TabsList, TabsTrigger, TabsContent, tabsListVariants };
