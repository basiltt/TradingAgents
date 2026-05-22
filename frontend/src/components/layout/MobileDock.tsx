import { useNavigate } from "@tanstack/react-router";
import { NeuMobileDock } from "@/design-system/neumorphism";
import { mobileDockItems } from "@/components/layout/navigation";

export function MobileDock({
  pathname,
  onMore,
}: {
  pathname: string;
  onMore: () => void;
}) {
  const navigate = useNavigate();

  const items = mobileDockItems.map((item) => {
    const Icon = item.icon;

    let isActive: boolean;
    if (item.id === "home") {
      isActive = pathname === "/";
    } else if (item.id === "scanner") {
      isActive = pathname.startsWith("/scanner");
    } else if (item.id === "accounts") {
      isActive = pathname.startsWith("/accounts");
    } else if (item.id === "analytics") {
      isActive = pathname.startsWith("/analytics");
    } else {
      isActive = item.matches(pathname);
    }

    return {
      id: item.id,
      label: item.shortLabel ?? item.label,
      icon: <Icon className="size-4.5" />,
      active: isActive,
      onSelect: () => navigate({ to: item.to as never }),
    };
  });

  const anyDockItemActive = items.some((i) => i.active);

  return (
    <NeuMobileDock
      items={items}
      menuActive={!anyDockItemActive}
      onMore={onMore}
    />
  );
}
