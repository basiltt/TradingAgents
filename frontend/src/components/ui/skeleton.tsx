import { cn } from "@/lib/utils";

function Skeleton({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="skeleton"
      className={cn(
        "neu-surface-base neu-surface-inset neu-skeleton-shimmer animate-pulse rounded-[var(--neu-radius-md)]",
        className,
      )}
      {...props}
    />
  );
}

export { Skeleton };
