import { Link } from "@tanstack/react-router";
import { Menu } from "lucide-react";
import { cn } from "@/lib/utils";
import { mobileDockItems } from "@/components/layout/navigation";

export function MobileDock({
  pathname,
  onMore,
}: {
  pathname: string;
  onMore: () => void;
}) {
  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-0 z-40 px-3 pb-3 lg:hidden">
      <div className="mobile-dock-frame pointer-events-auto">
        {mobileDockItems.map((item) => {
          const Icon = item.icon;
          const active = item.matches(pathname);

          return (
            <Link
              key={item.id}
              to={item.to}
              className="mobile-dock-item"
              data-active={active}
              aria-label={item.label}
            >
              <Icon className="size-4.5" />
              <span>{item.shortLabel ?? item.label}</span>
            </Link>
          );
        })}

        <button
          type="button"
          onClick={onMore}
          className={cn("mobile-dock-item", "text-muted-foreground")}
          aria-label="Open full navigation"
        >
          <Menu className="size-4.5" />
          <span>More</span>
        </button>
      </div>
    </div>
  );
}
