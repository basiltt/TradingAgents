/**
 * @module motion-constants
 *
 * Shared Framer Motion animation presets for the TradingAgents frontend.
 *
 * This module centralises every reusable spring configuration, cubic-bezier
 * easing curve, and `Variants` object so that individual components never
 * hard-code animation values.  Import from here rather than defining
 * transitions inline to keep the motion language consistent across the UI.
 *
 * @example
 * ```ts
 * import { springs, fadeInUp } from "@/lib/motion-constants";
 *
 * <motion.div variants={fadeInUp} transition={springs.gentle} />
 * ```
 */
import type { Variants, Transition } from "framer-motion";

// ---------------------------------------------------------------------------
// Spring Presets
// ---------------------------------------------------------------------------

/**
 * Named spring transition presets.
 *
 * Each entry is a complete Framer Motion `Transition` object of type
 * `"spring"` that can be spread directly into a `transition` prop or used
 * inside a `Variants` definition.
 *
 * | Key      | Feel                                      |
 * |----------|-------------------------------------------|
 * | snappy   | Fast, crisp — ideal for interactive UI    |
 * | bouncy   | Playful overshoot — badges, pop-ins       |
 * | gentle   | Smooth, unhurried — section entrances     |
 * | stiff    | Tight, near-instant — micro-interactions  |
 * | slow     | Deliberate, weighty — large panels        |
 *
 * @example
 * ```tsx
 * <motion.div transition={springs.snappy} animate={{ x: 0 }} />
 * ```
 */
export const springs = {
  snappy: { type: "spring", stiffness: 500, damping: 30, mass: 0.8 } as Transition,
  bouncy: { type: "spring", stiffness: 400, damping: 25, mass: 1 } as Transition,
  gentle: { type: "spring", stiffness: 200, damping: 20, mass: 1 } as Transition,
  stiff: { type: "spring", stiffness: 700, damping: 35, mass: 0.6 } as Transition,
  slow: { type: "spring", stiffness: 100, damping: 20, mass: 1.2 } as Transition,
} as const;

// ---------------------------------------------------------------------------
// Easing Presets
// ---------------------------------------------------------------------------

/**
 * Named cubic-bezier easing curves expressed as four-number tuples compatible
 * with Framer Motion's `ease` transition property.
 *
 * | Key       | Curve shape                                      |
 * |-----------|--------------------------------------------------|
 * | easeOut   | Standard deceleration — most content transitions |
 * | easeInOut | Symmetric — used for looping or reversible anim  |
 * | elastic   | Slight overshoot — numbers, counters              |
 *
 * @example
 * ```tsx
 * <motion.span transition={{ ease: easings.easeOut, duration: 0.3 }} />
 * ```
 */
export const easings = {
  easeOut: [0.22, 1, 0.36, 1] as [number, number, number, number],
  easeInOut: [0.65, 0, 0.35, 1] as [number, number, number, number],
  elastic: [0.68, -0.55, 0.265, 1.55] as [number, number, number, number],
};

// ---------------------------------------------------------------------------
// Variant Presets
// ---------------------------------------------------------------------------

/**
 * Fade-and-rise entrance variant with a blur dissolve.
 *
 * - `hidden`  — transparent, shifted 16 px down, blurred 4 px
 * - `visible` — fully opaque, at natural position, sharp
 * - `exit`    — transparent, shifted 8 px up, lightly blurred
 *
 * Use with `MotionSection` or directly on a `motion.*` element when a page
 * section should slide gently into view on mount.
 */
export const fadeInUp: Variants = {
  hidden: { opacity: 0, y: 16, filter: "blur(4px)" },
  visible: { opacity: 1, y: 0, filter: "blur(0px)" },
  exit: { opacity: 0, y: -8, filter: "blur(2px)" },
};

/**
 * Simple opacity-only fade variant.
 *
 * - `hidden`  — transparent
 * - `visible` — fully opaque
 * - `exit`    — transparent
 *
 * Use when positional or scale animation would be distracting (e.g. overlays,
 * tooltips).
 */
export const fadeIn: Variants = {
  hidden: { opacity: 0 },
  visible: { opacity: 1 },
  exit: { opacity: 0 },
};

/**
 * Scale-and-blur entrance variant.
 *
 * - `hidden`  — 92 % size, transparent, blurred 4 px
 * - `visible` — natural size, opaque, sharp
 * - `exit`    — 95 % size, transparent, lightly blurred
 *
 * Use with `MotionPopup` or for modal/card entrances.
 */
export const scaleIn: Variants = {
  hidden: { opacity: 0, scale: 0.92, filter: "blur(4px)" },
  visible: { opacity: 1, scale: 1, filter: "blur(0px)" },
  exit: { opacity: 0, scale: 0.95, filter: "blur(2px)" },
};

/**
 * Slide-in from the right with a blur dissolve.
 *
 * - `hidden`  — shifted 20 px right, transparent, blurred 3 px
 * - `visible` — at natural position, opaque, sharp
 * - `exit`    — shifted 10 px left, transparent, lightly blurred
 *
 * Use for drawer panels, side-sheet entrances, or right-to-left page transitions.
 */
export const slideInRight: Variants = {
  hidden: { opacity: 0, x: 20, filter: "blur(3px)" },
  visible: { opacity: 1, x: 0, filter: "blur(0px)" },
  exit: { opacity: 0, x: -10, filter: "blur(2px)" },
};

/**
 * Slide-in from the left with a blur dissolve.
 *
 * Mirror of `slideInRight`.  Use for left-to-right page transitions or
 * panels that enter from the left edge.
 */
export const slideInLeft: Variants = {
  hidden: { opacity: 0, x: -20, filter: "blur(3px)" },
  visible: { opacity: 1, x: 0, filter: "blur(0px)" },
  exit: { opacity: 0, x: 10, filter: "blur(2px)" },
};

/**
 * Bouncy pop-in scale variant.
 *
 * - `hidden`  — 80 % size, transparent
 * - `visible` — natural size, opaque (uses `springs.bouncy` internally)
 * - `exit`    — 90 % size, transparent
 *
 * Use for badges, notification dots, or any element that should "pop" on
 * arrival.  The `springs.bouncy` transition is embedded in `visible` so no
 * additional `transition` prop is required.
 */
export const popIn: Variants = {
  hidden: { opacity: 0, scale: 0.8 },
  visible: { opacity: 1, scale: 1, transition: springs.bouncy },
  exit: { opacity: 0, scale: 0.9 },
};

/**
 * Individual list-item variant intended to be used as a child inside a
 * stagger container (`staggerContainer` or `staggerContainerFast`).
 *
 * - `hidden`  — shifted 12 px down, 97 % scale, transparent
 * - `visible` — at natural position and size, opaque
 * - `exit`    — shifted 8 px up, 97 % scale, transparent
 *
 * Pair with `MotionList` + `MotionItem` for animated list rendering.
 */
export const listItem: Variants = {
  hidden: { opacity: 0, y: 12, scale: 0.97 },
  visible: { opacity: 1, y: 0, scale: 1 },
  exit: { opacity: 0, y: -8, scale: 0.97 },
};

// ---------------------------------------------------------------------------
// Stagger Containers
// ---------------------------------------------------------------------------

/**
 * Stagger container variant — standard cadence (60 ms between children).
 *
 * Orchestrates child animations by staggering them 60 ms apart with a 40 ms
 * initial delay.  The container itself fades in (`opacity: 0 → 1`) while its
 * children animate independently via their own variants (e.g. `listItem`).
 *
 * Use as the `variants` prop on a wrapping `motion.div` when the children
 * should enter sequentially at a relaxed pace.
 *
 * @example
 * ```tsx
 * <motion.ul variants={staggerContainer} initial="hidden" animate="visible">
 *   {items.map(i => <motion.li key={i} variants={listItem} />)}
 * </motion.ul>
 * ```
 */
export const staggerContainer: Variants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: { staggerChildren: 0.06, delayChildren: 0.04 },
  },
};

/**
 * Stagger container variant — fast cadence (35 ms between children).
 *
 * Same shape as `staggerContainer` but with tighter timing for dense lists
 * or dashboards where a slower stagger would feel sluggish.
 *
 * @example
 * ```tsx
 * <MotionList fast>
 *   {rows.map(r => <MotionItem key={r.id}>{r.label}</MotionItem>)}
 * </MotionList>
 * ```
 */
export const staggerContainerFast: Variants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: { staggerChildren: 0.035, delayChildren: 0.02 },
  },
};
