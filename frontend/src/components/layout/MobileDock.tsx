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

  return (
    <NeuMobileDock
      items={mobileDockItems.map((item) => {
        const Icon = item.icon;
        return {
          id: item.id,
          label: item.shortLabel ?? item.label,
          icon: <Icon className="size-4.5" />,
          active: item.matches(pathname),
          onSelect: () => navigate({ to: item.to as never }),
        };
      })}
      onMore={onMore}
    />
  );
}
