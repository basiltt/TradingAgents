import {
  cloneElement,
  createElement,
  isValidElement,
  type CSSProperties,
  type HTMLAttributes,
  type ReactElement,
  type ReactNode,
} from "react";
import { cn } from "@/lib/utils";
import {
  DEFAULT_NEU_ACCENT,
  DEFAULT_NEU_CONTRAST,
  DEFAULT_NEU_MODE,
} from "./theme";
import type {
  NeuAccentPalette,
  NeuContrastMode,
  NeuDepth,
  NeuPadding,
  NeuRadius,
  NeuSurfaceMode,
  NeuTone,
} from "./types";

const radiusClasses: Record<NeuRadius, string> = {
  sm: "rounded-[var(--neu-radius-sm)]",
  md: "rounded-[var(--neu-radius-md)]",
  lg: "rounded-[var(--neu-radius-lg)]",
  full: "rounded-[var(--neu-radius-pill)]",
};

const paddingClasses: Record<NeuPadding, string> = {
  none: "p-0",
  sm: "p-3",
  md: "p-4",
  lg: "p-6",
};

const depthClasses: Record<NeuDepth, string> = {
  raised: "neu-surface-raised",
  inset: "neu-surface-inset",
  flat: "neu-surface-flat",
  accent: "neu-surface-accent",
  disabled: "neu-surface-disabled",
};

const toneStyleMap: Record<NeuTone, CSSProperties | undefined> = {
  neutral: undefined,
  accent: {
    borderColor: "color-mix(in oklch, var(--neu-accent) 28%, var(--neu-stroke-soft))",
  },
  success: {
    borderColor: "color-mix(in oklch, var(--neu-success) 28%, var(--neu-stroke-soft))",
  },
  warning: {
    borderColor: "color-mix(in oklch, var(--neu-warning) 28%, var(--neu-stroke-soft))",
  },
  danger: {
    borderColor: "color-mix(in oklch, var(--neu-danger) 28%, var(--neu-stroke-soft))",
  },
};

function renderSlotLike({
  asChild,
  children,
  className,
  style,
  props,
  tag,
}: {
  asChild?: boolean;
  children: ReactNode;
  className: string;
  style?: CSSProperties;
  props?: HTMLAttributes<HTMLElement>;
  tag: keyof HTMLElementTagNameMap;
}) {
  if (asChild && isValidElement(children)) {
    const child = children as ReactElement<{ className?: string; style?: CSSProperties }>;
    return cloneElement(child, {
      ...props,
      className: cn(child.props.className, className),
      style: { ...style, ...child.props.style },
    });
  }

  return createElement(tag, { ...props, className, style }, children);
}

export function NeuThemeScope({
  mode = DEFAULT_NEU_MODE,
  accent = DEFAULT_NEU_ACCENT,
  contrast = DEFAULT_NEU_CONTRAST,
  className,
  children,
}: {
  mode?: NeuSurfaceMode;
  accent?: NeuAccentPalette;
  contrast?: NeuContrastMode;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div
      data-neu-mode={mode}
      data-neu-accent={accent}
      data-neu-contrast={contrast}
      className={cn("neu-theme neu-app-bg relative isolate overflow-hidden", className)}
    >
      {children}
    </div>
  );
}

export function NeuSurface({
  asChild,
  children,
  depth = "raised",
  tone = "neutral",
  radius = "md",
  padding = "md",
  interactive = false,
  className,
  style,
  ...props
}: HTMLAttributes<HTMLElement> & {
  asChild?: boolean;
  children: ReactNode;
  depth?: NeuDepth;
  tone?: NeuTone;
  radius?: NeuRadius;
  padding?: NeuPadding;
  interactive?: boolean;
}) {
  return renderSlotLike({
    asChild,
    children,
    tag: "div",
    props,
    style: { ...toneStyleMap[tone], ...style },
    className: cn(
      "neu-surface-base relative overflow-hidden",
      depthClasses[depth],
      radiusClasses[radius],
      paddingClasses[padding],
      interactive && "neu-interactive cursor-pointer",
      className,
    ),
  });
}

export function NeuPanel({
  title,
  description,
  actions,
  footer,
  depth = "raised",
  dense = false,
  scrollable = false,
  loading = false,
  empty = false,
  className,
  children,
}: {
  title?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  footer?: ReactNode;
  depth?: NeuDepth;
  dense?: boolean;
  scrollable?: boolean;
  loading?: boolean;
  empty?: boolean;
  className?: string;
  children?: ReactNode;
}) {
  return (
    <NeuSurface
      depth={depth}
      radius="lg"
      padding={dense ? "sm" : "md"}
      className={cn("flex flex-col gap-4", className)}
    >
      {(title || description || actions) && (
        <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
          <div className="space-y-1">
            {title ? (
              <h3 className="text-base font-semibold tracking-[-0.02em]" style={{ color: "var(--neu-text-strong)" }}>
                {title}
              </h3>
            ) : null}
            {description ? (
              <p className="text-sm leading-6" style={{ color: "var(--neu-text-muted)" }}>
                {description}
              </p>
            ) : null}
          </div>
          {actions ? <div className="flex flex-wrap gap-2">{actions}</div> : null}
        </div>
      )}

      <div
        className={cn(
          "min-h-0",
          scrollable && "neu-scrollbar max-h-[32rem] overflow-auto pr-1",
          empty && "flex min-h-52 items-center justify-center",
          loading && "animate-pulse",
        )}
      >
        {children}
      </div>

      {footer ? (
        <>
          <NeuDivider />
          <div className="flex flex-wrap items-center justify-between gap-3">{footer}</div>
        </>
      ) : null}
    </NeuSurface>
  );
}

export function NeuWell({
  padding = "md",
  scrollable = false,
  minHeight,
  focused = false,
  disabled = false,
  className,
  children,
}: {
  padding?: NeuPadding;
  scrollable?: boolean;
  minHeight?: number | string;
  focused?: boolean;
  disabled?: boolean;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div
      className={cn(
        "neu-surface-base neu-surface-inset min-h-0",
        radiusClasses.md,
        paddingClasses[padding],
        scrollable && "neu-scrollbar overflow-auto",
        focused && "ring-2 ring-offset-0",
        disabled && "opacity-70",
        className,
      )}
      style={{
        minHeight,
        borderColor: focused
          ? "color-mix(in oklch, var(--neu-accent) 24%, var(--neu-stroke-soft))"
          : undefined,
      }}
    >
      {children}
    </div>
  );
}

export function NeuDivider({
  orientation = "horizontal",
  decorative = true,
  inset = false,
  className,
}: {
  orientation?: "horizontal" | "vertical";
  decorative?: boolean;
  inset?: boolean;
  className?: string;
}) {
  return (
    <div
      role={decorative ? "presentation" : "separator"}
      aria-orientation={decorative ? undefined : orientation}
      className={cn(
        orientation === "horizontal" ? "neu-divider-h w-full" : "neu-divider-v h-full",
        inset && (orientation === "horizontal" ? "mx-2" : "my-2"),
        className,
      )}
    />
  );
}

export function NeuGlowAccent({
  tone = "accent",
  size = "md",
  subtle = false,
  className,
}: {
  tone?: Extract<NeuTone, "accent" | "success" | "warning" | "danger">;
  size?: "sm" | "md" | "lg";
  subtle?: boolean;
  className?: string;
}) {
  const sizeClass =
    size === "sm" ? "h-16 w-16" : size === "lg" ? "h-32 w-32" : "h-24 w-24";

  const background =
    tone === "success"
      ? "radial-gradient(circle, color-mix(in oklch, var(--neu-success) 26%, white), transparent 72%)"
      : tone === "warning"
        ? "radial-gradient(circle, color-mix(in oklch, var(--neu-warning) 26%, white), transparent 72%)"
        : tone === "danger"
          ? "radial-gradient(circle, color-mix(in oklch, var(--neu-danger) 26%, white), transparent 72%)"
          : "radial-gradient(circle, color-mix(in oklch, var(--neu-accent) 24%, white), transparent 72%)";

  return (
    <div
      aria-hidden="true"
      className={cn("pointer-events-none rounded-full blur-2xl", sizeClass, className)}
      style={{ background, opacity: subtle ? 0.32 : 0.5 }}
    />
  );
}
