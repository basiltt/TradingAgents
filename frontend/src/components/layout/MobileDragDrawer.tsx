import { useCallback, useEffect, useRef } from "react";
import { motion, AnimatePresence, useMotionValue, useTransform, animate } from "framer-motion";
import { NeuSurface } from "@/design-system/neumorphism";

const DRAWER_WIDTH = 320;
const EDGE_THRESHOLD = 24;
const VELOCITY_THRESHOLD = 300;
const OPEN_THRESHOLD = 0.35;

export function MobileDragDrawer({
  open,
  onOpenChange,
  children,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  children: React.ReactNode;
}) {
  const x = useMotionValue(open ? 0 : -DRAWER_WIDTH);
  const backdropOpacity = useTransform(x, [-DRAWER_WIDTH, 0], [0, 0.5]);
  const isDragging = useRef(false);
  const touchStartX = useRef(0);
  const touchStartY = useRef(0);
  const touchStartTime = useRef(0);
  const directionLocked = useRef<"horizontal" | "vertical" | null>(null);
  const drawerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    animate(x, open ? 0 : -DRAWER_WIDTH, {
      type: "spring",
      stiffness: 400,
      damping: 35,
      mass: 0.8,
    });
  }, [open, x]);

  // Lock body scroll when open
  useEffect(() => {
    if (open) {
      const scrollY = window.scrollY;
      document.body.style.position = "fixed";
      document.body.style.top = `-${scrollY}px`;
      document.body.style.left = "0";
      document.body.style.right = "0";
      document.body.style.overflow = "hidden";
      return () => {
        document.body.style.position = "";
        document.body.style.top = "";
        document.body.style.left = "";
        document.body.style.right = "";
        document.body.style.overflow = "";
        window.scrollTo(0, scrollY);
      };
    }
  }, [open]);

  const handleTouchStart = useCallback(
    (e: TouchEvent) => {
      const touch = e.touches[0];
      touchStartX.current = touch.clientX;
      touchStartY.current = touch.clientY;
      touchStartTime.current = Date.now();
      directionLocked.current = null;

      if (!open && touch.clientX <= EDGE_THRESHOLD) {
        // Edge swipe to open
        isDragging.current = true;
        x.set(-DRAWER_WIDTH);
      } else if (open) {
        // Only allow close-drag from the backdrop area (outside drawer)
        const drawerEl = drawerRef.current;
        if (drawerEl) {
          const rect = drawerEl.getBoundingClientRect();
          const isInsideDrawer =
            touch.clientX >= rect.left &&
            touch.clientX <= rect.right &&
            touch.clientY >= rect.top &&
            touch.clientY <= rect.bottom;
          if (!isInsideDrawer) {
            isDragging.current = true;
          }
        }
      }
    },
    [open, x],
  );

  const handleTouchMove = useCallback(
    (e: TouchEvent) => {
      if (!isDragging.current) return;

      const touch = e.touches[0];
      const dx = touch.clientX - touchStartX.current;
      const dy = touch.clientY - touchStartY.current;

      // Lock direction on first significant movement
      if (!directionLocked.current && (Math.abs(dx) > 8 || Math.abs(dy) > 8)) {
        directionLocked.current = Math.abs(dy) > Math.abs(dx) ? "vertical" : "horizontal";
      }

      // Cancel drag if vertical scroll wins
      if (directionLocked.current === "vertical") {
        isDragging.current = false;
        return;
      }

      let newX: number;
      if (open) {
        newX = Math.min(0, Math.max(-DRAWER_WIDTH, dx));
      } else {
        newX = Math.min(0, Math.max(-DRAWER_WIDTH, -DRAWER_WIDTH + dx));
      }
      x.set(newX);

      if (directionLocked.current === "horizontal") {
        e.preventDefault();
      }
    },
    [open, x],
  );

  const handleTouchEnd = useCallback(
    (e: TouchEvent) => {
      if (!isDragging.current) return;
      isDragging.current = false;
      directionLocked.current = null;

      const touch = e.changedTouches[0];
      const dx = touch.clientX - touchStartX.current;
      const currentX = x.get();
      const progress = (currentX + DRAWER_WIDTH) / DRAWER_WIDTH;

      const elapsed = (Date.now() - touchStartTime.current) / 1000;
      const velocity = dx / Math.max(elapsed, 0.016);

      let shouldOpen: boolean;
      if (Math.abs(velocity) > VELOCITY_THRESHOLD) {
        shouldOpen = velocity > 0;
      } else {
        shouldOpen = progress > OPEN_THRESHOLD;
      }

      onOpenChange(shouldOpen);
      animate(x, shouldOpen ? 0 : -DRAWER_WIDTH, {
        type: "spring",
        stiffness: 400,
        damping: 35,
        mass: 0.8,
      });
    },
    [onOpenChange, x],
  );

  useEffect(() => {
    const mq = window.matchMedia("(max-width: 1023px)");

    function attach() {
      if (!mq.matches) return;
      document.addEventListener("touchstart", handleTouchStart, { passive: true });
      document.addEventListener("touchmove", handleTouchMove, { passive: false });
      document.addEventListener("touchend", handleTouchEnd, { passive: true });
    }

    function detach() {
      document.removeEventListener("touchstart", handleTouchStart);
      document.removeEventListener("touchmove", handleTouchMove);
      document.removeEventListener("touchend", handleTouchEnd);
    }

    function handleChange() {
      detach();
      attach();
    }

    attach();
    mq.addEventListener("change", handleChange);

    return () => {
      detach();
      mq.removeEventListener("change", handleChange);
    };
  }, [handleTouchStart, handleTouchMove, handleTouchEnd]);

  return (
    <div className="lg:hidden">
      {/* Backdrop — driven by motion value, always mounted when open */}
      <AnimatePresence>
        {open && (
          <motion.div
            className="fixed inset-0 z-40"
            style={{ backgroundColor: `rgba(0,0,0,1)`, opacity: backdropOpacity }}
            initial={{ opacity: 0 }}
            animate={{ opacity: 0.5 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            onClick={() => onOpenChange(false)}
            aria-hidden="true"
          />
        )}
      </AnimatePresence>

      {/* Drawer panel */}
      <motion.div
        ref={drawerRef}
        className="fixed top-0 left-0 z-50 h-[100dvh] w-[min(100vw,20rem)]"
        style={{ x, pointerEvents: open ? "auto" : "none" }}
        role="dialog"
        aria-modal={open}
        aria-label="Navigation menu"
        aria-hidden={!open}
      >
        <NeuSurface
          depth="raised"
          radius="lg"
          padding="md"
          className="flex h-full flex-col overflow-hidden shadow-none"
        >
          <div className="neu-scrollbar min-h-0 flex-1 overflow-y-auto overscroll-contain pb-[env(safe-area-inset-bottom,0.5rem)]">
            {children}
          </div>
        </NeuSurface>
      </motion.div>

      {/* Edge hit area for discoverability — touch-transparent, just extends hit zone */}
      {!open && (
        <div
          className="fixed top-0 left-0 z-30 h-full"
          style={{ width: EDGE_THRESHOLD, touchAction: "pan-y" }}
          aria-hidden="true"
        />
      )}
    </div>
  );
}
