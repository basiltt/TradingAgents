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

export function MotionPresence({
  children,
  mode = "wait",
}: {
  children: React.ReactNode;
  mode?: "wait" | "sync" | "popLayout";
}) {
  return <AnimatePresence mode={mode}>{children}</AnimatePresence>;
}

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

