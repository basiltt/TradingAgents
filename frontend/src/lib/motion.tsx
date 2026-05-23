"use client";

import { motion, AnimatePresence, type Variants, type Transition } from "framer-motion";
import * as React from "react";

// ═══ Spring Presets ═══
export const springs = {
  snappy: { type: "spring", stiffness: 500, damping: 30, mass: 0.8 } as Transition,
  bouncy: { type: "spring", stiffness: 400, damping: 25, mass: 1 } as Transition,
  gentle: { type: "spring", stiffness: 200, damping: 20, mass: 1 } as Transition,
  stiff: { type: "spring", stiffness: 700, damping: 35, mass: 0.6 } as Transition,
  slow: { type: "spring", stiffness: 100, damping: 20, mass: 1.2 } as Transition,
} as const;

// ═══ Easing Presets ═══
export const easings = {
  easeOut: [0.22, 1, 0.36, 1] as [number, number, number, number],
  easeInOut: [0.65, 0, 0.35, 1] as [number, number, number, number],
  elastic: [0.68, -0.55, 0.265, 1.55] as [number, number, number, number],
};

// ═══ Variant Presets ═══
export const fadeInUp: Variants = {
  hidden: { opacity: 0, y: 16, filter: "blur(4px)" },
  visible: { opacity: 1, y: 0, filter: "blur(0px)" },
  exit: { opacity: 0, y: -8, filter: "blur(2px)" },
};

export const fadeIn: Variants = {
  hidden: { opacity: 0 },
  visible: { opacity: 1 },
  exit: { opacity: 0 },
};

export const scaleIn: Variants = {
  hidden: { opacity: 0, scale: 0.92, filter: "blur(4px)" },
  visible: { opacity: 1, scale: 1, filter: "blur(0px)" },
  exit: { opacity: 0, scale: 0.95, filter: "blur(2px)" },
};

export const slideInRight: Variants = {
  hidden: { opacity: 0, x: 20, filter: "blur(3px)" },
  visible: { opacity: 1, x: 0, filter: "blur(0px)" },
  exit: { opacity: 0, x: -10, filter: "blur(2px)" },
};

export const slideInLeft: Variants = {
  hidden: { opacity: 0, x: -20, filter: "blur(3px)" },
  visible: { opacity: 1, x: 0, filter: "blur(0px)" },
  exit: { opacity: 0, x: 10, filter: "blur(2px)" },
};

export const popIn: Variants = {
  hidden: { opacity: 0, scale: 0.8 },
  visible: { opacity: 1, scale: 1, transition: springs.bouncy },
  exit: { opacity: 0, scale: 0.9 },
};

export const listItem: Variants = {
  hidden: { opacity: 0, y: 12, scale: 0.97 },
  visible: { opacity: 1, y: 0, scale: 1 },
  exit: { opacity: 0, y: -8, scale: 0.97 },
};

// ═══ Stagger container ═══
export const staggerContainer: Variants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: { staggerChildren: 0.06, delayChildren: 0.04 },
  },
};

export const staggerContainerFast: Variants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: { staggerChildren: 0.035, delayChildren: 0.02 },
  },
};

// ═══ Animated Components ═══

/** Fade-in wrapper for page/section content */
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

/** Staggered list animation container */
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

/** Individual list item with stagger animation */
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

/** Scale-in popup effect */
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

/** Hover interaction wrapper — lifts and scales on hover, presses on tap */
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

/** Number counter animation */
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

/** Presence wrapper for conditional mount/unmount animations */
export function MotionPresence({
  children,
  mode = "wait",
}: {
  children: React.ReactNode;
  mode?: "wait" | "sync" | "popLayout";
}) {
  return <AnimatePresence mode={mode}>{children}</AnimatePresence>;
}

/** Skeleton pulse that feels alive */
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

// Re-export motion and AnimatePresence for direct use
export { motion, AnimatePresence };
