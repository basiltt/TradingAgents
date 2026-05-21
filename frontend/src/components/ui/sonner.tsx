"use client";

import type { CSSProperties } from "react";
import { Toaster as Sonner, type ToasterProps } from "sonner";
import {
  CircleCheckIcon,
  InfoIcon,
  Loader2Icon,
  OctagonXIcon,
  TriangleAlertIcon,
} from "lucide-react";
import { useAppSelector } from "@/store";

const Toaster = ({ ...props }: ToasterProps) => {
  const mode = useAppSelector((state) => state.neuUi.mode);

  return (
    <Sonner
      theme={mode === "graphite" ? "dark" : "light"}
      className="toaster group"
      icons={{
        success: <CircleCheckIcon className="size-4" />,
        info: <InfoIcon className="size-4" />,
        warning: <TriangleAlertIcon className="size-4" />,
        error: <OctagonXIcon className="size-4" />,
        loading: <Loader2Icon className="size-4 animate-spin" />,
      }}
      style={
        {
          "--normal-bg": "var(--popover)",
          "--normal-text": "var(--popover-foreground)",
          "--normal-border": "var(--border)",
          "--border-radius": "var(--neu-radius-lg)",
        } as CSSProperties
      }
      toastOptions={{
        classNames: {
          toast:
            "neu-surface-base neu-surface-raised rounded-[var(--neu-radius-lg)] border border-[color:var(--neu-stroke-soft)] bg-[var(--popover)] text-[var(--popover-foreground)] shadow-[var(--neu-shadow-float)]",
          title: "font-semibold tracking-[-0.02em]",
          description: "text-[var(--neu-text-muted)]",
        },
      }}
      {...props}
    />
  );
};

export { Toaster };
