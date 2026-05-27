import type { Variants, Transition } from "framer-motion";

// Spring Presets
export const springs = {
  snappy: { type: "spring", stiffness: 500, damping: 30, mass: 0.8 } as Transition,
  bouncy: { type: "spring", stiffness: 400, damping: 25, mass: 1 } as Transition,
  gentle: { type: "spring", stiffness: 200, damping: 20, mass: 1 } as Transition,
  stiff: { type: "spring", stiffness: 700, damping: 35, mass: 0.6 } as Transition,
  slow: { type: "spring", stiffness: 100, damping: 20, mass: 1.2 } as Transition,
} as const;

// Easing Presets
export const easings = {
  easeOut: [0.22, 1, 0.36, 1] as [number, number, number, number],
  easeInOut: [0.65, 0, 0.35, 1] as [number, number, number, number],
  elastic: [0.68, -0.55, 0.265, 1.55] as [number, number, number, number],
};

// Variant Presets
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

// Stagger container
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
