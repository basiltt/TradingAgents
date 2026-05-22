/* eslint-disable react-hooks/set-state-in-effect */
import { useEffect, useMemo, useRef, useState } from "react";
import { cn } from "@/lib/utils";

const NUMBER_PATTERN =
  /^([^0-9+-]*)([-+]?(?:\d[\d,]*\.?\d*|\d*\.?\d+))(.*)$/;

function parseDisplayValue(value: string) {
  const match = value.trim().match(NUMBER_PATTERN);
  if (!match) return null;

  const [, prefix, rawNumber, suffix] = match;
  const normalized = Number(rawNumber.replaceAll(",", ""));
  if (!Number.isFinite(normalized)) return null;

  const fractional = rawNumber.split(".")[1];

  return {
    prefix,
    number: normalized,
    suffix,
    decimals: fractional?.length ?? 0,
  };
}

function formatAnimatedValue(value: number, decimals: number) {
  return value.toLocaleString(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

export function AnimatedNumber({
  value,
  className,
  duration = 540,
}: {
  value: string | number;
  className?: string;
  duration?: number;
}) {
  const display = typeof value === "number" ? String(value) : value;
  const parsed = useMemo(() => parseDisplayValue(display), [display]);
  const [animated, setAnimated] = useState(() => parsed?.number ?? 0);
  const previousValueRef = useRef(parsed?.number ?? 0);

  useEffect(() => {
    if (!parsed) return;

    const mediaQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
    if (mediaQuery.matches) {
      previousValueRef.current = parsed.number;
      setAnimated(parsed.number);
      return;
    }

    const start = previousValueRef.current;
    const end = parsed.number;

    if (start === end) {
      setAnimated(end);
      return;
    }

    let frame = 0;
    let startTime = 0;

    const tick = (time: number) => {
      if (!startTime) startTime = time;
      const progress = Math.min((time - startTime) / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      const next = start + (end - start) * eased;
      setAnimated(next);

      if (progress < 1) {
        frame = window.requestAnimationFrame(tick);
      } else {
        previousValueRef.current = end;
        setAnimated(end);
      }
    };

    frame = window.requestAnimationFrame(tick);

    return () => window.cancelAnimationFrame(frame);
  }, [duration, parsed]);

  if (!parsed) {
    return <span className={className}>{display}</span>;
  }

  return (
    <span className={cn("tabular-nums", className)}>
      {parsed.prefix}
      {formatAnimatedValue(animated, parsed.decimals)}
      {parsed.suffix}
    </span>
  );
}
