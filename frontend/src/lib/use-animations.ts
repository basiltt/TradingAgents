"use client";

import * as React from "react";

/** Tracks mouse position relative to an element for magnetic/tilt effects */
export function useMousePosition(ref: React.RefObject<HTMLElement | null>) {
  const [position, setPosition] = React.useState({ x: 0.5, y: 0.5 });

  React.useEffect(() => {
    const el = ref.current;
    if (!el) return;

    function handleMove(e: MouseEvent) {
      const rect = el!.getBoundingClientRect();
      setPosition({
        x: (e.clientX - rect.left) / rect.width,
        y: (e.clientY - rect.top) / rect.height,
      });
    }

    function handleLeave() {
      setPosition({ x: 0.5, y: 0.5 });
    }

    el.addEventListener("mousemove", handleMove);
    el.addEventListener("mouseleave", handleLeave);
    return () => {
      el.removeEventListener("mousemove", handleMove);
      el.removeEventListener("mouseleave", handleLeave);
    };
  }, [ref]);

  return position;
}

/** Ripple effect hook — sets CSS variables on click */
export function useRipple(ref: React.RefObject<HTMLElement | null>) {
  React.useEffect(() => {
    const el = ref.current;
    if (!el) return;

    function handleClick(e: MouseEvent) {
      const rect = el!.getBoundingClientRect();
      const x = ((e.clientX - rect.left) / rect.width) * 100;
      const y = ((e.clientY - rect.top) / rect.height) * 100;
      el!.style.setProperty("--ripple-x", `${x}%`);
      el!.style.setProperty("--ripple-y", `${y}%`);
    }

    el.addEventListener("mousedown", handleClick);
    return () => el.removeEventListener("mousedown", handleClick);
  }, [ref]);
}

/** Magnetic pull toward cursor */
export function useMagnetic(ref: React.RefObject<HTMLElement | null>, strength = 0.3) {
  React.useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const prefersReduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (prefersReduced) return;

    function handleMove(e: MouseEvent) {
      const rect = el!.getBoundingClientRect();
      const centerX = rect.left + rect.width / 2;
      const centerY = rect.top + rect.height / 2;
      const dx = (e.clientX - centerX) * strength;
      const dy = (e.clientY - centerY) * strength;
      el!.style.transform = `translate(${dx}px, ${dy}px)`;
    }

    function handleLeave() {
      el!.style.transform = "translate(0, 0)";
    }

    el.addEventListener("mousemove", handleMove);
    el.addEventListener("mouseleave", handleLeave);
    return () => {
      el.removeEventListener("mousemove", handleMove);
      el.removeEventListener("mouseleave", handleLeave);
    };
  }, [ref, strength]);
}

/** Smooth 3D tilt on hover */
export function useTilt(ref: React.RefObject<HTMLElement | null>, maxDeg = 4) {
  React.useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const prefersReduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (prefersReduced) return;

    function handleMove(e: MouseEvent) {
      const rect = el!.getBoundingClientRect();
      const x = (e.clientX - rect.left) / rect.width - 0.5;
      const y = (e.clientY - rect.top) / rect.height - 0.5;
      el!.style.transform = `perspective(800px) rotateX(${-y * maxDeg}deg) rotateY(${x * maxDeg}deg) translateZ(4px)`;
    }

    function handleLeave() {
      el!.style.transform = "perspective(800px) rotateX(0) rotateY(0) translateZ(0)";
    }

    el.addEventListener("mousemove", handleMove);
    el.addEventListener("mouseleave", handleLeave);
    return () => {
      el.removeEventListener("mousemove", handleMove);
      el.removeEventListener("mouseleave", handleLeave);
    };
  }, [ref, maxDeg]);
}

/** Detects if element is in viewport — triggers animation once */
export function useInView(ref: React.RefObject<HTMLElement | null>, options?: IntersectionObserverInit) {
  const [inView, setInView] = React.useState(false);

  React.useEffect(() => {
    const el = ref.current;
    if (!el) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setInView(true);
          observer.disconnect();
        }
      },
      { threshold: 0.1, ...options },
    );

    observer.observe(el);
    return () => observer.disconnect();
  }, [ref, options]);

  return inView;
}

/** Value change detection — returns true briefly when value changes */
export function useValueChange(value: number | string) {
  const [changed, setChanged] = React.useState(false);
  const prev = React.useRef(value);

  React.useEffect(() => {
    if (prev.current !== value) {
      setChanged(true);
      prev.current = value;
      const timer = setTimeout(() => setChanged(false), 800);
      return () => clearTimeout(timer);
    }
  }, [value]);

  return changed;
}
