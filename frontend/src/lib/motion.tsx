/**
 * @module motion
 *
 * Reusable Framer Motion wrapper components for the TradingAgents frontend.
 *
 * Every component in this module is a thin, opinionated wrapper around a
 * Framer Motion `motion.*` primitive.  They apply pre-configured variants and
 * transitions from `motion-constants` so that callers can add polished
 * animation with a single JSX element and zero inline motion config.
 *
 * All components are marked `"use client"` because Framer Motion requires a
 * browser environment.
 *
 * ### Component overview
 *
 * | Component        | Purpose                                              |
 * |------------------|------------------------------------------------------|
 * | `MotionSection`  | Fade-and-rise entrance for page sections             |
 * | `MotionList`     | Staggered list container                             |
 * | `MotionItem`     | Individual list-item child for `MotionList`          |
 * | `MotionPopup`    | Scale-and-blur entrance for modals / cards           |
 * | `MotionHover`    | Lift-and-scale on hover / tap                        |
 * | `MotionNumber`   | Animated numeric counter with eased interpolation    |
 * | `MotionPresence` | `AnimatePresence` wrapper with a sensible default    |
 * | `MotionSkeleton` | Pulsing skeleton placeholder                         |
 *
 * @example
 * ```tsx
 * import { MotionSection, MotionList, MotionItem } from "@/lib/motion";
 *
 * <MotionSection>
 *   <MotionList>
 *     {items.map(i => <MotionItem key={i.id}>{i.label}</MotionItem>)}
 *   </MotionList>
 * </MotionSection>
 * ```
 */
"use client";

import { motion, AnimatePresence } from "framer-motion";
import * as React from "react";

import {
  springs,
  easings,
  fadeInUp,
  scaleIn,
  listItem,
  staggerContainer,
  staggerContainerFast,
} from "./motion-constants";

/**
 * Animated page-section wrapper that fades upward on mount.
 *
 * Applies the `fadeInUp` variant with a `springs.gentle` transition so the
 * section eases into view without feeling abrupt.  An optional `delay`
 * parameter lets you stagger multiple sections on the same page.
 *
 * @param children - Section content.
 * @param className - Optional CSS class forwarded to the wrapping `div`.
 * @param delay - Extra delay in seconds before the animation starts (default `0`).
 *
 * @example
 * ```tsx
 * <MotionSection delay={0.1} className="mt-8">
 *   <h2>Portfolio Overview</h2>
 * </MotionSection>
 * ```
 */
export function MotionSection({
  children,
  className,
  delay = 0,
}: {
  children: React.ReactNode;
  className?: string;
  delay?: number;
}) {
  return (
    <motion.div
      className={className}
      initial="hidden"
      animate="visible"
      exit="exit"
      variants={fadeInUp}
      transition={{ ...springs.gentle, delay }}
    >
      {children}
    </motion.div>
  );
}

/**
 * Stagger container that animates its direct children sequentially.
 *
 * Uses either `staggerContainer` (default, 60 ms cadence) or
 * `staggerContainerFast` (35 ms cadence when `fast` is `true`).  Pair with
 * `MotionItem` children so each item enters with the `listItem` variant.
 *
 * @param children - List items, typically `MotionItem` elements.
 * @param className - Optional CSS class forwarded to the wrapping `div`.
 * @param fast - When `true`, uses the fast-cadence stagger container
 *               (`staggerContainerFast`). Default `false`.
 *
 * @example
 * ```tsx
 * <MotionList fast>
 *   {trades.map(t => <MotionItem key={t.id}>{t.symbol}</MotionItem>)}
 * </MotionList>
 * ```
 */
export function MotionList({
  children,
  className,
  fast = false,
}: {
  children: React.ReactNode;
  className?: string;
  fast?: boolean;
}) {
  return (
    <motion.div
      className={className}
      initial="hidden"
      animate="visible"
      exit="exit"
      variants={fast ? staggerContainerFast : staggerContainer}
    >
      {children}
    </motion.div>
  );
}

/**
 * Individual animated list item for use inside `MotionList`.
 *
 * Applies the `listItem` variant and a `springs.snappy` transition so each
 * item slides up and sharpens into view as its parent stagger timer fires.
 *
 * @param children - Item content.
 * @param className - Optional CSS class forwarded to the wrapping `div`.
 *
 * @example
 * ```tsx
 * <MotionList>
 *   {rows.map(r => (
 *     <MotionItem key={r.id} className="py-2">
 *       {r.name}
 *     </MotionItem>
 *   ))}
 * </MotionList>
 * ```
 */
export function MotionItem({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <motion.div
      className={className}
      variants={listItem}
      transition={springs.snappy}
    >
      {children}
    </motion.div>
  );
}

/**
 * Scale-and-blur entrance wrapper for modal dialogs and floating cards.
 *
 * Uses the `scaleIn` variant with a `springs.bouncy` transition, giving the
 * panel a subtle overshoot that conveys depth without being distracting.
 *
 * @param children - Modal or card content.
 * @param className - Optional CSS class forwarded to the wrapping `div`.
 *
 * @example
 * ```tsx
 * <MotionPresence>
 *   {open && (
 *     <MotionPopup key="panel" className="rounded-xl shadow-xl p-6">
 *       <TradeDetails trade={selected} />
 *     </MotionPopup>
 *   )}
 * </MotionPresence>
 * ```
 */
export function MotionPopup({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <motion.div
      className={className}
      initial="hidden"
      animate="visible"
      exit="exit"
      variants={scaleIn}
      transition={springs.bouncy}
    >
      {children}
    </motion.div>
  );
}

/**
 * Interactive hover-lift and tap-press wrapper.
 *
 * Translates the element upward and scales it slightly on hover, then
 * presses it slightly on tap, providing tactile feedback for clickable cards
 * and buttons.  Both magnitudes are configurable.
 *
 * @param children - Clickable content.
 * @param className - Optional CSS class forwarded to the wrapping `div`.
 * @param lift - Upward translation in pixels on hover (default `3`).
 * @param scale - Scale multiplier on hover (default `1.02`).
 *
 * @example
 * ```tsx
 * <MotionHover lift={4} scale={1.03}>
 *   <AssetCard symbol="AAPL" />
 * </MotionHover>
 * ```
 */
export function MotionHover({
  children,
  className,
  lift = 3,
  scale = 1.02,
}: {
  children: React.ReactNode;
  className?: string;
  lift?: number;
  scale?: number;
}) {
  return (
    <motion.div
      className={className}
      whileHover={{ y: -lift, scale, transition: springs.snappy }}
      whileTap={{ y: 1, scale: 0.98, transition: { duration: 0.1 } }}
    >
      {children}
    </motion.div>
  );
}

/**
 * Animated numeric counter that smoothly interpolates between values.
 *
 * When the `value` prop changes, the displayed number eases from the previous
 * value to the new one using a cubic `easeOut` curve.  Duration is clamped
 * between 200 ms and 600 ms and scales with the magnitude of the change so
 * large jumps feel proportionally weighty.  A brief scale pulse on each new
 * `value` draws the eye to the update.
 *
 * An optional `format` callback lets you display the interpolated value as
 * currency, percentage, or any other string representation.
 *
 * @param value - Target numeric value.  Changing this prop triggers the animation.
 * @param className - Optional CSS class forwarded to the wrapping `span`.
 * @param format - Optional formatter called with the current interpolated
 *                 number on every animation frame.  Defaults to
 *                 `Math.round(n).toString()`.
 *
 * @example
 * ```tsx
 * // Plain integer
 * <MotionNumber value={totalTrades} />
 *
 * // Currency
 * <MotionNumber
 *   value={portfolioValue}
 *   format={n => `$${n.toFixed(2)}`}
 * />
 * ```
 */
export function MotionNumber({
  value,
  className,
  format,
}: {
  value: number;
  className?: string;
  format?: (n: number) => string;
}) {
  const [displayed, setDisplayed] = React.useState(value);
  const ref = React.useRef<HTMLSpanElement>(null);

  React.useEffect(() => {
    const start = displayed;
    const diff = value - start;
    if (diff === 0) return;
    const duration = Math.min(600, Math.abs(diff) * 20 + 200);
    const startTime = performance.now();
    let raf: number;

    function tick(now: number) {
      const progress = Math.min((now - startTime) / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      setDisplayed(start + diff * eased);
      if (progress < 1) raf = requestAnimationFrame(tick);
    }

    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  return (
    <motion.span
      ref={ref}
      className={className}
      key={value}
      initial={{ scale: 1 }}
      animate={{ scale: [1, 1.05, 1] }}
      transition={{ duration: 0.3, ease: easings.easeOut }}
    >
      {format ? format(displayed) : Math.round(displayed)}
    </motion.span>
  );
}

/**
 * Thin wrapper around Framer Motion's `AnimatePresence`.
 *
 * Provides a consistent default `mode` of `"wait"` (the most common choice
 * for conditional rendering, where the exiting element fully leaves before
 * the entering one appears) while still exposing all three modes via the
 * `mode` prop.
 *
 * Wrap any conditionally-rendered `motion.*` element or Motion component
 * inside `MotionPresence` so that exit animations play correctly.
 *
 * @param children - One or more conditionally-rendered Motion elements.
 * @param mode - AnimatePresence mode.
 *   - `"wait"` (default) — exit then enter
 *   - `"sync"` — exit and enter simultaneously
 *   - `"popLayout"` — exit with layout animation
 *
 * @example
 * ```tsx
 * <MotionPresence>
 *   {selectedTab === "overview" && <OverviewPanel key="overview" />}
 *   {selectedTab === "trades"   && <TradesPanel   key="trades"   />}
 * </MotionPresence>
 * ```
 */
export function MotionPresence({
  children,
  mode = "wait",
}: {
  children: React.ReactNode;
  mode?: "wait" | "sync" | "popLayout";
}) {
  return <AnimatePresence mode={mode}>{children}</AnimatePresence>;
}

/**
 * Pulsing skeleton placeholder for loading states.
 *
 * Continuously animates opacity (0.4 → 0.7 → 0.4) and a barely-perceptible
 * scale (1 → 1.005 → 1) on an infinite loop to indicate that content is
 * loading.  Apply a background colour and border-radius via `className` to
 * match the shape of the content it replaces.
 *
 * @param className - CSS class that sets the skeleton's size, background,
 *                    and border-radius (e.g. `"h-4 w-32 rounded bg-muted"`).
 *
 * @example
 * ```tsx
 * {isLoading ? (
 *   <MotionSkeleton className="h-6 w-48 rounded-md bg-muted" />
 * ) : (
 *   <span>{portfolioName}</span>
 * )}
 * ```
 */
export function MotionSkeleton({ className }: { className?: string }) {
  return (
    <motion.div
      className={className}
      animate={{
        opacity: [0.4, 0.7, 0.4],
        scale: [1, 1.005, 1],
      }}
      transition={{
        duration: 1.8,
        repeat: Infinity,
        ease: "easeInOut",
      }}
    />
  );
}

