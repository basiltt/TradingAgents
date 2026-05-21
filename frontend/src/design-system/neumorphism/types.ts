import type { ComponentType, ReactNode } from "react";

export type NeuTone = "neutral" | "accent" | "success" | "warning" | "danger";
export type NeuDepth = "raised" | "inset" | "flat" | "accent" | "disabled";
export type NeuRadius = "sm" | "md" | "lg" | "full";
export type NeuPadding = "none" | "sm" | "md" | "lg";
export type NeuSurfaceMode = "ivory" | "graphite";
export type NeuAccentPalette = "cobalt" | "sage" | "amber" | "rose";
export type NeuContrastMode = "balanced" | "high";

export interface NeuOption {
  value: string;
  label: string;
  description?: string;
  disabled?: boolean;
  group?: string;
  tone?: NeuTone;
  icon?: ReactNode;
  meta?: ReactNode;
  searchKeywords?: string[];
}

export interface NeuNavItemData {
  id: string;
  label: string;
  description?: string;
  href?: string;
  icon?: ComponentType<{ className?: string }>;
  badge?: ReactNode;
  active?: boolean;
  tone?: NeuTone;
  onSelect?: () => void;
}

export interface NeuNavSection {
  title: string;
  items: NeuNavItemData[];
}

export interface NeuCommandItem {
  id: string;
  label: string;
  description?: string;
  icon?: ReactNode;
  active?: boolean;
  keywords?: string[];
  meta?: ReactNode;
  tone?: NeuTone;
  onSelect: () => void;
}

export interface NeuCommandGroup {
  id: string;
  title: string;
  items: NeuCommandItem[];
}

export interface NeuMetric {
  label: string;
  value: ReactNode;
  tone?: NeuTone;
  icon?: ReactNode;
  delta?: ReactNode;
  trend?: "up" | "down" | "flat";
}

export interface NeuTableColumn<Row> {
  id: string;
  header: ReactNode;
  accessor?: keyof Row;
  cell?: (row: Row, index: number) => ReactNode;
  align?: "left" | "center" | "right";
  className?: string;
  mobileLabel?: string;
}

export interface NeuFilterChip {
  id: string;
  label: string;
  active?: boolean;
  count?: number;
  tone?: NeuTone;
  icon?: ReactNode;
  onSelect?: () => void;
}

export interface NeuPaginationState {
  page: number;
  pageSize: number;
  total: number;
}

export interface NeuPageZone {
  id: string;
  label: string;
  description?: string;
  emphasis?: "primary" | "secondary" | "supporting" | "actions";
}

export interface NeuRouteLayoutModel {
  route: string;
  title: string;
  navSection: string;
  template: string;
  headerVariant:
    | "overview"
    | "wizard"
    | "console"
    | "archive"
    | "workbench"
    | "portfolio"
    | "detail"
    | "analytics"
    | "library"
    | "table"
    | "inspector";
  desktopZones: NeuPageZone[];
  mobileZones: NeuPageZone[];
  alerts?: string[];
  drawers?: string[];
  touchActions?: string[];
}
