import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { NeuSurface } from "./foundation";

function NeuTemplateFrame({
  children,
  padding = "lg",
  className,
}: {
  children: ReactNode;
  padding?: "md" | "lg";
  className?: string;
}) {
  return (
    <NeuSurface depth="flat" radius="lg" padding={padding} className={cn("space-y-5", className)}>
      {children}
    </NeuSurface>
  );
}

export function NeuOverviewTemplate({
  header,
  hero,
  primary,
  secondary,
  activity,
  aside,
}: {
  header: ReactNode;
  hero: ReactNode;
  primary: ReactNode;
  secondary?: ReactNode;
  activity?: ReactNode;
  aside?: ReactNode;
}) {
  return (
    <div className="space-y-5">
      {header}
      {hero}
      <NeuTemplateFrame>
        <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_22rem]">
          <div className="space-y-5">
            {primary}
            {secondary}
            {activity}
          </div>
          {aside ? <div className="space-y-5">{aside}</div> : null}
        </div>
      </NeuTemplateFrame>
    </div>
  );
}

export function NeuWizardTemplate({
  header,
  stepRail,
  content,
  summary,
  footer,
}: {
  header: ReactNode;
  stepRail: ReactNode;
  content: ReactNode;
  summary?: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <div className="space-y-5">
      {header}
      <NeuTemplateFrame>
        <div className="grid gap-5 xl:grid-cols-[16rem_minmax(0,1fr)_20rem]">
          <NeuSurface depth="inset" radius="lg" padding="md" className="space-y-4">{stepRail}</NeuSurface>
          <NeuSurface depth="raised" radius="lg" padding="lg" className="space-y-5">
            {content}
            {footer ? <div>{footer}</div> : null}
          </NeuSurface>
          {summary ? <NeuSurface depth="inset" radius="lg" padding="md">{summary}</NeuSurface> : null}
        </div>
      </NeuTemplateFrame>
    </div>
  );
}

export function NeuConsoleTemplate({
  header,
  status,
  stats,
  primary,
  secondary,
  reports,
}: {
  header: ReactNode;
  status?: ReactNode;
  stats?: ReactNode;
  primary: ReactNode;
  secondary: ReactNode;
  reports: ReactNode;
}) {
  return (
    <div className="space-y-5">
      {header}
      {status}
      {stats}
      <NeuTemplateFrame>
        <div className="grid gap-5 xl:grid-cols-2">
          {primary}
          {secondary}
        </div>
        {reports}
      </NeuTemplateFrame>
    </div>
  );
}

export function NeuArchiveTemplate({
  header,
  filters,
  results,
  pagination,
  bulkActions,
}: {
  header: ReactNode;
  filters?: ReactNode;
  results: ReactNode;
  pagination?: ReactNode;
  bulkActions?: ReactNode;
}) {
  return (
    <div className="space-y-5">
      {header}
      <NeuTemplateFrame>
        {filters}
        {bulkActions}
        {results}
        {pagination}
      </NeuTemplateFrame>
    </div>
  );
}

export function NeuWorkbenchTemplate({
  header,
  controls,
  results,
  secondaryActions,
  aside,
}: {
  header: ReactNode;
  controls: ReactNode;
  results: ReactNode;
  secondaryActions?: ReactNode;
  aside?: ReactNode;
}) {
  return (
    <div className="space-y-5">
      {header}
      <NeuTemplateFrame>
        <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_22rem]">
          <div className="space-y-5">
            {controls}
            {secondaryActions}
            {results}
          </div>
          {aside ? <div className="space-y-5">{aside}</div> : null}
        </div>
      </NeuTemplateFrame>
    </div>
  );
}

export function NeuPortfolioGridTemplate({
  header,
  filters,
  stats,
  grid,
  aside,
}: {
  header: ReactNode;
  filters?: ReactNode;
  stats?: ReactNode;
  grid: ReactNode;
  aside?: ReactNode;
}) {
  return (
    <div className="space-y-5">
      {header}
      <NeuTemplateFrame>
        {filters}
        {stats}
        <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_20rem]">
          {grid}
          {aside ? <div className="space-y-5">{aside}</div> : null}
        </div>
      </NeuTemplateFrame>
    </div>
  );
}

export function NeuEntityDetailTemplate({
  header,
  summary,
  tabs,
  content,
  aside,
}: {
  header: ReactNode;
  summary?: ReactNode;
  tabs?: ReactNode;
  content: ReactNode;
  aside?: ReactNode;
}) {
  return (
    <div className="space-y-5">
      {header}
      <NeuTemplateFrame>
        {summary}
        {tabs}
        <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_22rem]">
          {content}
          {aside ? <div className="space-y-5">{aside}</div> : null}
        </div>
      </NeuTemplateFrame>
    </div>
  );
}

export function NeuAnalyticsTemplate({
  header,
  controls,
  kpis,
  charts,
  aside,
  footerActions,
}: {
  header: ReactNode;
  controls?: ReactNode;
  kpis?: ReactNode;
  charts: ReactNode;
  aside?: ReactNode;
  footerActions?: ReactNode;
}) {
  return (
    <div className="space-y-5">
      {header}
      <NeuTemplateFrame>
        {controls}
        {kpis}
        <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_20rem]">
          {charts}
          {aside ? <div className="space-y-5">{aside}</div> : null}
        </div>
        {footerActions}
      </NeuTemplateFrame>
    </div>
  );
}

export function NeuLibraryTemplate({
  header,
  filters,
  grid,
  dialogSlot,
}: {
  header: ReactNode;
  filters?: ReactNode;
  grid: ReactNode;
  dialogSlot?: ReactNode;
}) {
  return (
    <div className="space-y-5">
      {header}
      <NeuTemplateFrame>
        {filters}
        {grid}
        {dialogSlot}
      </NeuTemplateFrame>
    </div>
  );
}

export function NeuTableIndexTemplate({
  header,
  toolbar,
  table,
  pagination,
  aside,
}: {
  header: ReactNode;
  toolbar?: ReactNode;
  table: ReactNode;
  pagination?: ReactNode;
  aside?: ReactNode;
}) {
  return (
    <div className="space-y-5">
      {header}
      <NeuTemplateFrame>
        {toolbar}
        <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_20rem]">
          <div className="space-y-5">
            {table}
            {pagination}
          </div>
          {aside ? <div className="space-y-5">{aside}</div> : null}
        </div>
      </NeuTemplateFrame>
    </div>
  );
}

export function NeuInspectorTemplate({
  header,
  controls,
  inspector,
  notes,
  aside,
}: {
  header: ReactNode;
  controls?: ReactNode;
  inspector: ReactNode;
  notes?: ReactNode;
  aside?: ReactNode;
}) {
  return (
    <div className="space-y-5">
      {header}
      <NeuTemplateFrame>
        {controls}
        <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_22rem]">
          <div className="space-y-5">
            {inspector}
            {notes}
          </div>
          {aside ? <div className="space-y-5">{aside}</div> : null}
        </div>
      </NeuTemplateFrame>
    </div>
  );
}
